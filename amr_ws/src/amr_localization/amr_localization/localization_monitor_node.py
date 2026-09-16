"""localization_monitor_node: readiness over AMCL (spec §4.3).

Feeds amr_localization.readiness with /amcl_pose covariance, map->odom samples
(10 Hz from TF), /initialpose sightings and sensor/TF ages, and publishes
/amr/localization_state (latched, on change and at 2 Hz). Services:

  /amr/localization/confirm  Trigger  operator: scans align with fixed structure -> READY
  /amr/localization/reset    Trigger  back to UNLOCALIZED

/initialpose is only observed here; AMCL subscribes to it itself. The
executor (T7) faults if one arrives during a segment.
"""

from __future__ import annotations

import math

import numpy as np
import rclpy
import rclpy.duration
from amr_maps.raycast import ScanGeometry, cast
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu, LaserScan
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener

from amr_interfaces.msg import LocalizationState, WheelStates
from amr_localization import readiness as rd
from amr_maps import grid as gridio

SENSOR_DATA = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)
LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)


class LocalizationMonitor(Node):
    def __init__(self) -> None:
        super().__init__("localization_monitor")
        self.declare_parameter("cov_xy_max", 0.05)
        self.declare_parameter("cov_yaw_max", 0.03)
        self.declare_parameter("cov_hold_s", 1.0)
        self.declare_parameter("jump_dist_m", 0.15)
        self.declare_parameter("jump_angle_deg", 5.0)
        self.declare_parameter("settle_s", 2.0)
        self.declare_parameter("initial_grace_s", 1.5)
        self.declare_parameter("scan_age_limit_s", 0.15)
        self.declare_parameter("generation", 0)  # layer generation (unified plan U0)
        self.generation = int(self.get_parameter("generation").value)
        self.declare_parameter("wheels_age_limit_s", 0.10)
        self.declare_parameter("imu_age_limit_s", 0.20)
        self.declare_parameter("tf_age_limit_s", 0.20)
        self.declare_parameter("min_scan_match", 0.6)
        self.declare_parameter("max_scan_long", 0.15)
        self.declare_parameter("match_hold_s", 1.0)
        self.declare_parameter("match_tolerance_m", 0.15)
        self.declare_parameter("match_period_s", 0.5)
        self.declare_parameter(
            "match_max_range_m", 10.0
        )  # beyond this a 0.3 deg yaw error exceeds the tolerance
        p = self.get_parameter
        self.rd = rd.Readiness(
            rd.Limits(
                cov_xy_max=p("cov_xy_max").value,
                cov_yaw_max=p("cov_yaw_max").value,
                cov_hold_s=p("cov_hold_s").value,
                min_scan_match=p("min_scan_match").value,
                max_scan_long=p("max_scan_long").value,
                match_hold_s=p("match_hold_s").value,
                jump_dist_m=p("jump_dist_m").value,
                jump_angle_rad=math.radians(p("jump_angle_deg").value),
                settle_s=p("settle_s").value,
                initial_grace_s=p("initial_grace_s").value,
                age_limits={
                    "scan": p("scan_age_limit_s").value,
                    "wheels": p("wheels_age_limit_s").value,
                    "imu": p("imu_age_limit_s").value,
                    "tf": p("tf_age_limit_s").value,
                },
            )
        )
        self._last: dict[str, float] = {}
        self._last_state: int | None = None
        self._last_reason = ""
        self._match_tol_cells = 0
        self._match_period = p("match_period_s").value
        self._match_tol = p("match_tolerance_m").value
        self._match_max_range = p("match_max_range_m").value
        self._occ_near: np.ndarray | None = None  # occupied cells dilated by the tolerance
        self._grid: gridio.Grid | None = None  # the saved map, raycast for expected ranges
        self._last_match_t = 0.0

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl, 10)
        self.create_subscription(PoseWithCovarianceStamped, "/initialpose", self._on_initialpose, RELIABLE_1)
        self.create_subscription(LaserScan, "/scan", self._on_scan, SENSOR_DATA)
        self.create_subscription(OccupancyGrid, "/map", self._on_map, LATCHED)
        self.create_subscription(WheelStates, "/wheel_states", lambda _m: self._touch("wheels"), SENSOR_DATA)
        self.create_subscription(Imu, "/imu/data", lambda _m: self._touch("imu"), SENSOR_DATA)
        self.create_service(Trigger, "/amr/localization/confirm", self._srv_confirm)
        self.create_service(Trigger, "/amr/localization/reset", self._srv_reset)
        self._pub = self.create_publisher(LocalizationState, "/amr/localization_state", LATCHED)
        self.create_timer(0.1, self._tick)
        self.create_timer(0.5, self._publish)
        self.get_logger().info("UNLOCALIZED: waiting for /initialpose")

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _touch(self, key: str) -> None:
        self._last[key] = self._now()

    def _on_map(self, msg: OccupancyGrid) -> None:
        grid = gridio.from_occupancy_grid_msg(msg)
        occ = grid.data >= 65
        cells = max(1, int(round(self._match_tol / grid.meta.resolution)))
        near = np.zeros_like(occ)
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                near |= np.roll(np.roll(occ, dr, axis=0), dc, axis=1)
        self._occ_near, self._grid = near, grid
        self.get_logger().info(f"map {grid.width}x{grid.height} loaded for scan consistency")

    def _on_scan(self, msg: LaserScan) -> None:
        self._touch("scan")
        t = self._now()
        if self._grid is None or t - self._last_match_t < self._match_period:
            return
        try:
            # At the scan's own stamp: during a turn the latest transform is a few
            # degrees ahead of the scan, which throws every long beam off the map.
            tr = self.tf_buffer.lookup_transform(
                "map", msg.header.frame_id, msg.header.stamp, timeout=rclpy.duration.Duration(seconds=0.05)
            )
        except Exception:  # noqa: BLE001 - not localised yet, or the stamp is not covered
            return
        self._last_match_t = t
        q = tr.transform.rotation
        yaw = math.atan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z)
        lx, ly = tr.transform.translation.x, tr.transform.translation.y
        ranges = np.asarray(msg.ranges, dtype=np.float64)
        n = len(ranges)
        max_r = min(msg.range_max, self._match_max_range)
        geom = ScanGeometry(
            msg.angle_min, msg.angle_min + (n - 1) * msg.angle_increment, n, msg.range_min, max_r
        )
        expected = cast(self._grid, lx, ly, yaw, geom)  # inf where the map has nothing within max_r
        measured = np.where(np.isfinite(ranges), ranges, np.inf)

        # long: the map says a wall is closer than what was measured -> beam went through it
        wall_expected = np.isfinite(expected)
        long = wall_expected & (measured > expected + self._match_tol)
        long_frac = float(long.sum()) / max(1, int(wall_expected.sum()))

        # match: endpoints near mapped obstacles (informational; clutter lowers it)
        valid = np.isfinite(ranges) & (ranges >= msg.range_min) & (ranges < max_r)
        if valid.sum() >= 20:
            a = geom.angles[valid] + yaw
            ex, ey = lx + ranges[valid] * np.cos(a), ly + ranges[valid] * np.sin(a)
            g = self._grid.meta
            cols = np.floor((ex - g.origin_x) / g.resolution).astype(int)
            rows = np.floor((ey - g.origin_y) / g.resolution).astype(int)
            inside = (cols >= 0) & (cols < self._grid.width) & (rows >= 0) & (rows < self._grid.height)
            hit = np.zeros(int(valid.sum()), dtype=bool)
            hit[inside] = self._occ_near[rows[inside], cols[inside]]
            match_frac = float(hit.mean())
        else:
            match_frac = 0.0
        self.rd.on_scan_match(t, match_frac, long_frac)

    def _on_amcl(self, msg: PoseWithCovarianceStamped) -> None:
        c = msg.pose.covariance
        self.rd.on_amcl_pose(self._now(), c[0], c[7], c[35])

    def _on_initialpose(self, _msg: PoseWithCovarianceStamped) -> None:
        self.rd.on_initialpose(self._now())
        self.get_logger().info("initial pose received: CHECKING")
        self._publish()

    def _tick(self) -> None:
        t = self._now()
        try:
            tr = self.tf_buffer.lookup_transform("map", "odom", rclpy.time.Time())
            q = tr.transform.rotation
            yaw = math.atan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z)
            stamp = tr.header.stamp.sec + tr.header.stamp.nanosec * 1e-9
            # AMCL stamps map->odom into the future by transform_tolerance; clamp the age at 0.
            self._last["tf"] = max(self._last.get("tf", 0.0), min(stamp, t))
            odom_base = None
            try:
                ob = self.tf_buffer.lookup_transform("odom", "base_footprint", rclpy.time.Time())
                oq = ob.transform.rotation
                odom_base = (
                    ob.transform.translation.x,
                    ob.transform.translation.y,
                    math.atan2(2.0 * oq.w * oq.z, 1.0 - 2.0 * oq.z * oq.z),
                )
            except Exception:  # noqa: BLE001
                pass
            self.rd.on_map_odom(t, tr.transform.translation.x, tr.transform.translation.y, yaw, odom_base)
        except Exception:  # noqa: BLE001 - no transform yet is a normal state
            pass
        ages = {k: (t - self._last[k]) if k in self._last else None for k in ("scan", "wheels", "imu", "tf")}
        self.rd.evaluate(t, ages)
        if self.rd.state != self._last_state or self.rd.reason != self._last_reason:
            if self.rd.state != self._last_state:
                self.get_logger().info(f"{rd.NAMES[self.rd.state]}: {self.rd.reason}")
            self._last_state, self._last_reason = self.rd.state, self.rd.reason
            self._publish()

    def _publish(self) -> None:
        t = self._now()
        m = LocalizationState()
        m.generation = self.generation
        m.header.stamp = self.get_clock().now().to_msg()
        m.state = self.rd.state
        m.operator_confirmed = self.rd.confirmed
        m.can_confirm = self.rd.can_confirm
        if self.rd.cov is not None:
            m.cov_xx, m.cov_yy, m.cov_yaw = self.rd.cov
        if self.rd.last_jump is not None:
            m.last_jump_m = self.rd.last_jump.dist_m
            m.last_jump_rad = self.rd.last_jump.angle_rad
            m.last_jump_stamp.sec = int(self.rd.last_jump.t)
            m.last_jump_stamp.nanosec = int((self.rd.last_jump.t % 1.0) * 1e9)
        for key, attr in (
            ("scan", "scan_age_s"),
            ("wheels", "wheels_age_s"),
            ("imu", "imu_age_s"),
            ("tf", "tf_age_s"),
        ):
            setattr(m, attr, (t - self._last[key]) if key in self._last else -1.0)
        m.amcl_age_s = (t - self.rd.cov_t) if self.rd.cov_t is not None else -1.0
        m.scan_match = self.rd.scan_match if self.rd.scan_match is not None else -1.0
        m.scan_long = self.rd.scan_long if self.rd.scan_long is not None else -1.0
        m.reason = self.rd.reason
        self._pub.publish(m)

    def _srv_confirm(self, _req, res: Trigger.Response):
        res.success = self.rd.confirm()
        res.message = (
            self.rd.reason if res.success else f"cannot confirm: {rd.NAMES[self.rd.state]} - {self.rd.reason}"
        )
        if res.success:
            self.get_logger().info("READY: operator confirmed")
        self._publish()
        return res

    def _srv_reset(self, _req, res: Trigger.Response):
        self.rd.reset()
        self.get_logger().info("UNLOCALIZED: reset")
        self._publish()
        res.success, res.message = True, "reset; give a new initial pose"
        return res


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LocalizationMonitor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        # A callback running while launch tears the context down raises from
        # the C layer ("Unable to convert call argument"); only real if still ok.
        if rclpy.ok():
            raise
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
