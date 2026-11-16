"""DeviceHealth for the owner nodes (unified plan WP-H1): each device's Row read from the
owner's own objects, and the Outbox that publishes them on /amr/device_health.

The decisions are agv_core.health's; this only reads attributes and fills msgs. No rclpy at
import, so the row builders are tested on the dev box. A node that cannot import DeviceHealth
(amr_interfaces not rebuilt yet) still runs: the Outbox decides, and publishes nothing.

Owners: drive_node (drive_rows, bus_row, track_row, gyro_row), panel_node (health.dio),
trolley_node (rear_row), station_bridge (health.station_link).
"""

from __future__ import annotations

from agv_core import health

from amr_base import wire

TOPIC = "/amr/device_health"
DEVICE_IDS = {name: value for value, name in wire.HEALTH_DEVICE_NAMES.items()}
STATE_IDS = {name: value for value, name in wire.HEALTH_STATE_NAMES.items()}


def _age(now: float, t: float | None) -> float | None:
    return None if t is None else now - t


def probing(reader) -> bool:
    """An MLS reader (MlsTrack or MlsImu) with a rediscovery chain running or due."""
    return getattr(reader, "_chain", None) is not None or getattr(reader, "_rediscover_at", None) is not None


def drive_rows(now: float, up_s: float, link, nodes: tuple[int, int], want_link: bool, max_age: float,
               timeout_s: float) -> list[health.Row]:
    """drive_left / drive_right from canopen.DriveLink. nodes: (config.LEFT, config.RIGHT)."""
    from amr_base import canopen  # noqa: PLC0415 - canopen pulls python-can; keep this module light

    up = link.state in (canopen.STANDBY, canopen.ARMED)
    rebooted = set(link.rebooted_nodes()) if up else set()
    rows = []
    for device, nid in zip(("drive_left", "drive_right"), nodes, strict=True):
        t = link.telemetry[nid]
        fb = None
        if t.t_status is not None and t.t_position is not None:
            fb = now - min(t.t_status, t.t_position)
        rows.append(health.drive(
            device, nid, up_s, _age(now, t.t_alive), fb,
            feedback_expected=up,
            linking=want_link and link.state == canopen.DISARMED,
            max_age=max_age, timeout_s=timeout_s, rebooted=nid in rebooted,
        ))
    return rows


def bus_row(now: float, up_s: float, link, tx, timeout_s: float, sdo_timeouts: int = 0) -> health.Row:
    alive = [t.t_alive for t in link.telemetry.values() if t.t_alive is not None]
    return health.can_bus(
        up_s, (now - max(alive)) if alive else None,
        tx.failing_for(now) if tx is not None else 0.0, timeout_s,
        tx_errors=getattr(tx, "errors", 0), error_frames=getattr(link.router, "error_frames", 0),
        sdo_timeouts=sdo_timeouts, last_tx_error=getattr(tx, "last_error", ""),
    )


def track_row(now: float, up_s: float, track) -> health.Row:
    """mls_track from mls_track.MlsTrack. LOST after five stale limits, at least 1 s."""
    if track is None:
        return health.Row("mls_track", health.LOST, "MLS_SILENT", "no track reader (bus thread not up)")
    stale = float(track.stale_after())
    return health.mls_track(
        up_s, track.mode, getattr(track, "want", track.mode), track.age(now), stale, max(1.0, 5.0 * stale),
        probing(track),
        gaps=getattr(track, "stale_periods", 0), rejects=getattr(track, "rejected_frames", 0),
        reconnects=getattr(track, "restarts", 0), timeouts=getattr(track, "misses", 0),
    )


def gyro_row(now: float, up_s: float, imu, enabled: bool, t_sample: float | None) -> health.Row:
    """mls_gyro from mls_imu.MlsImu and the receive time of its last sample (drive_node keeps
    it). Stale after four poll periods (at least 0.1 s), lost after 1 s."""
    if not enabled or imu is None:
        return health.mls_gyro(up_s, enabled and imu is not None, "off", None, 0.1, 1.0, False)
    stale = max(0.1, 4.0 * float(getattr(imu, "poll_period", 0.02)))
    return health.mls_gyro(
        up_s, True, imu.mode, _age(now, t_sample), stale, 1.0, probing(imu),
        rejects=getattr(imu, "rejected", 0), reconnects=getattr(imu, "restarts", 0),
        timeouts=getattr(imu, "misses", 0),
        frozen=bool(getattr(imu, "frozen", False)),
    )


def rear_row(now: float, up_s: float, detect, configured: bool) -> health.Row:
    """rear_scanner from trolley_detect.TrolleyDetect (its detail text and last scan time)."""
    return health.rear_scanner(configured, up_s, detect.detail, _age(now, getattr(detect, "_t", None)),
                               float(detect.p.stale_s))


class Outbox:
    """One per owner node: health.Book plus the DeviceHealth publisher. send(pub, msg) is the
    node's publish (drive_node passes its shutdown-safe one). publish() never raises into the
    caller's loop: a failure is counted in `errors`."""

    def __init__(self, node, send=None) -> None:
        self.book = health.Book()
        self.errors = 0
        self.last_error = ""
        self._node = node
        self._send = send or (lambda pub, msg: pub.publish(msg))
        self._pub = self._msg = None
        try:
            from amr_base.qos import EVENT_STREAM  # noqa: PLC0415 - rclpy; not on the dev box
            from amr_interfaces.msg import DeviceHealth  # noqa: PLC0415
        except ImportError as e:
            node.get_logger().warn(f"no DeviceHealth ({e}): amr_interfaces not rebuilt, no health rows")
            return
        self._msg = DeviceHealth
        self._pub = node.create_publisher(DeviceHealth, TOPIC, EVENT_STREAM)

    def publish(self, now: float, rows) -> list[health.Row]:
        """Offer every row; publish the ones due (edges at once, else 2 Hz). -> the rows sent.
        `rows` may be a callable returning them, so a row builder that raises is counted too."""
        sent = []
        try:
            for row in rows() if callable(rows) else rows:
                out = self.book.offer(now, row)
                if out is None:
                    continue
                sent.append(out)
                if self._pub is not None:
                    m = health.fill(self._msg(), out, DEVICE_IDS, STATE_IDS)
                    m.header.stamp = self._node.get_clock().now().to_msg()
                    self._send(self._pub, m)
        except Exception as e:  # noqa: BLE001 - reporting must never take an owner down
            self.errors += 1
            if str(e) != self.last_error:
                self.last_error = str(e)
                self._node.get_logger().error(f"device health not published: {e!r}")
        return sent
