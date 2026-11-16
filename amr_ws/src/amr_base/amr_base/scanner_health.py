"""The safety scanners' own diagnosis as alarm rows (unified plan WP-E4, 2026-11-16). Pure.

Source: survey scn-diag-status-overview, sensor-dropout plan H-P1-12 (web half). No rclpy and
no message import: the callers pass plain dicts, so the web and a node can both use it.

    rows(diags, rear_scanner, scan_fresh, overview) -> [(code, detail)], worst first
    front_case(diags)                                -> the front active monitoring case (shown only)
    ScanGap                                          -> SURVEY_SCAN_GAP once per scan gap (front only)

`diags` is /diagnostics as amr_web.adapter stores it: {name: {"name", "hardware_id", "level",
"message", "values": {key: value}, "age_s"}} (a list of such statuses works too, and "values"
may be the message's [{"key", "value"}] list).

What the sick_safetyscanners2 driver (1.0.5, SickSafetyscanners sensorDiagnostics) publishes:
one status "<node>: State" per driver node, hardware_id = the sensor IP, values with the keys
below, booleans as "True" / "False". Level STALE "Waiting for data" before the first packet,
ERROR on an invalid header or a device error. After a data loss the State keeps its LAST values
(survey verifier): it is no silence signal, so a scanner whose scan is not fresh gets no row
here; SCANNER_STALE / REAR_SCANNER_SILENT say that. The key names are pinned by the fixture in
test_scanner_health.py: confirm them with `ros2 topic echo --once /diagnostics` on the vehicle.

StatusOverview (the driver's status_overview service, a CoLa2 read) adds config_state; the
caller asks for it at readiness and on a level change, never per tick.

Nothing here decides motion. The stop is the scanner's OSSD pair into the FX3; these rows say
WHY the field reads violated (a dirty window looks like an obstacle), so they rank above
FIELD_PROTECTIVE / FIELD_BLOCKED: every row here except SCANNER_DIRTY is an ERROR.
"""

from __future__ import annotations

FRONT, REAR = "front", "rear"
# Driver node names: launch/scanner.launch.py and launch/rear_scanner.launch.py. The updater
# names a status "<node name>: <task>" without the namespace, so the two must stay different.
NODES = {FRONT: "sick_safetyscanners2_node", REAR: "sick_safetyscanners2_rear_node"}
STATE_TASK = "State"
LEVEL_OK, LEVEL_WARN, LEVEL_ERROR, LEVEL_STALE = 0, 1, 2, 3  # diagnostic_msgs/DiagnosticStatus

KEY_CONTAMINATION_WARNING = "Contamination warning"
KEY_CONTAMINATION_ERROR = "Contamination error"
KEY_APPLICATION_ERROR = "Application error"
KEY_DEVICE_ERROR = "Device error"
KEY_CASE = "Current monitoring case no table 1"

# StatusOverview.config_state (TI 8022708 §6.3.1.3.1)
CONFIG_VERIFIED = 5
CONFIG_STATES = {3: "not verified", 5: "verified"}

STATE_MAX_AGE_S = 5.0  # the updater publishes at 1 Hz: older is a dead driver, not a reading
GAP_S = 1.0  # SURVEY_SCAN_GAP: no scan for longer than this while surveying

# Worst first. One row per code; the detail names every scanner it concerns.
RANK = ("SCANNER_ERROR", "SCANNER_CONTAMINATED", "SCANNER_CONFIG_UNVERIFIED", "SCANNER_DIRTY")


def scanner_of(name: str) -> str | None:
    """FRONT / REAR for a status name "<node>: <task>", else None."""
    node = str(name or "").split(":", 1)[0].strip().rsplit("/", 1)[-1]
    for scanner, n in NODES.items():
        if node == n:
            return scanner
    return None


def _statuses(diags):
    return list(diags.values()) if isinstance(diags, dict) else list(diags or ())


def _values(status: dict) -> dict:
    v = status.get("values") or {}
    if isinstance(v, dict):
        return v
    return {kv.get("key"): kv.get("value") for kv in v if isinstance(kv, dict)}


def _true(x) -> bool:
    return str(x).strip().lower() in ("true", "1")


