"""The web live view's 5 Hz display topics (unified plan WP-C16, cpu-load plan C#28).

A node that already holds the scan and TF (localization_monitor in NAV and in LINE's
tape_loc group, mapping_session in MAPPING) publishes the projected pose and scan, so
amr_web can leave raw /scan (17-34 Hz) and /tf (~42 Hz) unsubscribed. The consumer is
amr_web/live.py (live_sources(), cloud_xy()); the topic names and layout here are its
contract:

  /amr/live_pose_ui   geometry_msgs/PoseStamped: base_footprint in the world frame,
                      stamped with the transform's time
  /amr/live_scan_ui   sensor_msgs/PointCloud2 in the same frame, stamped with the scan's
                      time: float32 x, y, z at offsets 0, 4, 8, point_step 12, little
                      endian, at most MAX_POINTS points

The world frame is `map` while map->odom is fresh (MAP_FRESH_S, as amr_web's
MAP_ODOM_FRESH_S) and map->base_footprint resolves, else `odom`. Published only while
someone subscribes (get_subscription_count() > 0), at PERIOD_S.

The functions are pure (numpy only). LiveDisplay is the thin ROS part; it imports the
message types when a node builds it, so amr_maps itself still needs no rclpy.
"""

from __future__ import annotations

import array
import math

import numpy as np

POSE_TOPIC = "/amr/live_pose_ui"
SCAN_TOPIC = "/amr/live_scan_ui"
PERIOD_S = 0.2  # 5 Hz
MAX_POINTS = 400
MAP_FRESH_S = 2.0
FLOAT32 = 7  # sensor_msgs/PointField FLOAT32
FIELDS = (("x", 0, FLOAT32), ("y", 4, FLOAT32), ("z", 8, FLOAT32))
POINT_STEP = 12


def world_frame(map_odom_age_s: float | None, map_base_ok: bool) -> str:
    """'map' while a layer localises (map->odom no older than MAP_FRESH_S; AMCL stamps it
    ahead, so a negative age counts as 0), else 'odom'."""
    if map_odom_age_s is not None and map_odom_age_s <= MAP_FRESH_S and map_base_ok:
        return "map"
    return "odom"


def scan_cloud(ranges, angle_min: float, angle_inc: float, range_min: float, range_max: float,
               tx: float, ty: float, tyaw: float, limit: int = MAX_POINTS) -> tuple[int, bytes]:
    """Valid beams of a scan, every ceil(n / limit)-th one, projected through the laser pose
    (tx, ty, tyaw) in the world frame -> (point count, PointCloud2 data). The beam choice is
    amr_web's live.scan_points; z is 0."""
    r = np.asarray(ranges, dtype=np.float64)
    n = len(r)
    if n == 0:
        return 0, b""
    step = max(1, -(-n // limit))
    idx = np.arange(0, n, step)
    r = r[idx]
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(r) & (r >= range_min) & (r <= range_max)
    idx, r = idx[ok], r[ok]
    a = angle_min + idx * angle_inc
    lx, ly = r * np.cos(a), r * np.sin(a)
    c, s = math.cos(tyaw), math.sin(tyaw)
    pts = np.zeros((len(r), 3), dtype="<f4")
    pts[:, 0] = tx + c * lx - s * ly
    pts[:, 1] = ty + s * lx + c * ly
    return len(r), pts.tobytes()


def stamp_s(stamp) -> float:
    return stamp.sec + stamp.nanosec * 1e-9


def yaw_of(q) -> float:
    """Planar yaw of a quaternion (agv_core.se2.yaw_of; amr_maps stays dependency-free)."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class LiveDisplay:
    """The two publishers and the projection, for a node that has a tf2 Buffer.

    publish_pose()/publish_scan() each publish only while their topic has a subscriber,
    so a node calls them on its own tick and pays nothing while no page is open."""

    def __init__(self, node, tf_buffer, base_frame: str = "base_footprint") -> None:
        from geometry_msgs.msg import PoseStamped  # noqa: PLC0415 - a node's environment
        from rclpy.qos import QoSProfile, ReliabilityPolicy  # noqa: PLC0415
        from sensor_msgs.msg import PointCloud2, PointField  # noqa: PLC0415

        self._PoseStamped, self._PointCloud2, self._PointField = PoseStamped, PointCloud2, PointField
        self.node, self.tf, self.base = node, tf_buffer, base_frame
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)  # amr_web's subscriber
        self.pose_pub = node.create_publisher(PoseStamped, POSE_TOPIC, qos)
        self.scan_pub = node.create_publisher(PointCloud2, SCAN_TOPIC, qos)
        self._last_scan = None  # the scan last published: never the same one twice

    def wanted(self) -> bool:
        return self.pose_pub.get_subscription_count() > 0 or self.scan_pub.get_subscription_count() > 0

    def frame(self, now_s: float) -> str:
        """The world frame by world_frame(), from this node's buffer."""
        from rclpy.time import Time  # noqa: PLC0415

        try:
            t = self.tf.lookup_transform("map", "odom", Time())
            age = now_s - stamp_s(t.header.stamp)
            ok = self.tf.can_transform("map", self.base, Time())
        except Exception:  # noqa: BLE001 - no map frame: odom
            return "odom"
        return world_frame(age, ok)

    def publish_pose(self, frame: str) -> None:
        if self.pose_pub.get_subscription_count() <= 0:
            return
        from rclpy.time import Time  # noqa: PLC0415

        try:
            t = self.tf.lookup_transform(frame, self.base, Time())
        except Exception:  # noqa: BLE001 - nothing to show yet
            return
        m = self._PoseStamped()
        m.header.frame_id, m.header.stamp = frame, t.header.stamp  # the transform's time
        tr = t.transform
        m.pose.position.x, m.pose.position.y, m.pose.position.z = tr.translation.x, tr.translation.y, 0.0
        m.pose.orientation = tr.rotation
        self.pose_pub.publish(m)

    def publish_scan(self, frame: str, scan) -> None:
        """`scan`: a LaserScan (or None). Looked up at its own stamp when the buffer has it,
        else the latest transform (the EKF lands 20-40 ms after a raw scan)."""
        if scan is None or scan is self._last_scan or self.scan_pub.get_subscription_count() <= 0:
            return
        from rclpy.time import Time  # noqa: PLC0415

        try:
            try:
                t = self.tf.lookup_transform(frame, scan.header.frame_id, scan.header.stamp)
            except Exception:  # noqa: BLE001 - not there yet
                t = self.tf.lookup_transform(frame, scan.header.frame_id, Time())
        except Exception:  # noqa: BLE001
            return
        tr = t.transform
        n, data = scan_cloud(scan.ranges, scan.angle_min, scan.angle_increment, scan.range_min,
                             scan.range_max, tr.translation.x, tr.translation.y, yaw_of(tr.rotation))
        m = self._PointCloud2()
        m.header.frame_id, m.header.stamp = frame, scan.header.stamp  # the scan's time
        m.height, m.width = 1, n
        m.fields = [self._PointField(name=nm, offset=o, datatype=dt, count=1) for nm, o, dt in FIELDS]
        m.is_bigendian, m.point_step, m.row_step, m.is_dense = False, POINT_STEP, POINT_STEP * n, True
        m.data = array.array("B", data)  # the message's fast path for uint8[]
        self.scan_pub.publish(m)
        self._last_scan = scan
