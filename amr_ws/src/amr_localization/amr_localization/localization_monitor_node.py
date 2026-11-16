"""localization_monitor_node: readiness over AMCL (spec §4.3).

Feeds amr_localization.readiness with /amcl_pose covariance, map->odom samples
(10 Hz from TF), /initialpose sightings and sensor/TF ages, and publishes
/amr/localization_state (latched, on change and at 2 Hz). Services:

  /amr/localization/confirm  Trigger  operator: scans align with fixed structure -> READY
  /amr/localization/reset    Trigger  back to UNLOCALIZED

While CHECKING it calls AMCL's /request_nomotion_update every nomotion_period_s, so a
parked vehicle converges on its scan without being nudged (AMCL otherwise only updates
after update_min_d / update_min_a of motion). Confirmation stays with the operator.

/initialpose is only observed here; AMCL subscribes to it itself. The
executor (T7) faults if one arrives during a segment.

CPU (2026-11-16, cpu-load plan §4a a, b, e; unified plan WP-C1, C2):
  * /scan, /imu/data, /wheel_states and /drives/status are only aged. They are drained
    at the 10 Hz tick with take_message, aged by their source_timestamp (stream_age),
    and never wake the executor. The limits are unchanged.
  * /scan_gated arrives raw and is deserialised only for the one scan per
    match_period the map comparison uses (and for the live view, below).
  * The TF listener runs on its own lean node and thread (tf_thread); no parameter
    services on either node.
Live view (WP-C16): /amr/live_pose_ui and /amr/live_scan_ui at 5 Hz, every second tick,
only while a page subscribes (amr_maps.live_display).
"""

from __future__ import annotations

import hashlib
import math
import time

import numpy as np
import rclpy
from agv_core import alarms, se2
from amr_maps.live_display import LiveDisplay
from amr_maps.raycast import ScanGeometry
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.callback_groups import CallbackGroup
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import Imu, LaserScan
from std_srvs.srv import Empty, Trigger
from tf2_ros import Buffer

from amr_base import drive_state, tfpose
from amr_base.lean_node import LeanNode, run
from amr_base.qos import LATCHED, RELIABLE_1, SENSOR_DATA
from amr_interfaces.msg import DriveStatus, Event, LocalizationState, WheelStates
from amr_localization import readiness as rd
from amr_localization import scan_consistency as consistency
from amr_localization import stream_age, tf_thread
from amr_maps import grid as gridio


class PolledGroup(CallbackGroup):
    """A callback group the executor never runs: Humble's executor leaves an entity whose
    group cannot execute out of its wait set, so these subscriptions cost no wakeup.
    Their queues are read with take_message (_taker) instead."""

    def can_execute(self, entity) -> bool:
        return False

    def beginning_execution(self, entity) -> bool:
        return False

    def ending_execution(self, entity) -> None:
        pass


def _taker(sub):
    """take() -> (msg, info) or None, for stream_age.drain. Raw subscriptions give bytes."""

    def take():
        with sub.handle:
            return sub.handle.take_message(sub.msg_type, sub.raw)

    return take


