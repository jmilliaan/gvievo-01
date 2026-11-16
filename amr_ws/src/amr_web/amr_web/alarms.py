"""Standing alarms and the one-line vehicle state, computed ONCE, server-side.

Before this module the rail, Status, Run and Alarms pages each re-derived "what is
wrong" from `/api/state` in their own JavaScript, in their own words. They
disagreed, and none of them could say what to press. Here the state snapshot is
turned into catalogue rows (agv_core/alarms.py) exactly once; every page renders
what this returns and invents nothing.

Pure: a dict in, a dict out. `since` bookkeeping lives in the caller (the Flask
app holds a StandingTracker), so this function is trivially testable.
"""

from __future__ import annotations

from typing import Any

from agv_core import alarms as cat
from agv_core import health
from agv_core import position_status as pos

from amr_base import drive_state, hold_policy, scanner_health

FRESH_S = 0.5  # panel / drives / mux samples older than this are not current
# The scanner runs at 34 Hz. A gap this long is a dead link, not a late frame; the grace
# period stops a page loaded during boot from accusing a scanner that is still starting.
SCAN_STALE_S = 5.0
SCAN_GRACE_S = 20.0

# The headline the operator reads first. Worst wins; the order here IS the priority.
EMERGENCY_STOP = "EMERGENCY STOP"
NEEDS_SERVICE = "NEEDS SERVICE"
NOT_READY = "NOT READY"
STOPPED_NEEDS_YOU = "STOPPED (needs you)"
STOPPED_WILL_RESUME = "STOPPED (will resume)"
RUNNING = "RUNNING"
READY = "READY"
# A run that holds the vehicle: a restart or a mode swap waits for it (headline + restart).
RUN_ACTIVE = ("READY", "EXECUTING", "PAUSED", "BLOCKED")
# A drive row that names the fault says everything DRIVES_NOT_READY would, and more.
DRIVE_FAULT_CODES = ("DRIVE_FAULT", "DRIVE_SILENT", "DRIVE_REBOOTED")
# What explains each base_missing item (ModeState.base_missing, readiness.base_missing()) when it
# stands already: the BASE_NOT_READY row names only the items nothing else explains.
_MISSING_EXPLAINED = {
    "panel": ("PANEL_STALE", "IO_ISLAND_LOST"),
    "drives": DRIVE_FAULT_CODES + ("SAFETY_RESET_NEEDED", "CAN_BUS_LOST", "CAN_TX_FAILED",
                                   "DRIVE_LINK_FAULT"),
    "wheel feedback": DRIVE_FAULT_CODES + ("CAN_BUS_LOST", "SAFETY_RESET_NEEDED"),
}
STATUS_FRESH_S = 5.0  # a /diagnostics status (1 Hz) older than this is a dead publisher, not a reading
EVENTLOG_STATUS = "eventlog/recorder"  # event_recorder_node's /diagnostics status


# PanelState.emergency (amr_interfaces/msg/PanelState.msg, emergency-suite plan Part B, kyb
# contract). The PC's picture only: the stop itself is the Flexi Soft's STO, in hardware.
EMG_NORMAL, EMG_ACTIVE, EMG_RESET_NEEDED, EMG_RESETTING, EMG_RESET_FAILED = range(5)
EMG_NAMES = {
    EMG_NORMAL: "NORMAL",
    EMG_ACTIVE: "ACTIVE",
    EMG_RESET_NEEDED: "RESET_NEEDED",
    EMG_RESETTING: "RESETTING",
    EMG_RESET_FAILED: "RESET_FAILED",
}
_EMG_CODE = {
    EMG_ACTIVE: "ESTOP",
    EMG_RESET_NEEDED: "ESTOP_RESET_NEEDED",
    EMG_RESETTING: "ESTOP_RESET_NEEDED",
    EMG_RESET_FAILED: "ESTOP_RESET_FAILED",
}
# Said twice while an emergency row stands: the drives sit in 'Switch on disabled' (or standby)
# because of the E-stop, and the mux (code ESTOP) and a run's hold (ESTOP_HOLD, or a 'chain' hold
# before DI09 caught up) report the same stop.
_EMG_SAME_CAUSE = {"SAFETY_RESET_NEEDED", "DRIVES_NOT_READY", "ESTOP_HOLD", "SAFETY_CHAIN_STOP",
                   *_EMG_CODE.values()}
