"""What the web adapter keeps of device health and the scanners' diagnosis (unified plan WP-H2,
hardening plan H-P1-2). Pure: no rclpy, no msg import, so it is tested on the dev box; adapter.py
only subscribes and calls these.

    row_from_msg(m)              DeviceHealth msg (duck-typed) -> agv_core.health.Row
    view(rows, now, fitted, up)  the consumer's view as plain dicts for /api/state, or None
    statuses(diag)               the /diagnostics statuses alarms.standing() reads
    OverviewPoll                 when to ask the front scanner's status_overview service
    overview_of(resp)            its answer as the dict scanner_health.rows() takes
    supply_limits()              the profile's bus voltage limits for the supply chip (WP-P7)
"""

from __future__ import annotations

from dataclasses import asdict

from agv_core import health

from amr_base import scanner_health, wire

EVENTLOG_STATUS = "eventlog/recorder"  # event_recorder_node's /diagnostics status


def row_from_msg(m) -> health.Row | None:
    """A DeviceHealth message as a Row; None for a device this build does not know."""
    device = wire.HEALTH_DEVICE_NAMES.get(int(m.device))
    if device is None:
        return None
    return health.Row(
        device, wire.HEALTH_STATE_NAMES.get(int(m.state), health.LOST), str(m.code), str(m.detail),
        age_s=float(m.age_s), since_s=float(m.since_s), gaps=int(m.gaps), rejects=int(m.rejects),
        reconnects=int(m.reconnects), timeouts=int(m.timeouts),
    )


def view(rows: dict, now: float, fitted: dict, up_s: float) -> dict | None:
    """health.view() as {device: Row fields}. None while no DeviceHealth has arrived at all since
    the web started (amr_interfaces not rebuilt, or a sim whose fake base publishes none): then
    nothing is accused. Once one owner has reported, a silent fitted owner is LOST as view() says."""
    if not rows:
        return None
    return {d: asdict(r) for d, r in health.view(rows, now, fitted, up_s).items()}


def statuses(diag: dict) -> dict:
    """The scanner drivers' statuses and the event recorder's, from adapter.diagnostics()."""
    return {k: v for k, v in diag.items()
            if k == EVENTLOG_STATUS or scanner_health.scanner_of(k) is not None}


def overview_of(resp) -> dict:
    """The StatusOverview fields scanner_health.rows() reads (duck-typed response)."""
    return {"config_state": int(getattr(resp, "config_state", -1)),
            "error_info_code": int(getattr(resp, "error_info_code", 0))}


class OverviewPoll:
    """The status_overview read is a CoLa2 request to the scanner: asked when the front State
    status first appears (the driver came up) and on each change of its level, never per tick.
    A service that is not there yet is asked again every retry_s until it answers once."""

    def __init__(self, retry_s: float = 30.0) -> None:
        self.retry_s = float(retry_s)
        self._level: int | None = None
        self._due = False
        self._tried: float | None = None

    def level(self, level: int) -> None:
        """The front State status's level, at every /diagnostics message."""
        if level != self._level:
            self._level, self._due, self._tried = level, True, None

    def want(self, now: float) -> bool:
        """Call now? The caller then reports answered() or leaves it due."""
        if not self._due or (self._tried is not None and now - self._tried < self.retry_s):
            return False
        self._tried = now
        return True

    def answered(self) -> None:
        self._due = False


def supply_limits(thresholds=None) -> dict:
    """The profile's bus voltage limits (monitor.bus_v_*, config.MONITOR_THRESHOLDS["bus_v"]) for
    the supply chip's colour: {"warn_low", "trip_low", "warn_high"}, or {} on a dev box without a
    profile (an uncoloured chip)."""
    try:
        if thresholds is None:
            from agv_core import config  # noqa: PLC0415 - needs AGV_PROFILE, absent on a dev box

            thresholds = config.MONITOR_THRESHOLDS
        bus = thresholds["bus_v"]
        return {"warn_low": float(bus["warn_low"]), "trip_low": float(bus["trip_low"]),
                "warn_high": float(bus["warn"])}
    except Exception:  # noqa: BLE001 - display only
        return {}
