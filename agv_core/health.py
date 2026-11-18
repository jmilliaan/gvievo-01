"""Device health: one model for the link to every device (unified plan WP-H1; hardening plan
H-P1-1 and section 3).

Pure and clock-fed, like gating.py: no ROS, no Flask. Reporting and correlation ONLY. Nothing
here grants or removes motion; enforcement stays where it is (the gate, drive_node, the job,
the executor). A wrong state here mislabels the HMI, it never moves the vehicle.

    rows: what one device is doing   drive(), can_bus(), mls_track(), mls_gyro(), dio(),
                                     rear_scanner(), station_link()   -> Row
    Book: the owner node's outbox    Book.offer(now, row) -> Row to publish, or None
                                     (every edge at once, otherwise at 2 Hz)
    view(): what a consumer shows    owner silence -> LOST, unconfigured -> ABSENT
    classify(): the correlator       drives x2 + MLS -> CAN_BUS_LOST, MLS track + gyro ->
                                     MLS_OFFLINE, DIO -> IO_ISLAND_LOST

Devices and states are NAMES here; the DeviceHealth.msg ints are in amr_base/wire.py
(HEALTH_DEVICE_NAMES, HEALTH_STATE_NAMES, same order as DEVICES and STATES, pinned by
test_wire_contract). APPEND ONLY, like the msg.

Existence comes from the profile (configured()): a device the profile does not fit is
ABSENT, never LOST (2026-11-16: rear.source "none", station.enabled false). A fitted device
not seen yet is ABSENT for BOOT_GRACE_S after its owner started, then LOST.

No RFID device and no BMS (decisions 23 and 16). IO_ISLAND_LOST is the DIO alone: the RFID
reader that shared the cable is not used any more. station_link is not in any group: it runs
over Wi-Fi, not the shared cable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# APPEND ONLY: the index is the DeviceHealth.device value (amr_base/wire.py).
DEVICES = (
    "drive_left",
    "drive_right",
    "can_bus",
    "mls_track",
    "mls_gyro",
    "dio",
    "rear_scanner",
    "station_link",
)
# APPEND ONLY: the index is the DeviceHealth.state value.
STATES = ("ABSENT", "OK", "DEGRADED", "STALE", "FROZEN", "LOST", "RECONNECTING")
ABSENT, OK, DEGRADED, STALE, FROZEN, LOST, RECONNECTING = STATES

# Worst first, for a consumer that shows one line per device.
RANK = {LOST: 0, FROZEN: 1, STALE: 2, RECONNECTING: 3, DEGRADED: 4, OK: 5, ABSENT: 6}
# Down for the correlator: the data is not arriving (FROZEN arrives, it is just wrong).
DOWN = (LOST, STALE, RECONNECTING)

# Who publishes each device's row; a consumer names it when the rows stop.
OWNER = {
    "drive_left": "drive_node",
    "drive_right": "drive_node",
    "can_bus": "drive_node",
    "mls_track": "drive_node",
    "mls_gyro": "drive_node",
    "dio": "panel_node",
    "rear_scanner": "trolley_node",
    "station_link": "station_bridge",
}
# The catalogue code a consumer uses when the owner itself went quiet.
LOST_CODE = {
    "drive_left": "DRIVE_SILENT",
    "drive_right": "DRIVE_SILENT",
    "can_bus": "CAN_BUS_LOST",
    "mls_track": "MLS_SILENT",
    "mls_gyro": "IMU_STALE",
    "dio": "IO_ISLAND_LOST",
    "rear_scanner": "REAR_SCANNER_SILENT",
    "station_link": "STATION_LINK_DOWN",
}

PERIOD_S = 0.5  # 2 Hz repeat per device; edges go at once
BOOT_GRACE_S = 5.0  # a fitted device not seen yet is ABSENT this long after its owner started
OWNER_TIMEOUT_S = 2.0  # a consumer: a row older than this means the owner stopped reporting
WINDOW_S = 1.0  # the correlator: losses this close together share a cause
# A negative age down to -RACE_S is two threads racing on one monotonic clock: the owner's bus
# loop (or the consumer's state build) took `now`, then a frame or a message arrived with a newer
# stamp before the age was taken. That data is the freshest there is, so it reads as age 0.
# Beyond it a stamp from the future stays not fresh (rule 1). Seen on agv-01 2026-11-17: MLS,
# drives and the CAN bus flapped LOST at 1 Hz on ages of -0.01 s. Reporting only: the motion
# path keeps its strict 0 <= age (gating._fresh).
RACE_S = 0.25


@dataclass(frozen=True)
class Row:
    """One device's health, as DeviceHealth.msg carries it."""

    device: str
    state: str
    code: str = ""  # catalogue key (agv_core/alarms.py); "" while OK or ABSENT
    detail: str = ""
    age_s: float = -1.0  # age of the device's newest data; -1 = none / not applicable
    since_s: float = 0.0  # how long in this state (filled by Book)
    gaps: int = 0
    rejects: int = 0
    reconnects: int = 0
    timeouts: int = 0