# Why the web refuses a jog or a survey move (409). Always starts "E-stop active".
_EMG_REFUSAL = {
    EMG_ACTIVE: "E-stop active: release it and press Reset first",
    EMG_RESET_NEEDED: "E-stop active: press Reset on the cabinet first",
    EMG_RESETTING: "E-stop active: resetting, wait for it to finish",
    EMG_RESET_FAILED: "E-stop active: the Reset did not take",
}
RESETTING_DETAIL = "resetting…"
# The banner's steps (emergency plan §1: release, Reset, Start). Owner O-3 (2026-11-16): an E-stop
# never ends a run, so Start continues a held one.
EMG_STEPS = (
    "Make the area safe, then release (twist) the E-stop button.",
    "Press the yellow RESET button on the cabinet.",
    "Press START: a stopped run continues.",
)


def _panel_fresh(panel: dict | None) -> bool:
    return bool(panel) and (panel.get("age_s") or 0) <= FRESH_S and bool(panel.get("valid"))


def emergency(state: dict[str, Any]) -> dict | None:
    """The emergency picture when it is NOT normal and can be trusted, else None.

    Only a fresh, valid panel image counts. A stale or invalid one is PANEL_STALE, which
    already says "no motion" - showing it as an emergency would send the operator to an
    E-stop nobody pressed (the controller does treat it as one, fail-safe)."""
    e = state.get("emergency")
    if not e or not _panel_fresh(state.get("panel")):
        return None
    if int(e.get("state") or 0) not in _EMG_CODE:
        return None
    return e


def emergency_refusal(state: dict[str, Any]) -> str:
    """'' when a jog / survey move may be asked for, else the reason it is refused."""
    e = emergency(state)
    return _EMG_REFUSAL[int(e["state"])] if e else ""


def _emergency_row(e: dict) -> dict:
    s = int(e["state"])
    active = "E-stop signal active" if not e.get("estop_ok", True) else ""
    detail = {EMG_ACTIVE: active, EMG_RESETTING: RESETTING_DETAIL}
    return cat.describe(_EMG_CODE[s], detail.get(s, ""))


def banner(state: dict[str, Any]) -> dict | None:
    """The red banner every page shows while not NORMAL (base.html renders it, amr.js
    keeps it current from /api/state). None when there is nothing to show."""
    e = emergency(state)
    if not e:
        return None
    s = int(e["state"])
    released = s in (EMG_RESET_NEEDED, EMG_RESETTING) or (s == EMG_RESET_FAILED and bool(e.get("estop_ok")))
    note = {EMG_RESET_NEEDED: "released: press Reset", EMG_RESETTING: RESETTING_DETAIL}.get(s, "")
    # the RESET_FAILED words are the catalogue row's, so banner and Alarms say the same
    failed = cat.describe("ESTOP_RESET_FAILED") if s == EMG_RESET_FAILED else None
    since = e.get("active_s")
    if since is None:
        since = e.get("since_s")
    return {
        "state": s,
        "state_name": EMG_NAMES[s],
        "title": EMERGENCY_STOP,
        "note": note,
        "failed": bool(failed),
        "failed_text": f"{failed['title']}. {failed['action']}" if failed else "",
        "since_s": since,
        "reason": _EMG_REFUSAL[s],
        "steps": [
            {"text": EMG_STEPS[0], "done": released, "now": not released},
            {"text": EMG_STEPS[1], "done": False, "now": released},
            {"text": EMG_STEPS[2], "done": False, "now": False},
        ],
    }


def _drive_code(drives: dict | None) -> str | None:
    """A drive row is the one place the operator's action differs by statusword:
    'Switch on disabled' on both drives is the safety chain, not a broken drive."""
    if drives is None:
        return None
    # drive_node's own verdict first (DriveStatus.fault_code, WP-B4): DRIVE_SILENT, DRIVE_FAULT,
    # DRIVE_REBOOTED or CAN_TX_FAILED, chosen by canopen.decide() with the bus in hand.
    code = drives.get("fault_code") or ""
    if code in cat.CATALOGUE:
        return code
    states = f"{drives.get('left', '')} {drives.get('right', '')}"
    # The LINK's verdict first (WP-B4): a link in FAULT with cached "Operation enabled"
    # statuswords used to show nothing but DRIVES_NOT_READY. A silent node reads "stale".
    if drives.get("link") == drive_state.LINK_FAULT:
        return "DRIVE_SILENT" if drive_state.STALE in states else "DRIVE_FAULT"
    if drive_state.has_fault(states):
        return "DRIVE_FAULT"
    if not drives.get("operational"):
        if drive_state.SWITCH_ON_DISABLED in states:
            return "SAFETY_RESET_NEEDED"
        return None  # disarmed on purpose (IDLE with no one asking to move) is not an alarm
    return None


