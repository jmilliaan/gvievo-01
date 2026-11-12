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
from agv_core import position_status as pos

from amr_base import drive_state

FRESH_S = 0.5  # panel / drives / mux samples older than this are not current
# The scanner runs at 34 Hz. A gap this long is a dead link, not a late frame; the grace
# period stops a page loaded during boot from accusing a scanner that is still starting.
SCAN_STALE_S = 5.0
SCAN_GRACE_S = 20.0

# The headline the operator reads first. Worst wins; the order here IS the priority.
NEEDS_SERVICE = "NEEDS SERVICE"
NOT_READY = "NOT READY"
STOPPED_NEEDS_YOU = "STOPPED (needs you)"
STOPPED_WILL_RESUME = "STOPPED (will resume)"
RUNNING = "RUNNING"
READY = "READY"
# A run that holds the vehicle: a restart or a mode swap waits for it (headline + restart).
RUN_ACTIVE = ("READY", "EXECUTING", "PAUSED", "BLOCKED")


def _drive_code(drives: dict | None) -> str | None:
    """A drive row is the one place the operator's action differs by statusword:
    'Switch on disabled' on both drives is the safety chain, not a broken drive."""
    if drives is None:
        return None
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

    def add(code: str, detail: str = "") -> None:
        out.append(cat.describe(code, detail))

    mode = state.get("mode")
    if not mode or (state.get("mode_age_s") or 0) > 5.0:
        add("SUPERVISOR_DOWN", "no ModeState from the supervisor")
        return out  # nothing else can be trusted without it
    if mode.get("fault_code"):
        add(mode["fault_code"], mode.get("reason", ""))

    panel, panel_age = state.get("panel"), (state.get("panel") or {}).get("age_s")
    if panel is None or (panel_age or 0) > FRESH_S or not panel.get("valid"):
        add("PANEL_STALE", "no fresh, valid panel image" if panel else "no panel image at all")

    drive_code = _drive_code(state.get("drives"))
    if drive_code:
        d = state["drives"]
        add(drive_code, f"{d.get('left', '?')} / {d.get('right', '?')}")

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

    loc = state.get("localization")
    # Localisation only matters where the vehicle navigates by it: in IDLE (no layer)
    # an UNLOCALIZED monitor is not something the operator has to fix.
    if loc and loc.get("code") and mode.get("mode_name") == "NAVIGATION":
        add(loc["code"], loc.get("reason", ""))

    # Storage (power-loss plan W3). Warned a gigabyte early, because the cure - deleting
    # old maps and reports - is an engineer's job and takes a visit.
    d = state.get("disk") or {}
    if d.get("level") == "stop":
        add("DISK_FULL", f"{d.get('free_mb')} MB free on {d.get('path')}")
    elif d.get("level") == "warn":
        add("DISK_LOW", f"{d.get('free_mb')} MB free on {d.get('path')}")

    if state.get("station_link_home"):
        add("STATION_LINK_HOME", state["station_link_home"])

    mux = state.get("mux")
    if mux and mux.get("inhibited") and mux.get("code"):
        add(mux["code"], mux.get("reason", ""))

    # Worst first, and never the same code twice (a mux inhibit during a supervisor
    # FAULT is the same stop said twice).
    # A drive row that names the fault says everything DRIVES_NOT_READY would, and more.
    if any(r["code"] in ("DRIVE_FAULT", "DRIVE_SILENT") for r in out):
        out = [r for r in out if r["code"] != "DRIVES_NOT_READY"]
    seen, unique = set(), []
    for row in sorted(out, key=lambda r: cat.SEVERITY_ORDER[r["level"]]):
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        unique.append(row)
    return unique


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
    top = rows[0] if rows else None
    detail = ""

    if top and top["clears_by"] == "restart_service":
        line = NEEDS_SERVICE
    elif mode.get("mode_name") in ("STARTING", "TRANSITIONING") or not mode.get("base_ready"):
        line = NOT_READY
    elif run.get("state_name") == "EXECUTING":
        line = RUNNING
    elif run.get("state_name") == "BLOCKED":
        line = STOPPED_WILL_RESUME if run.get("auto_resume") else STOPPED_NEEDS_YOU
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

    return {
        "state": line,
        "detail": detail,
        "action": top["action"] if top else "Nothing to do.",
        "title": top["title"] if top else "The vehicle is fine.",
        "code": top["code"] if top else "",
        "level": top["level"] if top else "info",
        "button": cat.BUTTON.get(top["clears_by"], "") if top else "",
        "clears_by": top["clears_by"] if top else "",
    }


# ---- the Home status tile (manuals/emergency-suite-plan.md Part A) ----------------------------
# One full-width tile, one state. Colour is the meaning: green = normal, yellow = abnormal (blinking:
# not localized), red = stopped for something only a person or a restart fixes, grey = not up yet.
# The E-stop is not seen by the PC yet (Q3 not wired, Part B postponed): it shows through what it
# causes - an estop hold (stopped) or SAFETY_RESET_NEEDED (attention) - and is never red or green here.
TILE_OK, TILE_WARN, TILE_ERROR, TILE_OFF = "ok", "warn", "error", "off"
NOT_LOCALIZED = "NOT LOCALIZED"
CHECKING_POSITION = "CHECKING POSITION"
ATTENTION = "ATTENTION"
LOCALIZE_STEPS = (
    "Turn the selector to MANUAL.",
    "Drive the vehicle to HOME.",
    "Hold the yellow RESET and the green START together for 1 s.",
)
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

    def tile(kind, level, big, row=None, title="", action="", steps=(), blink=False) -> dict:
        return {
            "kind": kind, "level": level, "big": big, "blink": blink,
            "title": row["title"] if row else title,
            "action": row["action"] if row else action,
            "code": row["code"] if row else "",
            "button": cat.BUTTON.get(row["clears_by"], "") if row else "",
            "steps": list(steps),
        }

    def stopped_big(r: dict) -> str:
        return STOPPED_WILL_RESUME if r.get("auto_resume") else STOPPED_NEEDS_YOU

    run_name, line_name = run.get("state_name"), line.get("state_name")
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
        return tile("stopped", TILE_WARN, stopped_big(line), hold_row(line.get("code", "")), "Stopped",
                    line.get("message", ""))

    loc = position.get("loc") if position.get("show") else ""
    if loc == "lost":
        manual = bool(panel.get("valid")) and not panel.get("mode_auto")
        steps = [
            {"text": LOCALIZE_STEPS[0], "done": manual, "now": not manual},
            {"text": LOCALIZE_STEPS[1], "done": False, "now": manual},
            {"text": LOCALIZE_STEPS[2], "done": False, "now": False},
        ]
        return tile("lost", TILE_WARN, NOT_LOCALIZED, None, position["status"],
                    "Localize at HOME with the panel buttons:", steps, blink=True)
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