def _age(age: float | None) -> float:
    return -1.0 if age is None else float(age)


def _race(age: float | None) -> float | None:
    """`age`, with a race-sized negative (see RACE_S) read as 0.0. None stays None."""
    return 0.0 if age is not None and -RACE_S <= age < 0.0 else age


def _unseen(device: str, up_s: float, what: str, code: str) -> Row:
    """A fitted device with no data yet: ABSENT inside the boot grace, LOST after it."""
    if up_s < BOOT_GRACE_S:
        return Row(device, ABSENT, "", f"{what}: not seen yet")
    return Row(device, LOST, code, f"{what}: never seen since start")


def by_age(age: float | None, stale_after: float, lost_after: float) -> str:
    """OK / STALE / LOST from a data age (rule 1: a negative age beyond RACE_S is not fresh).
    None = LOST."""
    age = _race(age)
    if age is None or age < 0.0 or age > lost_after:
        return LOST
    return STALE if age > stale_after else OK


# ---------------------------------------------------------------- the devices (owner side)


def drive(
    device: str,
    node: int,
    up_s: float,
    alive_age: float | None,
    feedback_age: float | None,
    feedback_expected: bool,
    linking: bool,
    max_age: float,
    timeout_s: float,
    rebooted: bool = False,
) -> Row:
    """One BLV-R drive. alive_age: any frame or SDO reply (DriveTelemetry.t_alive);
    feedback_age: the older of TPDO1 and TPDO2; expected once the link is up (STANDBY and on).
    linking: the link is wanted but not up yet (prepare retrying)."""
    alive_age, feedback_age = _race(alive_age), _race(feedback_age)
    what = f"drive node {node}"
    if alive_age is None:
        return _unseen(device, up_s, what, "DRIVE_SILENT")
    if alive_age < 0.0 or alive_age > timeout_s:
        return Row(device, LOST, "DRIVE_SILENT", f"{what}: no frame for {alive_age:.1f} s",
                   age_s=_age(alive_age))
    if rebooted:
        return Row(device, RECONNECTING, "DRIVE_REBOOTED", f"{what}: boot-up frame, relinking",
                   age_s=_age(alive_age))
    if feedback_expected:
        state = by_age(feedback_age, max_age, timeout_s)
        if state != OK:
            why = "no TPDO yet" if feedback_age is None else f"TPDO {feedback_age:.2f} s old"
            return Row(device, state, "DRIVE_SILENT", f"{what}: {why}, heartbeat alive",
                       age_s=_age(feedback_age))
        return Row(device, OK, "", "", age_s=_age(feedback_age))
    if linking:
        return Row(device, RECONNECTING, "", f"{what}: answering, linking", age_s=_age(alive_age))
    return Row(device, OK, "", f"{what}: link off", age_s=_age(alive_age))