def standing(state: dict[str, Any]) -> list[dict]:
    """Everything holding the vehicle right now, worst first, as catalogue rows."""
    out: list[dict] = []
    # The emergency row goes FIRST, whatever the severity sort says (a WARN "press Reset"
    # still outranks everything: nothing else can be fixed until the E-stop is reset).
    e = emergency(state)
    first = [_emergency_row(e)] if e else []

    def add(code: str, detail: str = "") -> None:
        out.append(cat.describe(code, detail))

    mode = state.get("mode")
    if not mode or (state.get("mode_age_s") or 0) > 5.0:
        add("SUPERVISOR_DOWN", "no ModeState from the supervisor")
        return first + out  # nothing else can be trusted without it
    if mode.get("fault_code"):
        add(mode["fault_code"], mode.get("reason", ""))

    panel, panel_age = state.get("panel"), (state.get("panel") or {}).get("age_s")
    if panel is None or (panel_age or 0) > FRESH_S or not panel.get("valid"):
        where = f" (I/O island {state['dio_ip']})" if state.get("dio_ip") else ""
        add("PANEL_STALE", ("no fresh, valid panel image" if panel else "no panel image at all") + where)

    drive_code = _drive_code(state.get("drives"))
    if drive_code:
        d = state["drives"]
        add(drive_code, d.get("fault_detail") or f"{d.get('left', '?')} / {d.get('right', '?')}")

    run = state.get("run")
    if run:
        if run.get("state_name") == "FAULT":
            add(run.get("fault_code") or "EXEC_ACTION_FAILED", run.get("reason", ""))
        elif run.get("state_name") == "BLOCKED":
            add(run.get("fault_code") or cat.hold_code(run.get("hold_cause", "")), run.get("reason", ""))

    line = state.get("line")
    if line and line.get("code"):
        add(line["code"], line.get("message", ""))

    # The scanner is the one failure nothing else reports: its driver is an optional
    # launch member, so an unplugged sensor kills mapping, navigation and localisation
    # while the supervisor still says IDLE and the drives still jog (vehicle, 2026-09-22 -
    # the operator had no way at all to find out). Absence is the evidence, so it is
    # reported after a grace period from web start, not on the first empty poll.
    scan_age = state.get("scan_age_s")
    if (state.get("up_s") or 0.0) > SCAN_GRACE_S:
        if scan_age is None:
            add("SCANNER_SILENT", "no scan since this page's server started")
        elif scan_age > SCAN_STALE_S:
            add("SCANNER_STALE", f"last scan {scan_age:.0f} s ago")
    # The scanners' own diagnosis (WP-E4): why a field reads violated. Only on a fresh scan: after
    # a data loss the driver's State keeps its last values (scanner_health).
    rear_on = state.get("rear_source") == "scanner"
    trolley = state.get("trolley") or {}
    fresh = {"front": scan_age is not None and scan_age <= SCAN_STALE_S,
             "rear": bool(trolley) and trolley.get("state_name", "UNKNOWN") != "UNKNOWN"}
    for code, detail in scanner_health.rows(state.get("diagnostics") or {}, rear_scanner=rear_on,
                                            scan_fresh=fresh, overview=state.get("scanner_overview")):
        add(code, detail)

    # Device health (WP-H1): one row per lost or degraded link, a shared cable as one row
    # (agv_core.health.standing). None: nothing publishes DeviceHealth (not rebuilt, a sim).
    for f in device_findings(state.get("device_health")):
        add(f.code, f.detail)

    loc = state.get("localization")
    # Localisation only matters where the vehicle navigates by it: in IDLE (no layer)
    # an UNLOCALIZED monitor is not something the operator has to fix.
    if loc and loc.get("code") and mode.get("mode_name") == "NAVIGATION":
        add(loc["code"], loc.get("reason", ""))

    # Storage (power-loss plan W3). Warned a gigabyte early, because the cure - deleting
    # old maps and reports - is an engineer's job and takes a visit.
    d = state.get("disk") or {}
    if d.get("readonly"):
        add("DISK_READONLY", f"read-only: {d['readonly']}")
    if d.get("level") == "stop":
        add("DISK_FULL", f"{d.get('free_mb')} MB free on {d.get('path')}")
    elif d.get("level") == "warn":
        add("DISK_LOW", f"{d.get('free_mb')} MB free on {d.get('path')}")

    if state.get("station_link_home"):
        add("STATION_LINK_HOME", state["station_link_home"])

    rec = (state.get("diagnostics") or {}).get(EVENTLOG_STATUS)
    if rec and int(rec.get("level", 0)) >= 2 and (rec.get("age_s") or 0.0) <= STATUS_FRESH_S:
        add("EVENTLOG_WRITE_FAILED", f"{rec.get('message', '')}: {rec.get('hardware_id', '')}".strip(": "))

    mux = state.get("mux")
    if mux and mux.get("inhibited") and mux.get("code"):
        add(mux["code"], mux.get("reason", ""))

    # What the base lacks (ModeState.base_missing, WP-H2): named, so NOT READY never stands
    # beside "The vehicle is fine". Not while starting (the boot is still waiting for them), and
    # only the items no other row explains already.
    codes = {r["code"] for r in out}
    missing = [i.strip() for i in (mode.get("base_missing") or "").split(",") if i.strip()]
    if missing and mode.get("mode_name") not in ("STARTING", "TRANSITIONING"):
        unexplained = [i for i in missing if not codes & set(_MISSING_EXPLAINED.get(i, ()))]
        if unexplained:
            add("BASE_NOT_READY", "missing: " + ", ".join(unexplained))

    # Worst first, and never the same code twice (a mux inhibit during a supervisor
    # FAULT is the same stop said twice).
    codes = {r["code"] for r in out}
    if codes & set(DRIVE_FAULT_CODES):
        out = [r for r in out if r["code"] != "DRIVES_NOT_READY"]
    # The I/O island row says why the panel is stale, and what to check (WP-H2).
    if "IO_ISLAND_LOST" in codes:
        out = [r for r in out if r["code"] != "PANEL_STALE"]
    seen, unique = (set(_EMG_SAME_CAUSE) if first else set()), list(first)
    for row in sorted(out, key=lambda r: cat.SEVERITY_ORDER[r["level"]]):
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        unique.append(row)
    return unique


