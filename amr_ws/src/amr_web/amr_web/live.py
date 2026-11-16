"""Live map, pose and scan for the browser (unified plan §6.4). Pure helpers +
a small snapshot store; the ROS subscriptions live in the adapter.

  * The occupancy grid is kept as the latest message plus a snapshot id that
    changes with every new grid; the PNG is encoded lazily, at most once per
    snapshot, by whichever request first asks for it, never inside a callback
    and never under the adapter's state lock.
  * Scan points are transformed at the scan timestamp into `map` (or `odom`
    when there is no map frame), decimated to a bounded count.
  * Everything is tagged with the supervisor generation it was received under
    and dropped on a generation change: new-map scans are never drawn over an
    old-map image.
  * On demand (2026-10-24): /scan (17 Hz) and /tf (~42 Hz) were half of the
    adapter's callbacks, for pages that are open a small part of the time. A
    live-view request marks demand (want()); the adapter subscribes while
    there is demand and drops both LIVE_IDLE_S after the last request. The
    scanner's liveness for the SCANNER_SILENT/STALE alarm then comes from the
    driver's own "/scan topic status" diagnostic (scan_diag_progress()).
  * Display topics (WP-C16, 2026-11-16): a node that already holds /scan and TF can
    publish the projected pose and scan at 5 Hz (DISPLAY_POSE_TOPIC, DISPLAY_SCAN_TOPIC).
    While one does and its samples are fresh, the web takes those and keeps /scan and
    /tf unsubscribed; otherwise it falls back to the raw path above (live_sources()).
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
from agv_core import se2

from amr_web.png import encode_gray

MAX_POINTS = 400
# /scan and /tf are dropped this long after the last live-view request. The
# pages poll at 5 Hz while visible, so only a closed or hidden page lets it lapse.
LIVE_IDLE_S = 5.0
# The sick_safetyscanners2 driver's diagnostic_updater status for its /scan publisher.
SCAN_DIAG_SUFFIX = "/scan topic status"
# WP-C16 display topics: geometry_msgs/PoseStamped and sensor_msgs/PointCloud2 (float32 x, y),
# both already in the world frame (map while a layer localises, else odom), stamped with
# the source time (the transform's / the scan's), at ~5 Hz, at most MAX_POINTS points.
DISPLAY_POSE_TOPIC = "/amr/live_pose_ui"
DISPLAY_SCAN_TOPIC = "/amr/live_scan_ui"
DISPLAY_FRESH_S = 1.0  # a display sample older than this (5 periods): fall back to /scan + /tf
DISPLAY_GRACE_S = 2.0  # just subscribed: wait this long for a first sample before falling back


def live_sources(wanted: bool, display_pubs: int, display_age_s: float | None,
                 display_since_s: float) -> tuple[bool, bool]:
    """(subscribe the display topics, subscribe raw /scan + /tf) for the live view.

    `display_pubs`: publishers of DISPLAY_POSE_TOPIC; `display_age_s`: age of the newest
    display sample (None = none since subscribing); `display_since_s`: how long the display
    topics have been subscribed. A stale display keeps its subscription (cheap at 5 Hz) so
    the view switches back as soon as it resumes; the raw path covers the gap."""
    if not wanted:
        return False, False
    if display_pubs <= 0:
        return False, True
    if display_age_s is None:
        return True, display_since_s >= DISPLAY_GRACE_S
    return True, display_age_s > DISPLAY_FRESH_S


def scan_diag_progress(prev: int | None, values: dict) -> tuple[int | None, bool]:
    """The scanner driver's "/scan topic status" values -> (counter to keep, scans flowed).

    "Events since startup" counts every scan the driver PUBLISHED: any change since the
    last status is evidence of a live scanner (a driver restart resets it, also a change).
    The first status has nothing to compare with, so its "Events in window" decides. A
    dead driver publishes no status at all, which keeps the age growing - the same
    absence the /scan subscription itself would have shown."""
    try:
        n = int(values.get("Events since startup"))
    except (TypeError, ValueError):
        return prev, False
    if prev is None:
        try:
            return n, int(values.get("Events in window", 0)) > 0
        except (TypeError, ValueError):
            return n, False
    return n, n != prev


def grid_to_gray(data: list[int] | np.ndarray, width: int, height: int) -> np.ndarray:
    """OccupancyGrid data (-1 unknown, 0 free .. 100 occupied) -> uint8 image,
    row 0 at the TOP (the bundle PNG convention): 254 free, 205 unknown, 0 occupied."""
    a = np.asarray(data, dtype=np.int16).reshape(height, width)
    img = np.full(a.shape, 205, dtype=np.uint8)
    img[a == 0] = 254
    img[a > 50] = 0
    img[(a > 0) & (a <= 50)] = 254 - (a[(a > 0) & (a <= 50)] * 2).astype(np.uint8)
    return np.flipud(img)


yaw_of = se2.yaw_of


def scan_points(ranges, angle_min: float, angle_inc: float, range_min: float, range_max: float, tx, ty, tyaw):
    """Valid beams as (x, y) in the target frame given the laser pose (tx, ty, tyaw)."""
    n = len(ranges)
    if n == 0:
        return []
    step = max(1, -(-n // MAX_POINTS))  # ceil: at most MAX_POINTS (1152 beams -> 384, not 576)
    c, s = math.cos(tyaw), math.sin(tyaw)
    out = []
    for i in range(0, n, step):
        r = ranges[i]
        if not (range_min <= r <= range_max) or not math.isfinite(r):
            continue
        a = angle_min + i * angle_inc
        lx, ly = r * math.cos(a), r * math.sin(a)
        out.append((round(tx + c * lx - s * ly, 3), round(ty + s * lx + c * ly, 3)))
    return out


_CLOUD_FLOAT32 = 7  # sensor_msgs/PointField FLOAT32


def cloud_xy(fields, point_step: int, data, is_bigendian: bool = False, limit: int = MAX_POINTS):
    """(x, y) of a PointCloud2's float32 x and y fields, rounded to mm, at most `limit`
    (evenly decimated), non-finite points dropped. [] when the layout has no float32 x/y.
    `fields`: (name, offset, datatype) triples."""
    off = {name: o for name, o, dt in fields if dt == _CLOUD_FLOAT32}
    if "x" not in off or "y" not in off or point_step <= 0:
        return []
    buf = bytes(data)
    n = len(buf) // point_step
    if n == 0:
        return []
    f4 = ">f4" if is_bigendian else "<f4"
    dt = np.dtype({"names": ["x", "y"], "formats": [f4, f4], "offsets": [off["x"], off["y"]],
                   "itemsize": point_step})
    a = np.frombuffer(buf, dtype=dt, count=n)[:: max(1, -(-n // limit))]
    ok = np.isfinite(a["x"]) & np.isfinite(a["y"])
    return [(round(float(x), 3), round(float(y), 3)) for x, y in zip(a["x"][ok], a["y"][ok], strict=True)]


class LiveStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.generation = 0
        self.grid = None  # latest OccupancyGrid
        self.grid_t = 0.0
        self.snapshot = 0
        self._png: tuple[int, bytes] | None = None
        self.pose = None  # (x, y, yaw, frame)
        self.pose_t = 0.0
        self.scan = None  # list of (x, y)
        self.scan_frame = ""
        self.scan_t = 0.0
        # live-view demand: monotonic time of the last request, and the adapter's hook
        # (runs in the requesting thread; it must only wake the executor, never block)
        self.want_t: float | None = None
        self.on_want = None

    def want(self, now: float | None = None) -> None:
        """A page polled the live view: keep /scan and /tf subscribed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            lapsed = self.want_t is None or now - self.want_t >= LIVE_IDLE_S
            self.want_t = now
        if lapsed and self.on_want is not None:
            try:
                self.on_want()
            except Exception:  # noqa: BLE001 - never fail the request
                # The reconcile timer is stopped while nothing is subscribed (WP-C12), so this
                # wake-up is the only way in: forget the demand and the next request retries it.
                with self._lock:
                    self.want_t = None

    def wanted(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return self.want_t is not None and now - self.want_t < LIVE_IDLE_S

    def clear_live(self) -> None:
        """The subscriptions were dropped: never serve their last sample as current."""
        with self._lock:
            self.pose = self.scan = None

    def set_generation(self, gen: int) -> None:
        with self._lock:
            if gen != self.generation:
                self.generation = gen
                self.grid = None
                self._png = None
                self.pose = self.scan = None
                self.snapshot += 1

    def on_grid(self, msg) -> None:
        with self._lock:
            self.grid = msg
            self.grid_t = time.monotonic()
            self.snapshot += 1

    def set_pose(self, x: float, y: float, yaw: float, frame: str, source_age_s: float = 0.0) -> None:
        """`source_age_s`: how old the transform this pose came from already was when read
        (review Q12). Re-reading a frozen cached transform must not make it look fresh, so
        the stored time is the SOURCE time, and age_s grows from it."""
        with self._lock:
            self.pose = (x, y, yaw, frame)
            self.pose_t = time.monotonic() - max(0.0, float(source_age_s))

    def set_scan(self, pts, frame: str, source_age_s: float = 0.0) -> None:
        with self._lock:
            self.scan, self.scan_frame = pts, frame
            self.scan_t = time.monotonic() - max(0.0, float(source_age_s))

    def map_meta(self) -> dict | None:
        with self._lock:
            g = self.grid
            if g is None:
                return None
            o = g.info.origin
            return {
                "snapshot": self.snapshot,
                "generation": self.generation,
                "width": int(g.info.width),
                "height": int(g.info.height),
                "resolution": float(g.info.resolution),
                "origin": [float(o.position.x), float(o.position.y), yaw_of(o.orientation)],
                "frame_id": g.header.frame_id,
                "age_s": time.monotonic() - self.grid_t,
            }

    def map_png(self, snapshot: int) -> bytes | None:
        """Encode outside the lock, once per snapshot."""
        with self._lock:
            if self.grid is None or snapshot != self.snapshot:
                return None
            if self._png and self._png[0] == snapshot:
                return self._png[1]
            g, snap = self.grid, self.snapshot
        png = encode_gray(grid_to_gray(g.data, g.info.width, g.info.height))
        with self._lock:
            if self.snapshot == snap:
                self._png = (snap, png)
        return png

    def pose_scan(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "generation": self.generation,
                "pose": None
                if self.pose is None
                else {
                    "x": self.pose[0],
                    "y": self.pose[1],
                    "yaw": self.pose[2],
                    "frame": self.pose[3],
                    "age_s": now - self.pose_t,
                },
                "scan": None
                if self.scan is None
                else {"points": self.scan, "frame": self.scan_frame, "age_s": now - self.scan_t},
            }