def can_bus(
    up_s: float,
    newest_alive_age: float | None,
    tx_failing_for: float,
    timeout_s: float,
    tx_errors: int = 0,
    error_frames: int = 0,
    sdo_timeouts: int = 0,
    last_tx_error: str = "",
) -> Row:
    """The bus itself: TX health (canopen.TxHealth) and whether ANY node is heard."""
    n = dict(rejects=int(error_frames), timeouts=int(sdo_timeouts), gaps=int(tx_errors))
    if tx_failing_for > timeout_s:
        return Row("can_bus", LOST, "CAN_TX_FAILED",
                   f"CAN TX failing for {tx_failing_for:.1f} s ({last_tx_error})", **n)
    newest_alive_age = _race(newest_alive_age)
    if newest_alive_age is None:
        r = _unseen("can_bus", up_s, "CAN bus", "CAN_BUS_LOST")
        return replace(r, **n)
    if newest_alive_age < 0.0 or newest_alive_age > timeout_s:
        return Row("can_bus", LOST, "CAN_BUS_LOST", f"no frame from any node for {newest_alive_age:.1f} s",
                   age_s=_age(newest_alive_age), **n)
    if tx_failing_for > 0.0:
        return Row("can_bus", DEGRADED, "CAN_TX_FAILED", f"CAN TX failing ({last_tx_error})",
                   age_s=_age(newest_alive_age), **n)
    return Row("can_bus", OK, "", "", age_s=_age(newest_alive_age), **n)


def mls_track(
    up_s: float,
    mode: str,
    want: str,
    age: float | None,
    stale_after: float,
    lost_after: float,
    probing: bool,
    gaps: int = 0,
    rejects: int = 0,
    reconnects: int = 0,
    timeouts: int = 0,
) -> Row:
    """The MLS line track (mls_track.MlsTrack). mode is what it reads now (tpdo | sdo | off),
    want what it was asked for (tpdo | sdo | auto | off). SDO while a stream was wanted is
    MLS_NO_STREAM (it answers, it does not stream); no samples at all is MLS_SILENT."""
    age = _race(age)
    n = dict(gaps=int(gaps), rejects=int(rejects), reconnects=int(reconnects), timeouts=int(timeouts))
    if want == "off":
        return Row("mls_track", ABSENT, "", "track reading off (mls_track_mode)", **n)
    if mode == "off":
        if probing:
            return Row("mls_track", RECONNECTING, "MLS_SILENT", "not answering, probing",
                       age_s=_age(age), **n)
        if age is None and up_s < BOOT_GRACE_S:
            return Row("mls_track", ABSENT, "", "MLS: not seen yet", **n)
        return Row("mls_track", LOST, "MLS_SILENT", "not answering", age_s=_age(age), **n)
    if age is None:
        return replace(_unseen("mls_track", up_s, "MLS", "MLS_SILENT"), **n)
    state = by_age(age, stale_after, lost_after)
    if state != OK:
        return Row("mls_track", state, "MLS_SILENT", f"last sample {age:.2f} s old ({mode})", age_s=age, **n)
    if mode == "sdo" and want in ("tpdo", "auto"):
        return Row("mls_track", DEGRADED, "MLS_NO_STREAM", "answers SDO, no TPDO stream: polling",
                   age_s=age, **n)
    return Row("mls_track", OK, "", mode, age_s=age, **n)