def device_findings(rows: dict | None) -> list:
    """agv_core.health.standing() over the adapter's view (device -> Row fields as a dict)."""
    if not rows:
        return []
    view = {d: health.Row(**r) for d, r in rows.items() if d in health.DEVICES}
    return [f for f in health.standing(view) if f.code in cat.CATALOGUE]


def home_position(state: dict[str, Any]) -> dict:
    """The Home page's position row: its status line and whether At home can be pressed now. It says what
    the line node says (LineState.home_detail, agv_core.position_status) and only names the rest."""
    mode, line = state.get("mode") or {}, state.get("line")
    if mode.get("mode_name") != "LINE" or not line:
        return {"show": False, "status": "", "level": "info", "enabled": False, "why": "", "loc": ""}
    panel = state.get("panel") or {}
    manual_ok = "order" not in state or (bool(panel.get("valid")) and not panel.get("mode_auto"))
    why_not = "" if manual_ok else "turn the selector to MANUAL"

    # loc: what home_tile() needs to know - "ok", "away", "trip", "fault", "checking" or "lost" (not
    # localized: the operator has to localize at HOME)
    def row(status: str, level: str = "info", press: bool = True, why: str = "", loc: str = "lost") -> dict:
        ok = press and manual_ok
        return {"show": True, "status": status, "level": level, "enabled": ok,
                "why": why or ("" if ok or not press else why_not), "loc": loc}

    loc = state.get("localization") or {}
    name = loc.get("state_name")
    detail = line.get("home_detail") or ""
    if line.get("state_name") == "FAULT":
        return row("Job in fault", "warn", False, "press Reset on the panel", loc="fault")
    if line.get("state_name") in ("ARMED", "RUNNING", "HOLD") or line.get("trip"):
        return row("On a trip", "info", False, "not while a trip is active", loc="trip")
    if detail.startswith(pos.CHECKING):
        return row(detail, "info", False, "checking now", loc="checking")
    if detail.startswith(pos.FAILED):
        return row(detail, "warn")
    if detail.startswith(pos.RECHECKING):
        return row(detail, "warn")
    if name == "READY":
        if line.get("at_home"):
            return row("Position OK", loc="ok")
        return row("Away from home", "info", False, "drive to HOME first", loc="away")
    if name == "LOST":
        return row(f"Position lost: {loc.get('reason') or 'unknown reason'}", "warn")
    if name == "CHECKING":
        return row("Checking position set by hand", loc="checking")
    return row("Position not set", "warn")