class LocalizationMonitor(LeanNode):
    def __init__(self) -> None:
        super().__init__("localization_monitor", start_parameter_services=False)
        lim = rd.Limits()  # the defaults live in readiness.Limits, once
        self.declare_parameter("cov_xy_max", lim.cov_xy_max)
        self.declare_parameter("cov_yaw_max", lim.cov_yaw_max)
        self.declare_parameter("cov_hold_s", lim.cov_hold_s)
        self.declare_parameter("jump_dist_m", lim.jump_dist_m)
        self.declare_parameter("jump_angle_deg", math.degrees(lim.jump_angle_rad))
        self.declare_parameter("settle_s", lim.settle_s)
        self.declare_parameter("initial_grace_s", lim.initial_grace_s)
        self.declare_parameter("scan_age_limit_s", lim.age_limits["scan"])
        self.declare_parameter("generation", 0)  # layer generation (unified plan U0)
        self.generation = int(self.get_parameter("generation").value)
        self.declare_parameter("wheels_age_limit_s", lim.age_limits["wheels"])
        self.declare_parameter("imu_age_limit_s", lim.age_limits["imu"])
        self.declare_parameter("tf_age_limit_s", lim.age_limits["tf"])
        self.declare_parameter("min_scan_match", lim.min_scan_match)
        self.declare_parameter("max_scan_long", lim.max_scan_long)
        self.declare_parameter("match_hold_s", lim.match_hold_s)
        self.declare_parameter("match_tolerance_m", 0.15)
        self.declare_parameter("match_period_s", 0.5)
        self.declare_parameter("match_age_max_s", lim.match_age_max_s)  # confirmation needs one this recent
        self.declare_parameter(
            "match_max_range_m", 10.0
        )  # beyond this a 0.3 deg yaw error exceeds the tolerance
        # the active revision's dynamic.yaml (navigation_layer passes it; "" = none): beams into
        # dynamic areas are left out of the scan comparison (dynamic-mapping plan §1.2)
        self.declare_parameter("dynamic_yaml", "")
        # safety stop (auto-resume plan): wheel feedback is excused while a /drives/status no
        # older than this says both drives have their torque off
        self.declare_parameter("drives_age_limit_s", 0.5)
        self.declare_parameter("nomotion_period_s", 0.5)  # 0 = never ask AMCL for an in-place update
        p = self.get_parameter
        self._drives_age = float(p("drives_age_limit_s").value)
        self._torque_off_t: float | None = None  # when /drives/status last said torque off
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
                match_age_max_s=p("match_age_max_s").value,
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
        self._map_key: tuple | None = None  # identity of the loaded map (geometry + content hash)
        self._last_match_t = 0.0
        self._dynamic_grid: gridio.Grid | None = None
        self._dynamic: np.ndarray | None = None  # aligned with self._grid, else None
        path = str(p("dynamic_yaml").value or "")
        if path:
            try:
                self._dynamic_grid = gridio.read(path)
            except (gridio.GridError, OSError) as e:
                self.get_logger().error(f"dynamic mask {path} unreadable, not used: {e}")

        self.tf_buffer = Buffer()
        self._tf_node, _ = tf_thread.start(self.tf_buffer, "localization_monitor_tf")
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl, 10)
        self.create_subscription(PoseWithCovarianceStamped, "/initialpose", self._on_initialpose, RELIABLE_1)
        # the map comparison runs on the gated scan: its odom transform already exists, so the
        # lookup below never has to wait (a 50 ms wait on every raw scan starved this node's
        # executor and made its OWN view of TF stale, 2026-09-17)
        self.create_subscription(LaserScan, "/scan_gated", self._on_scan_gated, SENSOR_DATA, raw=True)
        self._gated_raw: bytes | None = None  # the newest gated scan, still serialized
        self._gated: tuple[bytes, LaserScan] | None = None  # (raw, its decoded message), once each
        self.create_subscription(OccupancyGrid, "/map", self._on_map, LATCHED)
        # age-only streams: drained by _drain() at the tick, never a wakeup of their own
        polled = PolledGroup()

        def poll(msg_type, topic, qos, raw):
            return _taker(self.create_subscription(msg_type, topic, lambda _m: None, qos,
                                                   callback_group=polled, raw=raw))

        self._take = {
            "scan": poll(LaserScan, "/scan", SENSOR_DATA, True),
            "imu": poll(Imu, "/imu/data", SENSOR_DATA, True),
            "wheels": poll(WheelStates, "/wheel_states", SENSOR_DATA, False),
            "drives": poll(DriveStatus, "/drives/status", 10, False),
        }
        self._drain_t: float | None = None
        self.create_service(Trigger, "/amr/localization/confirm", self._srv_confirm)
        self.create_service(Trigger, "/amr/localization/reset", self._srv_reset)
        self._pub = self.create_publisher(LocalizationState, "/amr/localization_state", LATCHED)
        # Operator events on STATE CHANGES only (the tick runs at 2 Hz and _evaluate
        # is called per sample): UNLOCALIZED -> CHECKING -> READY -> LOST.
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._event_seq = 0
        self._nomotion = self.create_client(Empty, "/request_nomotion_update")
        self._nomotion_period = float(p("nomotion_period_s").value)
        self._nomotion_t = 0.0
        self._nomotion_pending = None
        self._live = LiveDisplay(self, self.tf_buffer)
        self._live_n = 0
        self.create_timer(0.1, self._tick)
        self.create_timer(0.5, self._publish)
        self.get_logger().info("UNLOCALIZED: waiting for /initialpose")

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _seen(self, key: str, t: float | None) -> None:
        if t is not None:
            self._last[key] = max(self._last.get(key, t), t)

    def _drain(self) -> None:
        """Take everything the age-only streams queued since the last drain (stream_age)."""
        t, wall, prev = self._now(), time.time_ns(), self._drain_t
        self._drain_t = t
        got = {k: stream_age.drain(take, t, wall, prev) for k, take in self._take.items()}
        self._seen("scan", stream_age.newest(got["scan"]))
        self._seen("imu", stream_age.newest(got["imu"]))
        # Arrival is not feedback: only a sample both drives vouch for keeps wheels fresh.
        self._seen("wheels", stream_age.newest(got["wheels"], lambda m: m.left_valid and m.right_valid))
        if got["drives"]:
            # the newest report decides, as each one did when they came one callback at a time;
            # a feedback-only loss with the drives still enabled is never excused
            msg, ts = got["drives"][-1]
            off = drive_state.torque_off(msg.operational, msg.left_state, msg.right_state)
            self._torque_off_t = ts if off else None

    def _on_map(self, msg: OccupancyGrid) -> None:
        grid = gridio.from_occupancy_grid_msg(msg)
        m = grid.meta
        key = (grid.width, grid.height, m.resolution, m.origin_x, m.origin_y, m.origin_yaw)
        key += (hashlib.sha256(grid.data.tobytes()).hexdigest(),)
        self._occ_near, self._grid = consistency.occupied_near(grid, self._match_tol), grid
        self._dynamic = None
        if self._dynamic_grid is not None:
            problem = gridio.mask_misalignment(grid, self._dynamic_grid)
            if problem:
                self.get_logger().error(f"dynamic mask not aligned with /map ({problem}): not used")
            else:
                self._dynamic = gridio.occupied(self._dynamic_grid)
        if self._map_key is not None and key != self._map_key:
            # Pose, covariance and scan evidence were all about the previous map.
            self.rd.reset("map changed; give a new initial pose")
            self._publish()
        self._map_key = key
        self.get_logger().info(f"map {grid.width}x{grid.height} loaded for scan consistency")

    def _gated_scan(self) -> LaserScan | None:
        """The newest gated scan, deserialised at most once."""
        raw = self._gated_raw
        if raw is None:
            return None
        if self._gated is None or self._gated[0] is not raw:
            self._gated = (raw, deserialize_message(raw, LaserScan))
        return self._gated[1]

    def _on_scan_gated(self, raw: bytes) -> None:
        self._gated_raw = raw
        t = self._now()
        if self._grid is None or t - self._last_match_t < self._match_period:
            return
        self._last_match_t = t  # one attempt per period, whether or not it succeeds
        msg = self._gated_scan()
        try:
            # At the scan's own stamp: during a turn the latest transform is a few
            # degrees ahead of the scan, which throws every long beam off the map.
            tr = self.tf_buffer.lookup_transform("map", msg.header.frame_id, msg.header.stamp)
        except Exception:  # noqa: BLE001 - not localised yet, or the stamp is not covered
            return  # no comparison: readiness lets the previous result expire
        q = tr.transform.rotation
        yaw = se2.yaw_of(q)
        lx, ly = tr.transform.translation.x, tr.transform.translation.y
        ranges = np.asarray(msg.ranges, dtype=np.float64)
        n = len(ranges)
        max_r = min(msg.range_max, self._match_max_range)
        geom = ScanGeometry(
            msg.angle_min, msg.angle_min + (n - 1) * msg.angle_increment, n, msg.range_min, max_r
        )
        match_frac, long_frac = consistency.compare(
            self._grid, self._occ_near, lx, ly, yaw, ranges, geom, self._match_tol, self._dynamic
        )
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self.rd.on_scan_match(t, match_frac, long_frac, stamp)

    def _request_nomotion(self, t: float) -> None:
        if self._nomotion_period <= 0.0 or not self.rd.wants_nomotion_update():
            return
        if t - self._nomotion_t < self._nomotion_period:
            return
        if self._nomotion_pending is not None and not self._nomotion_pending.done():
            return  # AMCL busy (or inactive): never queue requests behind it
        if not self._nomotion.service_is_ready():
            return
        self._nomotion_t = t
        self._nomotion_pending = self._nomotion.call_async(Empty.Request())

    def _on_amcl(self, msg: PoseWithCovarianceStamped) -> None:
        c = msg.pose.covariance
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9  # its scan's time (Q07)
        self.rd.on_amcl_pose(self._now(), c[0], c[7], c[35], stamp if stamp > 0.0 else None)

    def _on_initialpose(self, _msg: PoseWithCovarianceStamped) -> None:
        self.rd.on_initialpose(self._now())
        self.get_logger().info("initial pose received: CHECKING")
        self._publish()

    def _tick(self) -> None:
        self._drain()
        t = self._now()
        try:
            tr = self.tf_buffer.lookup_transform("map", "odom", rclpy.time.Time())
            q = tr.transform.rotation
            yaw = se2.yaw_of(q)
            stamp = tr.header.stamp.sec + tr.header.stamp.nanosec * 1e-9
            # AMCL stamps map->odom into the future by transform_tolerance; clamp the age at 0.
            self._last["tf"] = max(self._last.get("tf", 0.0), min(stamp, t))
            odom_base = tfpose.lookup_pose(self.tf_buffer, "odom", "base_footprint")
            self.rd.on_map_odom(t, tr.transform.translation.x, tr.transform.translation.y, yaw, odom_base)
        except Exception:  # noqa: BLE001 - no transform yet is a normal state
            pass
        ages = {k: (t - self._last[k]) if k in self._last else None for k in ("scan", "wheels", "imu", "tf")}
        held = self._torque_off_t is not None and t - self._torque_off_t <= self._drives_age
        self.rd.evaluate(t, ages, frozenset({"wheels"}) if held else frozenset())
        self._request_nomotion(t)
        if self.rd.state != self._last_state or self.rd.reason != self._last_reason:
            if self.rd.state != self._last_state:
                self.get_logger().info(f"{rd.NAMES[self.rd.state]}: {self.rd.reason}")
                self._event()
            self._last_state, self._last_reason = self.rd.state, self.rd.reason
            self._publish()
        self._live_n += 1
        if self._live_n % 2 == 0 and self._live.wanted():  # 5 Hz, and only for an open page
            frame = self._live.frame(t)
            self._live.publish_pose(frame)
            self._live.publish_scan(frame, self._gated_scan())

    def _event(self) -> None:
        code = self.rd.code or "MODE_CHANGE"
        text = f"localisation {rd.NAMES[self.rd.state]}: {self.rd.reason}"
        self._pub_event.publish(self.build_event("localization_monitor", alarms.level(code), code, text))

    def _publish(self) -> None:
        self._drain()  # the published ages are as current as the evaluated ones
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
        m.code = self.rd.code
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
    run(LocalizationMonitor, args)


if __name__ == "__main__":
    main()