def mls_gyro(
    up_s: float,
    enabled: bool,
    mode: str,
    age: float | None,
    stale_after: float,
    lost_after: float,
    probing: bool,
    rejects: int = 0,
    reconnects: int = 0,
    timeouts: int = 0,
    frozen: bool = False,
) -> Row:
    """The MLS yaw rate (mls_imu.MlsImu). SDO polling is how a sensor without the gyro TPDO
    is read: a configuration, not a degradation.

    `frozen` is MlsImu.frozen (its StampTracker latched a duplicate sensor stamp, H-P1-7): the
    sensor answers but its clock stopped, and its samples are withheld. FROZEN, not STALE, so
    the row says why; not answering at all still wins (2026-11-16)."""
    age = _race(age)
    n = dict(rejects=int(rejects), reconnects=int(reconnects), timeouts=int(timeouts))
    if not enabled:
        return Row("mls_gyro", ABSENT, "", "imu.enabled false", **n)
    if mode == "off":
        if probing:
            return Row("mls_gyro", RECONNECTING, "IMU_STALE", "not answering, probing", age_s=_age(age), **n)
        if age is None and up_s < BOOT_GRACE_S:
            return Row("mls_gyro", ABSENT, "", "MLS gyro: not seen yet", **n)
        return Row("mls_gyro", LOST, "IMU_STALE", "gyro not answering", age_s=_age(age), **n)
    if frozen:
        return Row("mls_gyro", FROZEN, "IMU_STALE", f"sensor stamp frozen ({mode}): samples withheld",
                   age_s=_age(age), **n)
    if age is None:
        return replace(_unseen("mls_gyro", up_s, "MLS gyro", "IMU_STALE"), **n)
    state = by_age(age, stale_after, lost_after)
    if state != OK:
        return Row("mls_gyro", state, "IMU_STALE", f"last yaw rate {age:.2f} s old ({mode})", age_s=age, **n)
    return Row("mls_gyro", OK, "", mode, age_s=age, **n)


def dio(up_s: float, snap: dict, source_max_age_s: float) -> Row:
    """The DIO island, from DioLink.snapshot(). A scan saved by the retry (dio._scan_with_retry)
    or a drop in the last 10 minutes is DEGRADED: a connector going bad shows before it
    costs a run."""
    n = dict(gaps=int(snap.get("retried", 0)), timeouts=int(snap.get("errors", 0)),
             reconnects=int(snap.get("drops_10min", 0)))
    if not snap.get("enabled", True):
        return Row("dio", ABSENT, "", "dio.enabled false", **n)
    age = _race(snap.get("rx_age_s"))
    detail = str(snap.get("detail", ""))
    if age is None:
        r = _unseen("dio", up_s, "DIO", "IO_ISLAND_LOST")
        return replace(r, detail=f"{r.detail} ({detail})" if detail else r.detail, **n)
    if not snap.get("comms_ok") or not snap.get("connected", True):
        return Row("dio", LOST, "IO_ISLAND_LOST", f"no scan for {age:.1f} s: {detail}", age_s=age, **n)
    if age < 0.0 or age > source_max_age_s:
        return Row("dio", STALE, "IO_ISLAND_LOST", f"last scan {age:.2f} s old", age_s=age, **n)
    retries, drops = int(snap.get("retries_10min", 0)), int(snap.get("drops_10min", 0))
    if retries or drops:
        last = snap.get("last_retry") or ""
        why = f"{retries} scan(s) retried, {drops} drop(s) in 10 min" + (f"; last: {last}" if last else "")
        return Row("dio", DEGRADED, "DIO_SCAN_RETRIED", why, age_s=age, **n)
    return Row("dio", OK, "", "", age_s=age, **n)


# trolley_detect.TrolleyDetect.detail: a repeated scan (the content counter did not move).
_REAR_FROZEN = ("the scan content is frozen",)
# Its texts that mean "no usable scan yet" while scans DO arrive (the debounce is running).
_REAR_WAITING = ("no scan yet", "no scan", "the rear scan is stale")


def rear_scanner(configured: bool, up_s: float, detail: str, age: float | None, stale_after: float,
                 rejects: int = 0) -> Row:
    """The rear nanoScan3 as trolley_node sees /rear/scan: TrolleyDetect's detail and the age of
    its last accepted scan. Scans that arrive but are malformed or mostly invalid: DEGRADED."""
    if not configured:
        return Row("rear_scanner", ABSENT, "", "rear.source none")
    n = dict(rejects=int(rejects))
    if detail in _REAR_FROZEN:
        return Row("rear_scanner", FROZEN, "REAR_SCANNER_SILENT", detail, age_s=_age(age), **n)
    age = _race(age)
    if age is None:
        return replace(_unseen("rear_scanner", up_s, "rear scanner", "REAR_SCANNER_SILENT"), **n)
    if age < 0.0 or age > stale_after:
        return Row("rear_scanner", LOST, "REAR_SCANNER_SILENT", f"no scan for {age:.1f} s", age_s=age, **n)
    if detail and detail not in _REAR_WAITING:
        return Row("rear_scanner", DEGRADED, "REAR_SCANNER_SILENT", detail, age_s=age, **n)
    return Row("rear_scanner", OK, "", "", age_s=age, **n)