def headline(state: dict[str, Any], rows: list[dict]) -> dict:
    """The one line and the one button for the Home page.

    `rows` is what standing() returned (already worst-first), so the top row decides
    the action; the headline itself comes from what the vehicle is DOING, because
    "RUNNING" with an info-level field stop still reads as a stop to the operator.
    """
    mode = state.get("mode") or {}
    run = state.get("run") or {}
    job = state.get("line") or {}
    top = rows[0] if rows else None
    detail = ""
    starting = mode.get("mode_name") in ("STARTING", "TRANSITIONING") or not mode.get("base_ready")

    # The tape job's branches follow home_tile() (WP-H2): the same words for the same state.
    if emergency(state):
        line = EMERGENCY_STOP
    elif top and top["clears_by"] == "restart_service":
        line = NEEDS_SERVICE
    elif "FAULT" in (mode.get("mode_name"), run.get("state_name"), job.get("state_name")):
        line = STOPPED_NEEDS_YOU
    elif starting:
        line = NOT_READY
    elif run.get("state_name") == "EXECUTING" or job.get("state_name") in _LINE_MOVING:
        line = RUNNING
    elif run.get("state_name") == "BLOCKED":
        line = STOPPED_WILL_RESUME if run.get("auto_resume") else STOPPED_NEEDS_YOU
    elif job.get("state_name") == "HOLD":
        line = STOPPED_WILL_RESUME if job.get("auto_resume") else STOPPED_NEEDS_YOU
    elif top and top["level"] == "error":
        line = STOPPED_NEEDS_YOU
    elif run.get("state_name") in ("READY", "PAUSED", "DONE"):
        line = f"READY · {run.get('mission_id') or 'no mission'}"
    else:
        line = READY

    if run.get("state_name") in ("EXECUTING", "PAUSED", "BLOCKED") and run.get("mission_id"):
        total = int(run.get("step_index", -1)) + 1
        step = f" · {run.get('step_id')}" if run.get("step_id") else ""
        detail = f"{run['mission_id']} · step {total}{step}"
    elif job.get("state_name") in ("ARMED", "RUNNING", "HOLD") and job.get("message"):
        detail = job["message"]
    elif starting and mode.get("base_missing"):
        detail = f"waiting for: {mode['base_missing']}"

    # Never "The vehicle is fine" under NOT READY or a stop (H-P1-2).
    idle_title = "Starting up" if line == NOT_READY else (
        "Stopped" if line.startswith("STOPPED") else "The vehicle is fine.")
    idle_action = (mode.get("reason") or "Wait.") if line == NOT_READY else "Nothing to do."
    return {
        "state": line,
        "detail": detail,
        "action": top["action"] if top else idle_action,
        "title": top["title"] if top else idle_title,
        "code": top["code"] if top else "",
        "level": "error" if line == EMERGENCY_STOP else (top["level"] if top else "info"),
        "button": cat.BUTTON.get(top["clears_by"], "") if top else "",
        "clears_by": top["clears_by"] if top else "",
    }


# ---- the Home status tile (manuals/emergency-suite-plan.md Part A) ----------------------------
# One full-width tile, one state. Colour is the meaning: green = normal, yellow = abnormal (blinking:
# not localized), red = stopped for something only a person or a restart fixes, grey = not up yet.
# The E-stop (Part B, 2026-11-16: DI09 = Flexi Soft Q3, PanelState.emergency) is the one row above
# `fault`: red, the banner's content (base.html hides its own banner on Home). Without a fresh, valid
# panel it shows through what it causes - an estop hold (stopped) or SAFETY_RESET_NEEDED (attention).
TILE_OK, TILE_WARN, TILE_ERROR, TILE_OFF = "ok", "warn", "error", "off"
NOT_LOCALIZED = "NOT LOCALIZED"
CHECKING_POSITION = "CHECKING POSITION"
ATTENTION = "ATTENTION"
LOCALIZE_STEPS = (
    "Turn the selector to MANUAL.",
    "Drive the vehicle to HOME.",
    "Hold the yellow RESET and the green START together for 1 s.",
)
# The front panel's buttons by place (documentation/operation-manual/images/IMG-04-02.svg): left recess
# RESET over START, right recess E-STOP over the MANUAL/AUTO selector. The Home page draws them.
PANEL_BUTTONS = ("reset", "start", "estop", "selector")
_LINE_MOVING = ("ARMED", "RUNNING")