def state_status(diags, scanner: str) -> dict | None:
    """The driver's "<node>: State" status for this scanner, or None."""
    for st in _statuses(diags):
        name = str(st.get("name", ""))
        if scanner_of(name) == scanner and name.split(":", 1)[-1].strip() == STATE_TASK:
            return st
    return None


def _label(scanner: str, status: dict | None) -> str:
    hw = (status or {}).get("hardware_id") or ""
    return f"{scanner} ({hw})" if hw else scanner


def rows(diags, rear_scanner: bool = False, scan_fresh: dict | None = None,
         overview: dict | None = None, max_age_s: float = STATE_MAX_AGE_S) -> list[tuple[str, str]]:
    """(code, detail) rows for the operator surface, worst first.

    rear_scanner: profile rear.source == "scanner"; without it the rear is never reported.
    scan_fresh: {scanner: bool}, the caller's scan age verdict; None = not gated (tests).
    overview: {scanner: StatusOverview fields as a dict}, the last service answer."""
    scope = (FRONT, REAR) if rear_scanner else (FRONT,)
    found: dict[str, list[str]] = {}

    def add(code: str, text: str) -> None:
        found.setdefault(code, []).append(text)

    for scanner in scope:
        st = state_status(diags, scanner)
        fresh = scan_fresh is None or bool(scan_fresh.get(scanner))
        age = (st or {}).get("age_s")
        if st is not None and fresh and (age is None or 0.0 <= float(age) <= max_age_s):
            level, v, who = int(st.get("level", LEVEL_OK)), _values(st), _label(scanner, st)
            if level != LEVEL_STALE:  # STALE: no packet yet; SCANNER_SILENT says that
                errors = [k.lower() for k in (KEY_DEVICE_ERROR, KEY_APPLICATION_ERROR) if _true(v.get(k))]
                if errors or level == LEVEL_ERROR:
                    add("SCANNER_ERROR", f"{who}: {', '.join(errors) or st.get('message') or 'error'}")
                if _true(v.get(KEY_CONTAMINATION_ERROR)):
                    add("SCANNER_CONTAMINATED", f"{who}: contamination error")
                elif _true(v.get(KEY_CONTAMINATION_WARNING)):
                    add("SCANNER_DIRTY", f"{who}: contamination warning")
        ov = (overview or {}).get(scanner)
        if ov:
            try:
                cs = int(ov.get("config_state"))
            except (TypeError, ValueError):
                cs = None
            if cs != CONFIG_VERIFIED:
                add("SCANNER_CONFIG_UNVERIFIED",
                    f"{_label(scanner, st)}: config_state {cs} ({CONFIG_STATES.get(cs, 'unknown')})")
            try:
                err = int(ov.get("error_info_code") or 0)
            except (TypeError, ValueError):
                err = 0
            if err and any(t.startswith(scanner) for t in found.get("SCANNER_ERROR", ())):
                # the scanner's last error: its class gives the recovery action
                found["SCANNER_ERROR"].append(f"{scanner} error code 0x{err:08X}")
    return [(code, "; ".join(found[code])) for code in RANK if code in found]


def front_case(diags) -> int | None:
    """The front scanner's active monitoring case from its State, for SHOWING (never gating:
    WP-E2, survey scn-outputpaths-valid-safe). None without a State or a number."""
    st = state_status(diags, FRONT)
    if st is None or int(st.get("level", LEVEL_OK)) == LEVEL_STALE:
        return None
    try:
        return int(_values(st).get(KEY_CASE))
    except (TypeError, ValueError):
        return None


class ScanGap:
    """SURVEY_SCAN_GAP (H-P1-12): while surveying, a front /scan older than limit_s is a gap in
    the map. Reported ONCE per gap; a fresh scan closes it. Front only: SLAM maps /scan.
    An age of None (no scan seen yet) is no gap: the survey's own start check covers it."""

    CODE = "SURVEY_SCAN_GAP"

    def __init__(self, limit_s: float = GAP_S) -> None:
        self.limit_s = float(limit_s)
        self._open = False

    def update(self, scan_age_s: float | None) -> str | None:
        """The event text to emit now, or None."""
        if scan_age_s is None or scan_age_s <= self.limit_s:
            self._open = False
            return None
        if self._open:
            return None
        self._open = True
        return f"NO SCAN for {scan_age_s:.1f} s: the map has a gap here"