def station_link(
    configured: bool,
    up_s: float,
    connected: bool,
    ready: bool,
    reconnects: int = 0,
    down_for: float | None = None,
    failed: str = "",
) -> Row:
    """The MQTT link to the station PC (amr_station.mqtt_link). Ready = connected, announced
    and subscribed. failed: the bridge could not start (credentials, paho) and will exit."""
    n = dict(reconnects=int(reconnects))
    if not configured:
        return Row("station_link", ABSENT, "", "station.enabled false", **n)
    if failed:
        return Row("station_link", LOST, "STATION_LINK_DOWN", f"bridge cannot start: {failed}", **n)
    if ready:
        return Row("station_link", OK, "", "", **n)
    if connected:
        return Row("station_link", RECONNECTING, "", "connected, subscribing", **n)
    if down_for is None and up_s < BOOT_GRACE_S:
        return Row("station_link", RECONNECTING, "", "connecting to the broker", **n)
    why = "no link to the broker" + ("" if down_for is None else f" for {down_for:.0f} s")
    return Row("station_link", LOST, "STATION_LINK_DOWN", why, **n)


# ---------------------------------------------------------------- the owner's outbox


class Book:
    """Per owner node: when each device's row goes out. An edge (state or code changed) goes
    at once and restarts `since`; otherwise each device repeats every `period` s, so a late
    subscriber has every row within one period and a consumer can age the owner."""

    def __init__(self, period: float = PERIOD_S) -> None:
        self.period = float(period)
        self._last: dict[str, tuple[str, str]] = {}  # device -> (state, code)
        self._since: dict[str, float] = {}
        self._sent: dict[str, float] = {}

    def offer(self, now: float, row: Row) -> Row | None:
        d = row.device
        key = (row.state, row.code)
        edge = self._last.get(d) != key
        if edge:
            self._last[d], self._since[d] = key, now
        elif d in self._sent and now - self._sent[d] < self.period:
            return None
        self._sent[d] = now
        return replace(row, since_s=max(0.0, now - self._since[d]))

    def edge(self, row: Row) -> bool:
        """True when `row` would change the device's (state, code): an edge, worth an event."""
        return self._last.get(row.device) != (row.state, row.code)


def fill(msg, row: Row, device_ids: dict[str, int], state_ids: dict[str, int]):
    """Copy a Row into a DeviceHealth msg (duck-typed: any object with the fields). The ids
    are wire.py's name -> value tables, inverted by the caller."""
    msg.device = int(device_ids[row.device])
    msg.state = int(state_ids[row.state])
    msg.code, msg.detail = row.code, row.detail
    msg.age_s, msg.since_s = float(row.age_s), float(row.since_s)
    msg.gaps = max(0, min(int(row.gaps), 0xFFFFFFFF))
    msg.rejects = max(0, min(int(row.rejects), 0xFFFFFFFF))
    msg.reconnects = max(0, min(int(row.reconnects), 0xFFFFFFFF))
    msg.timeouts = max(0, min(int(row.timeouts), 0xFFFFFFFF))
    return msg


# ---------------------------------------------------------------- the consumer side


def configured(cfg) -> dict[str, bool]:
    """Which devices this profile fits. A device it does not fit is ABSENT, never LOST."""
    return {
        "drive_left": True,
        "drive_right": True,
        "can_bus": True,
        "mls_track": True,
        "mls_gyro": bool(getattr(cfg, "IMU_ENABLED", True)),
        "dio": bool(getattr(cfg, "DIO_ENABLED", True)),
        "rear_scanner": getattr(cfg, "REAR_SOURCE", "none") == "scanner",
        "station_link": bool(getattr(cfg, "STATION_ENABLED", False)),
    }