def _benign(row: dict, state: dict[str, Any]) -> bool:
    """A standing row that is not worth a yellow tile on its own. Today one: DRIVES_NOT_READY while the
    drives sit in standby on purpose (powered only on demand, 2026-10-08), which stands at every idle."""
    if row["level"] == "info":
        return True
    drives = state.get("drives") or {}
    return row["code"] == "DRIVES_NOT_READY" and drives.get("link") == "standby"


def home_tile(state: dict[str, Any], rows: list[dict], position: dict | None = None) -> dict:
    """The Home page's status tile. `rows` is standing() (worst first), `position` is home_position();
    the page draws what this returns and decides nothing. The first rule that matches wins:

        emergency  red     PanelState.emergency not NORMAL on a fresh, valid panel (the banner's
                           steps, since, RESET_FAILED text; emergency plan A5)
        fault      red     restart_service, a supervisor / run / job FAULT
        starting   grey    STARTING, TRANSITIONING, base not ready
        fault      red     any other ERROR row (panel stale, ...), except an operator's LOC_ row
        running    green   run EXECUTING, tape job ARMED / RUNNING
        stopped    yellow  run BLOCKED, tape job HOLD
        lost       yellow, blinking   not localized (LINE: localize at HOME with the panel;
                                      NAVIGATION: Set position)
        checking   yellow  a position check is running
        fault      red     an ERROR row left
        attention  yellow  a WARN row that is not benign (e.g. SAFETY_RESET_NEEDED after an E-stop at rest)
        ready      green
    """
    mode = state.get("mode") or {}
    run = state.get("run") or {}
    line = state.get("line") or {}
    panel = state.get("panel") or {}
    position = position if position is not None else home_position(state)
    top = rows[0] if rows else None
    worth = [r for r in rows if not _benign(r, state)]

    def tile(kind, level, big, row=None, title="", action="", steps=(), blink=False, press=(),
             press_text="") -> dict:
        return {
            "kind": kind, "level": level, "big": big, "blink": blink,
            "title": row["title"] if row else title,
            "action": row["action"] if row else action,
            "code": row["code"] if row else "",
            "button": cat.BUTTON.get(row["clears_by"], "") if row else "",
            "steps": list(steps),
            # panel buttons the page rings on its panel drawing (PANEL_BUTTONS); empty: no drawing
            "press": list(press),
            "press_text": press_text,  # the drawing's caption
        }

    def stopped_big(r: dict) -> str:
        return STOPPED_WILL_RESUME if r.get("auto_resume") else STOPPED_NEEDS_YOU

    run_name, line_name = run.get("state_name"), line.get("state_name")
    b = banner(state)
    if b:
        # Ring the button the operator needs now: the E-stop to twist out, then Reset.
        # The big text already says EMERGENCY STOP: the title names the step, the steps the rest.
        released = b["steps"][0]["done"]
        row = _emergency_row(emergency(state))
        title = "Emergency stop active" if row["code"] == "ESTOP" else row["title"]
        t = tile("emergency", TILE_ERROR, EMERGENCY_STOP, None, title, "Follow the steps:", b["steps"],
                 press=("reset",) if released else ("estop",),
                 press_text="Press Reset" if released else "Release (twist)")
        t.update(code=row["code"], since_s=b["since_s"], note=b["note"], failed=b["failed"],
                 failed_text=b["failed_text"])
        return t
    if (top and top["clears_by"] == "restart_service") or mode.get("mode_name") == "FAULT":
        return tile("fault", TILE_ERROR, NEEDS_SERVICE if top and top["clears_by"] == "restart_service"
                    else STOPPED_NEEDS_YOU, top, "Supervisor fault", mode.get("reason", ""))
    if run_name == "FAULT" or line_name == "FAULT":
        return tile("fault", TILE_ERROR, STOPPED_NEEDS_YOU, top, "Job in fault", "Press Reset on the panel.")
    if mode.get("mode_name") in ("STARTING", "TRANSITIONING") or not mode.get("base_ready"):
        return tile("starting", TILE_OFF, NOT_READY, top, "Starting up", mode.get("reason", ""))
    errors = [r for r in rows if r["level"] == "error"]
    # an operator-fixable LOC_ row is "not localized" (yellow, below); an engineer's LOC_ row stays red
    if errors and not (errors[0]["code"].startswith("LOC_") and errors[0]["clears_by"] == "operator"):
        return tile("fault", TILE_ERROR, STOPPED_NEEDS_YOU, errors[0])
    if run_name == "EXECUTING" or line_name in _LINE_MOVING:
        return tile("running", TILE_OK, RUNNING, worth[0] if worth else None, "Running the job.",
                    "Nothing to do.")
    # A hold says its own cause (an estop hold: "release the E-stop, Reset, Start"), not whichever row
    # sorted first - SAFETY_RESET_NEEDED stands beside it after an E-stop and says only half of it.
    def hold_row(code: str) -> dict | None:
        return next((r for r in rows if r["code"] == code), top)

    if run_name == "BLOCKED":
        code = run.get("fault_code") or cat.hold_code(run.get("hold_cause", ""))
        return tile("stopped", TILE_WARN, stopped_big(run), hold_row(code), "Stopped", run.get("reason", ""))
    if line_name == "HOLD":
        # A stop waiting for attach / release: the panel calls (pulsed alarm) until Start, and the
        # drawing rings the button that ends it (manuals/stop-call-alarm-plan.md C4).
        calling = line.get("hold_cause") in hold_policy.CALL_CAUSES
        return tile("stopped", TILE_WARN, stopped_big(line), hold_row(line.get("code", "")), "Stopped",
                    line.get("message", ""), press=("start",) if calling else (),
                    press_text="Press to go on" if calling else "")

    loc = position.get("loc") if position.get("show") else ""
    if loc == "lost":
        manual = bool(panel.get("valid")) and not panel.get("mode_auto")
        steps = [
            {"text": LOCALIZE_STEPS[0], "done": manual, "now": not manual},
            {"text": LOCALIZE_STEPS[1], "done": False, "now": manual},
            {"text": LOCALIZE_STEPS[2], "done": False, "now": False},
        ]
        return tile("lost", TILE_WARN, NOT_LOCALIZED, None, position["status"],
                    "Localize at HOME with the panel buttons:", steps, blink=True, press=("reset", "start"),
                    press_text="Press together, 1 s")
    if loc == "checking":
        return tile("checking", TILE_WARN, CHECKING_POSITION, None, position["status"],
                    "Keep the vehicle still at HOME.")
    nav_loc = state.get("localization") or {}
    if mode.get("mode_name") == "NAVIGATION" and nav_loc and nav_loc.get("state_name") != "READY":
        loc_row = next((r for r in rows if r["code"].startswith("LOC_")), None)
        return tile("lost", TILE_WARN, NOT_LOCALIZED, loc_row, "The vehicle does not know where it is",
                    "Set the position on the Mapping page.", blink=True)
    if errors:
        return tile("fault", TILE_ERROR, STOPPED_NEEDS_YOU, errors[0])
    if worth:
        return tile("attention", TILE_WARN, ATTENTION, worth[0])
    return tile("ready", TILE_OK, READY, None, "The vehicle is fine.", "Nothing to do.")


class StandingTracker:
    """Keeps `since` for each standing code across polls, so the Alarms page can say
    'for 4 minutes' and the history can say when it cleared. Not thread-hostile: the
    Flask request threads call it under the app's own GIL-level atomicity only, so it
    takes no lock and does the simplest possible thing."""

    def __init__(self) -> None:
        self._since: dict[str, float] = {}

    def apply(self, rows: list[dict], now: float) -> list[dict]:
        live = {r["code"] for r in rows}
        for code in list(self._since):
            if code not in live:
                del self._since[code]
        for row in rows:
            row["since"] = self._since.setdefault(row["code"], now)
            row["for_s"] = round(now - row["since"], 1)
        return rows