def view(
    rows: dict[str, tuple[Row, float]],
    now: float,
    fitted: dict[str, bool],
    up_s: float,
    owner_timeout_s: float = OWNER_TIMEOUT_S,
) -> dict[str, Row]:
    """Every device's row as a consumer should show it. rows: device -> (last Row received,
    receive time, monotonic). up_s: how long the consumer has been listening. Unfitted is
    ABSENT whatever arrives; no row, or one older than owner_timeout_s, is the owner gone."""
    out: dict[str, Row] = {}
    for d in DEVICES:
        if not fitted.get(d, False):
            out[d] = Row(d, ABSENT, "", "not fitted (profile)")
            continue
        got = rows.get(d)
        if got is None:
            if up_s < BOOT_GRACE_S + owner_timeout_s:
                out[d] = Row(d, ABSENT, "", f"no report from {OWNER[d]} yet")
            else:
                out[d] = Row(d, LOST, LOST_CODE[d], f"{OWNER[d]} is not reporting")
            continue
        row, t = got
        age = _race(now - t)
        if age < 0.0 or age > owner_timeout_s:
            out[d] = Row(d, LOST, LOST_CODE[d], f"{OWNER[d]} stopped reporting {age:.0f} s ago")
        else:
            out[d] = replace(row, since_s=row.since_s + max(0.0, age))
    return out


@dataclass(frozen=True)
class Group:
    code: str
    members: tuple[str, ...]  # all must be down, their losses within the window
    absorbs: tuple[str, ...] = ()  # also folded in when down (the bus row under CAN_BUS_LOST)


# Most specific first: a member taken by one group is not offered to the next.
GROUPS = (
    Group("CAN_BUS_LOST", ("drive_left", "drive_right", "mls_track"), absorbs=("can_bus", "mls_gyro")),
    Group("MLS_OFFLINE", ("mls_track", "mls_gyro")),
    Group("IO_ISLAND_LOST", ("dio",)),  # DIO only since decision 23 (no RFID on the cable)
)


@dataclass(frozen=True)
class Finding:
    code: str
    devices: tuple[str, ...]
    detail: str
    since_s: float


def classify(rows: dict[str, Row], window: float = WINDOW_S) -> tuple[list[Finding], set[str]]:
    """The common-cause correlator. rows: device -> Row (as view() returns, since_s at one
    instant). A group fires when every member is down and the losses began within `window`
    of each other; its members (and any absorbed device that is down) are then suppressed,
    so one cable is one line, not three. -> (findings, suppressed devices)."""
    found: list[Finding] = []
    taken: set[str] = set()
    for g in GROUPS:
        members = [rows.get(d) for d in g.members]
        if any(r is None or r.state not in DOWN or r.device in taken for r in members):
            continue
        since = [r.since_s for r in members]
        if max(since) - min(since) > window:
            continue
        devs = [r.device for r in members]
        devs += [d for d in g.absorbs if d not in taken and rows.get(d) is not None and rows[d].state in DOWN]
        taken.update(devs)
        detail = "; ".join(f"{d}: {rows[d].detail}" for d in devs if rows[d].detail)
        found.append(Finding(g.code, tuple(devs), detail, max(since)))
    return found, taken


def standing(rows: dict[str, Row], window: float = WINDOW_S) -> list[Finding]:
    """What a consumer stands as alarm rows: the correlated findings, then every other
    device that is not OK or ABSENT and carries a code. Worst state first."""
    found, taken = classify(rows, window)
    rest = sorted(
        (r for d, r in rows.items() if d not in taken and r.state not in (OK, ABSENT) and r.code),
        key=lambda r: (RANK[r.state], DEVICES.index(r.device)),
    )
    return found + [Finding(r.code, (r.device,), r.detail, r.since_s) for r in rest]
