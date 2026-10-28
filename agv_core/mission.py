"""Tape-AGV missions: missions/<name>.json, validated against the vehicle profile.

Schema v2 (2026-10-08): the mission IS the site's RFID tag reference table. One
row per tag, and the row says everything the tag does:

    stop          decelerate to rest over stop_distance_m, then by role:
                    home         the run ends there (DONE); the next run is a new job
                    always       wait for the physical Start, every pass
                    destination  stop only when it is the job's destination, and
                                 only until it has been served once
    u_turn        decelerate to approach_mps within decel_m, creep until the tape
                  ends, stop at once (at creep speed or not), pivot (cw|ccw) until
                  the tape is reacquired and centred - 180 deg by geometry, the
                  encoders only gate it (amr_line.uturn)
    ignore_s      after a read is ACTED ON, the same tag is ignored this long.
                  A stop's window restarts at departure, since a parked vehicle
                  outlasts any window.

RFID decides WHERE TO STOP; the MLS marker codes decide SPEED (operator, 2026-10-09).
The v2.1 RFID zone rows (zone_outer/zone_inner) and the v2 speed_toggle are refused:
speed zones work whatever the RFID setting is, and RFID never changes the speed.

high_zone (v2.2, 2026-10-09): null (the run stays at NORMAL) or
    {"pair_spacing_m": 0.5, "outer_code": 2, "inner_code": 1}
Every straight end carries two MLS markers: the OUTER code on the corner side, the
INNER code on the straight side. Outer then inner = entering the straight: HIGH until
the exit pair. Inner while HIGH = leaving (amr_line.speed_zone). The codes are shared
by every pair, must be laid on the floor (mls.marker_codes), and are reserved: nothing
else may use them. There is no HIGH distance budget (2026-10-24, operator: slowdowns
are marker codes, or localization later); shortest_straight_m is refused by name.
Marker events are always on (2026-10-23): a mission without a high_zone runs NORMAL only.

Branching stays its own table (branch_latch + branch_default) and its own engine
(amr_line.branch): speed, stops and branch orders never share a tag.

v1 (gy-demo's route sequence, route_guard, stop_until_start_button, u_turn,
outbound/inbound direction) is retired: a v1 document is refused by name rather
than half-loaded. The repo ships no site mission; "empty" (or no mission) is
plain line following. missions/empty.json, when present, is what plain line
following runs - the site's U-turn tags, so a vehicle without a job still turns
at the tape ends (2026-10-08).

    list_missions()          -> ["empty", ...]
    load(name, vehicle=None) -> dict of the names below, or MissionError
    destinations(m)          -> the destination labels, in table order
    summary(m)               -> the picker's note: branch rule, speed rule

The four basic jobs (2026-10-23) are plain line following with the site's U-turn tags:
empty (always left), basic-right, basic-high-left, basic-high-right (high zones on the
line-a marker pair).

MISSION_NAME, BRANCH_DEFAULT, BRANCH_LATCH, TAGS {tag: row}, HOME (row | None),
DESTINATIONS (labels), HIGH_ZONE ({"inner", "outer" (marker codes, int), "arm_m",
"spacing_m"} | None), MARKER_RUN (dict | None, below).

marker_run (optional, 2026-10-18, tracked plan 3 section 7.5): a run with no RFID at all,
for the straight in front of MRU. Two MLS marker codes do what tags 0180 and Home did:
    {"uturn_code": 2, "home_code": 1, "direction": "cw", "approach_mps": 0.1,
     "decel_m": 0.3, "max_approach_m": 2.0, "stop_distance_m": 0.5, "label": "T-HOME"}
Out: the first uturn_code starts the U-turn approach (as a u_turn tag row). Back, after
the pivot: the first home_code ends the run at home (a measured stop, DONE); a uturn_code
there means the home marker was missed - FAULT at once (the backstop strip). The codes
mean nothing else, so the block is refused with a high_zone that uses either of them
(2026-10-24: a zone on other codes is allowed, and the home stop is then checked from
HIGH) and with any RFID tag or branch row.
    Optional "home_arm_m" (2026-10-23): ONE code for both, told apart by wheel travel. A read
    of the shared code is ignored until home_arm_m has been driven from either end: since
    Start out (the departure crosses the home strip), since the pivot back (after the
    own-strip re-pass). The first read after that is the U-turn out, home back. With two
    codes the backstop stays; with one there is none (a missed home strip drives on).

guided (optional, 2026-10-23): {"cruise_mps": 0.3}. A walked run: the engineer gives each
branch order by hand (left / straight / right, one shot, consumed by the next fork) and the
follower never exceeds cruise_mps outside HIGH. Refused with RFID branch rows (two sources
of orders would race). A high_zone is allowed since 2026-10-24 but starts switched off: the
guided page's speed toggle (NORMAL / HIGH, NORMAL at every mission load) lets the marker
pair grant HIGH. The codes still decide where HIGH begins and ends.

Free of ROS; the line layer and the web both read it.
"""
import json
import os

from agv_core import kinematics
from agv_core.config import ConfigError, _coerce

MISSION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "missions")

ACTIONS = ("stop", "u_turn")
# The outer marker waits this far beyond the pair spacing for its inner marker. RFID
# needed 1.0 m (first reads of a 0.5 m pair landed 0.65-0.99 m apart, 2026-10-08); an
# MLS marker is reported at a fixed point - FailSafe, after the 100 mm marker plus the
# t90 filter delay, the same lag for both - so 0.15 m covers encoder scale and skew.
# Wider is safe (an expired arm is NORMAL) but it must stay below the exit-outer ->
# entry-outer distance through a corner.
ZONE_ARM_TOLERANCE_M = 0.15
ROLES = ("home", "always", "destination")

# Keys per action, beyond the common tag/action/ignore_s. "label" is optional on
# u_turn and speed_toggle rows, required on stops (the operator picks by it).
_KEYS = {
    "stop": {"stop_distance_m", "role", "label"},
    "u_turn": {"direction", "approach_mps", "decel_m", "max_approach_m"},
}
_COMMON = {"tag", "action", "ignore_s"}
_OPTIONAL = {"stop": set(), "u_turn": {"label"}}

_V1_KEYS = ("route", "route_guard", "stop_until_start_button", "u_turn")


class MissionError(ConfigError):
    """A mission file that cannot be run as written."""


def _tag(raw, width, where, ignored):
    """The reader hands tags over as hex text (rfid.tag_of): a JSON number, a
    wrong width or an ignored tag is a rule that never fires, and fails silently."""
    if not isinstance(raw, str):
        raise ConfigError(f"{where}: expected a {width}-character hex string like \"0010\", "
                          f"got {raw!r}. Tag ids come from rfid.tag_of() as hex text, "
                          f"so a number never matches.")
    tag = raw.strip().upper()
    if len(tag) != width or any(c not in "0123456789ABCDEF" for c in tag):
        raise ConfigError(f"{where}: expected {width} hex characters as the RFID panel "
                          f"shows them, got {raw!r}")
    if tag in ignored:
        raise ConfigError(f"{where}: {tag} is also in rfid.ignore_tags, so the reader "
                          f"discards it before any rule can see it")
    return tag


def _read_branch_latch(rows, tag_len, ignore_tags):
    """branch_latch -> validated rows, or [] when there are no junctions.

    An entry tag sets a direction and an exit tag clears it (branch.Ladder).
    Every check here exists to stop a rung being silently DEAD: a tag that never
    matches produces no error, no log line and no motion - the AGV simply drives
    past the junction.

    slow_speed is OPTIONAL and must be false (2026-10-09, operator: no RFID tag affects the
    speed - the MLS marker codes do). It is still type-checked: the string "True" is
    refused, not silently accepted as truthy.
    """
    if not isinstance(rows, list):
        raise ConfigError("branch_latch: expected a list")
    want = {"entry_tag", "exit_tag", "branch"}
    optional = {"slow_speed"}
    width = tag_len * 2
    seen = {}
    out = []
    for i, row in enumerate(rows):
        where = f"branch_latch[{i}]"
        if not isinstance(row, dict):
            raise ConfigError(f"{where}: expected an object")
        unknown = set(row) - want - optional
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
        missing = want - set(row)
        if missing:
            raise ConfigError(f"{where}: missing key(s) {sorted(missing)}")

        slow = _coerce(row.get("slow_speed", False), bool, f"{where}.slow_speed")
        if slow:
            raise ConfigError(f"{where}.slow_speed: retired 2026-10-09 - no RFID tag affects the speed; "
                              f"a junction that must not be passed at HIGH lies outside the marker "
                              f"high zone (high_zone.outer_code/inner_code)")
        side = _coerce(row["branch"], str, f"{where}.branch")
        if side not in ("left", "right"):
            raise ConfigError(f"{where}.branch: expected 'left' or 'right', got {side!r}")

        tags = {key: _tag(row[key], width, f"{where}.{key}", ignore_tags)
                for key in ("entry_tag", "exit_tag")}
        if tags["entry_tag"] == tags["exit_tag"]:
            raise ConfigError(f"{where}: entry_tag and exit_tag are both {tags['entry_tag']} - "
                              f"the same read cannot both set and clear the latch")
        for key, tag in tags.items():
            if tag in seen:
                raise ConfigError(f"{where}.{key}: tag {tag} is already used by {seen[tag]} - "
                                  f"one tag cannot mean two things")
            seen[tag] = f"{where}.{key}"
        out.append({"entry_tag": tags["entry_tag"], "exit_tag": tags["exit_tag"],
                    "branch": side, "slow_speed": slow})
    return out


def _bounded(row, key, where, lo, hi, lo_open=True):
    v = _coerce(row[key], float, f"{where}.{key}")
    ok = (lo < v if lo_open else lo <= v) and v <= hi
    if not ok:
        raise ConfigError(f"{where}.{key} must be in {'(' if lo_open else '['}{lo:g}, {hi:g}], got {v:g}")
    return v


def _decel_needed(vehicle, v_rpm, distance_m, end_rpm=0.0):
    """(the r/min/s that takes v_rpm to end_rpm over distance_m, the drives' 6084h limit)."""
    return (kinematics.approach_decel_rpm_s(v_rpm, end_rpm, distance_m, vehicle.MPS_PER_RPM),
            float(vehicle.RAMP["auto"]["decel"]))


def _uturn_approach(row, where, vehicle):
    """The U-turn approach every mission shape shares: approach_mps (at most NORMAL),
    max_approach_m and decel_m, plus (rate, limit) for slowing NORMAL -> approach_mps
    over decel_m. Each caller words its own refusal."""
    normal_mps = vehicle.AUTO_RPM * vehicle.MPS_PER_RPM
    out = {"approach_mps": _bounded(row, "approach_mps", where, 0.0, round(normal_mps, 3)),
           "max_approach_m": _bounded(row, "max_approach_m", where, 0.0, 5.0),
           "decel_m": _bounded(row, "decel_m", where, 0.0, 2.0)}
    rate, limit = _decel_needed(vehicle, vehicle.AUTO_RPM, out["decel_m"],
                                out["approach_mps"] / vehicle.MPS_PER_RPM)
    return out, rate, limit


def _read_tags(rows, vehicle, branch_tags):
    """tags -> {tag: normalised row}. Every rule a tag can carry, one row each."""
    if not isinstance(rows, list):
        raise ConfigError("tags: expected a list")
    width = 2 * vehicle.RFID_TAG_LEN
    ignored = {t.upper() for t in vehicle.RFID_IGNORE_TAGS}
    out, labels = {}, {}
    for i, row in enumerate(rows):
        where = f"tags[{i}]"
        if not isinstance(row, dict):
            raise ConfigError(f"{where}: expected an object")
        action = row.get("action")
        if action == "speed_toggle":
            raise ConfigError(f"{where}: speed_toggle is retired (2026-10-08): a missed read "
                              f"carried HIGH into a corner. Speed is the MLS marker pair: "
                              f"high_zone.outer_code/inner_code")
        if action in ("zone_inner", "zone_outer"):
            raise ConfigError(f"{where}: RFID zone tags are retired (2026-10-09): RFID decides "
                              f"where to stop, the MLS marker codes decide speed. Lay an "
                              f"outer/inner marker pair and set high_zone.outer_code/inner_code")
        if action not in ACTIONS:
            raise ConfigError(f"{where}.action: expected one of {list(ACTIONS)}, got {action!r}")
        allowed = _COMMON | _KEYS[action] | _OPTIONAL[action]
        unknown = set(row) - allowed
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)} for a {action} row")
        missing = (_COMMON | _KEYS[action]) - set(row)
        if missing:
            raise ConfigError(f"{where}: missing key(s) {sorted(missing)} for a {action} row")

        tag = _tag(row["tag"], width, f"{where}.tag", ignored)
        where = f"tags[{i}] ({tag})"
        if tag in out:
            raise ConfigError(f"{where}: tag {tag} is listed twice - one tag cannot mean two things")
        if tag in branch_tags:
            raise ConfigError(f"{where}: tag {tag} is also a branch_latch tag - "
                              f"one tag cannot mean two things")
        rec = {"tag": tag, "action": action,
               "ignore_s": _bounded(row, "ignore_s", where, 0.0, 30.0, lo_open=False),
               "label": ""}
        if "label" in row:
            rec["label"] = _coerce(row["label"], str, f"{where}.label").strip()

        if action == "stop":
            rec["stop_distance_m"] = _bounded(row, "stop_distance_m", where, 0.0, 5.0)
            role = row["role"]
            if role not in ROLES:
                raise ConfigError(f"{where}.role: expected one of {list(ROLES)}, got {role!r}")
            rec["role"] = role
            if not rec["label"]:
                raise ConfigError(f"{where}.label: a stop needs a name the operator recognises")
            if rec["label"] in labels:
                raise ConfigError(f"{where}.label: {rec['label']!r} is already {labels[rec['label']]}")
            labels[rec["label"]] = tag
        else:  # u_turn
            if row["direction"] not in ("cw", "ccw"):
                raise ConfigError(f"{where}.direction must be cw or ccw")
            rec["direction"] = row["direction"]
            # NORMAL -> approach_mps over decel_m within the drives' deceleration. The
            # tag belongs in a NORMAL area; arriving HIGH, the rate is capped at runtime
            # and the slowdown takes longer than decel_m.
            approach, rate, decel = _uturn_approach(row, where, vehicle)
            rec.update(approach)
            if rate > decel:
                raise ConfigError(f"{where}.decel_m: slowing from {vehicle.AUTO_RPM:.0f} r/min to "
                                  f"{rec['approach_mps']:g} m/s in {rec['decel_m']:g} m needs {rate:.0f} "
                                  f"r/min/s, beyond drivers.ramp.auto.decel {decel:.0f}")
        out[tag] = rec
    return out


def _check_table(tags, vehicle, fastest_rpm):
    """Rules that span rows: one home, stops the drives can make from the fastest speed."""
    homes = [r for r in tags.values() if r["action"] == "stop" and r["role"] == "home"]
    if len(homes) > 1:
        raise ConfigError(f"tags: {len(homes)} home stops ({', '.join(r['tag'] for r in homes)}); "
                          f"a run ends at exactly one place")
    dests = [r for r in tags.values() if r["action"] == "stop" and r["role"] == "destination"]
    if dests and not homes:
        raise ConfigError("tags: destination stops need a home stop - the run starts and ends there")

    # A measured stop from the fastest speed the mission can reach (HIGH when it has a
    # high zone: a stop tag read during a late exit) must be within what the drives
    # decelerate at: beyond it, 6084h clips the profile and the vehicle stops past the mark.
    for r in tags.values():
        if r["action"] != "stop":
            continue
        rate, decel = _decel_needed(vehicle, fastest_rpm, r["stop_distance_m"])
        if rate > decel:
            raise ConfigError(f"tags ({r['tag']}): stopping from {fastest_rpm:.0f} r/min in "
                              f"{r['stop_distance_m']:g} m needs {rate:.0f} r/min/s, beyond "
                              f"drivers.ramp.auto.decel {decel:.0f}; commission a longer stop_distance_m")
    return homes[0] if homes else None


_MISSION_KEYS = ("mission_name", "branch_default", "branch_latch", "high_zone", "tags")
_OPTIONAL_MISSION_KEYS = ("marker_run", "guided", "max_tag_gap_m")
_MARKER_RUN_KEYS = {"uturn_code", "home_code", "direction", "approach_mps", "decel_m", "max_approach_m",
                    "stop_distance_m", "label"}
_MARKER_RUN_OPTIONAL = {"home_arm_m"}
# Past the approach distance the own strip is re-passed within this; amr_line.uturn uses it.
REARM_MARGIN_M = 1.0
# Junction guard (2026-10-23, amr_line.tape_run): a marker-run read acts only after this
# much travel with no second tape under the MLS, so the home stop must be longer than it.
MARKER_JUNCTION_M = 0.3


def _read_marker_run(raw, vehicle, fastest_rpm):
    """marker_run -> the validated block, or None. fastest_rpm: the home stop's start speed
    (HIGH with a high zone on other codes)."""
    if raw is None:
        return None
    allowed = _MARKER_RUN_KEYS | _MARKER_RUN_OPTIONAL
    if not isinstance(raw, dict) or not (_MARKER_RUN_KEYS <= set(raw) <= allowed):
        raise ConfigError(f"marker_run: expected null or exactly {sorted(_MARKER_RUN_KEYS)} "
                          f"(+ optional {sorted(_MARKER_RUN_OPTIONAL)})")
    laid = list(vehicle.MLS_MARKER_CODES)
    out = {}
    for key in ("uturn_code", "home_code"):
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigError(f"marker_run.{key}: expected an integer marker code, got {v!r}")
        if v not in laid:
            raise ConfigError(f"marker_run.{key}: code {v} is not laid on the floor "
                              f"(mls.marker_codes {laid})")
        out[key] = v
    if out["uturn_code"] == out["home_code"] and "home_arm_m" not in raw:
        raise ConfigError("marker_run: uturn_code and home_code must differ, or share one code with "
                          "home_arm_m (the travel from Start or the pivot before that code counts)")
    if raw["direction"] not in ("cw", "ccw"):
        raise ConfigError("marker_run.direction must be cw or ccw")
    out["direction"] = raw["direction"]
    out["label"] = _coerce(raw["label"], str, "marker_run.label").strip()
    if not out["label"]:
        raise ConfigError("marker_run.label: the home stop needs a name the operator recognises")
    approach, rate, decel = _uturn_approach(raw, "marker_run", vehicle)
    out.update(approach)
    # past the junction guard, with room left to brake (a measured stop, not a hard one)
    out["stop_distance_m"] = _bounded(raw, "stop_distance_m", "marker_run", MARKER_JUNCTION_M + 0.1, 5.0)
    out["home_arm_m"] = None
    if "home_arm_m" in raw:
        # beyond the own strip's re-pass after the pivot (approach travel + the rearm margin)
        out["home_arm_m"] = _bounded(raw, "home_arm_m", "marker_run",
                                     out["max_approach_m"] + REARM_MARGIN_M, 1000.0)
    if rate > decel:
        raise ConfigError(f"marker_run.decel_m: {rate:.0f} r/min/s is beyond "
                          f"drivers.ramp.auto.decel {decel:.0f}")
    rate, decel = _decel_needed(vehicle, fastest_rpm, out["stop_distance_m"])
    if rate > decel:
        raise ConfigError(f"marker_run.stop_distance_m: stopping from {fastest_rpm:.0f} r/min needs "
                          f"{rate:.0f} r/min/s, beyond drivers.ramp.auto.decel {decel:.0f}")
    return out


def _read_guided(raw, vehicle):
    """guided -> {"cruise_mps", "cruise_rpm"}, or None."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"cruise_mps"}:
        raise ConfigError("guided: expected null or exactly ['cruise_mps']")
    normal_mps = vehicle.AUTO_RPM * vehicle.MPS_PER_RPM
    cruise = _bounded(raw, "cruise_mps", "guided", 0.0, round(normal_mps, 3))
    return {"cruise_mps": cruise, "cruise_rpm": cruise * vehicle.RPM_PER_MPS}


def _read_high_zone(raw, vehicle):
    """high_zone -> the marker pair, or None."""
    if raw is None:
        return None
    if isinstance(raw, dict) and "shortest_straight_m" in raw:
        raise ConfigError("high_zone.shortest_straight_m: removed 2026-10-24 - HIGH has no distance "
                          "budget any more and lasts until the exit marker pair; delete the key")
    keys = {"pair_spacing_m", "outer_code", "inner_code"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ConfigError(f"high_zone: expected null or exactly {sorted(keys)} (v2.2, 2026-10-09: "
                          f"the zone pair is two MLS marker codes, not RFID tags)")
    laid = list(vehicle.MLS_MARKER_CODES)
    codes = {}
    for key in ("outer_code", "inner_code"):
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigError(f"high_zone.{key}: expected an integer marker code, got {v!r}")
        if v not in laid:
            raise ConfigError(f"high_zone.{key}: code {v} is not laid on the floor "
                              f"(mls.marker_codes {laid}); the zone would never be entered")
        codes[key] = v
    if codes["outer_code"] == codes["inner_code"]:
        raise ConfigError("high_zone: outer_code and inner_code must differ - the read ORDER "
                          "tells entering from leaving")
    spacing = _bounded(raw, "pair_spacing_m", "high_zone", 0.3, 1.0, lo_open=False)
    return {"inner": codes["inner_code"], "outer": codes["outer_code"],
            "spacing_m": spacing, "arm_m": spacing + ZONE_ARM_TOLERANCE_M}


def _parse_mission(doc, vehicle):
    if not isinstance(doc, dict):
        raise ConfigError("mission must be a JSON object")
    v1 = sorted(set(doc) & set(_V1_KEYS))
    if v1:
        raise ConfigError(f"mission: {v1} are the retired v1 route schema (2026-10-08); "
                          f"write the site's tag reference as the 'tags' table")
    unknown = set(doc) - set(_MISSION_KEYS) - set(_OPTIONAL_MISSION_KEYS)
    if unknown:
        raise ConfigError(f"mission: unknown key(s) {sorted(unknown)}")
    missing = set(_MISSION_KEYS) - set(doc)
    if missing:
        raise ConfigError(f"mission: missing key(s) {sorted(missing)}")

    out = {"MISSION_NAME": _coerce(doc["mission_name"], str, "mission_name")}
    default = _coerce(doc["branch_default"], str, "branch_default")
    if default not in ("straight", "left", "right"):
        raise ConfigError(f"branch_default ({default!r}) must be straight, left or right")
    out["BRANCH_DEFAULT"] = default
    out["BRANCH_LATCH"] = _read_branch_latch(doc["branch_latch"], vehicle.RFID_TAG_LEN,
                                             {t.upper() for t in vehicle.RFID_IGNORE_TAGS})
    branch_tags = {r[k] for r in out["BRANCH_LATCH"] for k in ("entry_tag", "exit_tag")}
    out["TAGS"] = _read_tags(doc["tags"], vehicle, branch_tags)
    out["HIGH_ZONE"] = _read_high_zone(doc["high_zone"], vehicle)
    fastest = vehicle.AUTO_HIGH_RPM if out["HIGH_ZONE"] else vehicle.AUTO_RPM
    out["HOME"] = _check_table(out["TAGS"], vehicle, float(fastest))
    out["DESTINATIONS"] = [r["label"] for r in out["TAGS"].values()
                           if r["action"] == "stop" and r["role"] == "destination"]
    out["MARKER_RUN"] = _read_marker_run(doc.get("marker_run"), vehicle, float(fastest))
    if out["MARKER_RUN"] is not None:
        mr, z = out["MARKER_RUN"], out["HIGH_ZONE"]
        shared = {mr["uturn_code"], mr["home_code"]} & ({z["outer"], z["inner"]} if z else set())
        if shared:
            raise ConfigError(f"marker_run with a high_zone on code(s) {sorted(shared)}: the speed zone's "
                              f"codes and the marker run's would mean two things")
        if out["TAGS"] or out["BRANCH_LATCH"]:
            raise ConfigError("marker_run with RFID tag or branch rows: a marker run has no RFID; "
                              "two triggers for one U-turn or home stop would race")
    # Missed-tag backstop (unified plan WP-A7): the most wheel travel between two reads of a
    # tag in this table before the run holds (rfid_overdue). Absent/null = off, so a mission
    # written before the key stays valid until the site's tag spacing is measured.
    gap = doc.get("max_tag_gap_m")
    if gap is not None:
        if not out["TAGS"]:
            raise ConfigError("max_tag_gap_m on a mission without tag rows: there is no tag to miss")
        gap = _bounded(doc, "max_tag_gap_m", "mission", 0.0, 500.0)
    out["MAX_TAG_GAP_M"] = gap
    out["GUIDED"] = _read_guided(doc.get("guided"), vehicle)
    if out["GUIDED"] is not None:
        if out["BRANCH_LATCH"]:
            raise ConfigError("guided with branch_latch rows: the engineer gives the branch orders; "
                              "RFID orders as well would race")
    return out


def destinations(m):
    """The destination labels of a parsed mission (or None), in table order."""
    return list(m["DESTINATIONS"]) if m else []


_BRANCH_NOTE = {"left": "always branch left", "right": "always branch right",
                "straight": "straight through branches"}


def summary(m):
    """The mission picker's note for a parsed mission: its branch rule and its speed rule."""
    branch = _BRANCH_NOTE[m["BRANCH_DEFAULT"]]
    if m["BRANCH_LATCH"]:
        branch += f" (+{len(m['BRANCH_LATCH'])} tag orders)"
    z = m["HIGH_ZONE"]
    parts = [branch, f"HIGH zones (markers {z['outer']}→{z['inner']})" if z else "normal speed"]
    if m.get("GUIDED") is not None:
        parts[0] = "branches by hand"
        parts[1] = f"≤ {m['GUIDED']['cruise_mps']:g} m/s"
        if z:
            parts[1] += f", HIGH zones by toggle (markers {z['outer']}→{z['inner']})"
    if m["MARKER_RUN"] is not None:
        parts.append("marker run")
    elif m["DESTINATIONS"]:
        parts.append(f"{len(m['DESTINATIONS'])} destinations")
    return " · ".join(parts)


def list_missions(directory=None):
    """Mission names on disk, sorted. "empty" is always offered."""
    d = directory or MISSION_DIR
    try:
        names = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
    except OSError:
        names = set()
    # Site missions (schema site-3) are not tag-table jobs: listed by list_site_missions().
    names -= set(list_site_missions(d))
    return sorted(names | {"empty"})


EMPTY = {
    "mission_name": "empty",
    "branch_default": "straight",
    "branch_latch": [],
    "high_zone": None,
    "tags": [],
}


def _as_mission_error(parser, doc, vehicle):
    """Run a parser, a ConfigError from a shared reader surfacing as a MissionError."""
    if vehicle is None:
        from agv_core import config as vehicle  # noqa: PLC0415
    try:
        return parser(doc, vehicle)
    except MissionError:
        raise
    except ConfigError as e:
        raise MissionError(str(e)) from None


def parse(doc, vehicle=None):
    """A mission document -> the validated names. MissionError on any problem."""
    return _as_mission_error(_parse_mission, doc, vehicle)


def load(name, vehicle=None, directory=None):
    """missions/<name>.json -> validated names. "empty" needs no file."""
    if name == "empty" and not os.path.exists(_path(name, directory)):
        doc = EMPTY
    else:
        doc = _read_doc(name, directory, have=lambda: list_missions(directory))
    if is_site(doc):
        raise MissionError(f"{name!r} is a site mission (tracked plan 3): it runs on tape-graph "
                           f"localization, not as an RFID tag-table job")
    return _named(parse(doc, vehicle), name)


# -- site missions (schema "site-4", tracked plans 3 section 2.5 and 4 section 2.2) -----
#
# A site mission is designed data: groups of machines, circuits with every junction
# order written out, and what happens at each stop. WHERE things are (legs, stations)
# is taught on the vehicle into the tape graph (amr_line.tape_graph), bound to a map
# revision; the two meet in tape_graph.compile_route, which names anything not taught.
#
#   schema            "site-4" (site-3 + cruise_mps, uturn_points; 2026-10-24)
#   mission_name      the file name
#   home, attach      station ids: the bay where the AGV parks empty, the attach stop
#   trip_calls        calls of one group that form a trip (site D3/D4/D18: 1 or 2)
#   stop_distance_m   braking distance into every station
#   cruise_mps        a trip's speed outside the high-speed zones (at most NORMAL)
#   junctions         {id: {"shape": "Y"|"T"|"X", "laid": bool}}. An unlaid junction is
#                     not a node: the legs run through it until it is laid and re-taught
#   uturns            {id: {"direction": "cw"|"ccw", "approach_mps", "decel_m",
#                     "max_approach_m", "lead_m"}}: a tape-end pivot, empty only
#   circuits          {id: [item, ...]}, items in travel order:
#                       {"stop": id} | {"junction": id, "order": o} | {"uturn": id}
#                     o: left | right | straight | merge (Y), cross (X). A T item also says
#                     "approach": "stem" (left | right only: no straight on) or "bar" (as a Y).
#                     A merge may add "steer": left | right - the side armed before it, like
#                     an order; the leg keeps its "merge" name (2026-10-25: MRU inbound, always
#                     left until HOME)
#                     A circuit starts and ends with {"stop": home} and passes attach once
#   groups            {name: {"circuit": id, "machines": {machine: {"swap": stop} |
#                     {"release": stop, "take": stop[, "uturn": point]}}}}. "uturn": where a
#                     trip turns mid-line when this machine is its farthest release (site D16);
#                     without it, at the circuit's tape-end U-turn
#   uturn_points      {id: {"direction": "cw"|"ccw"}}: mid-line U-turn points, each the
#                     "uturn" of exactly one machine; taught on that machine's release leg
#
# High-speed zones are not mission data (2026-10-25): they are AREAS drawn on the map
# revision (amr_line.tape_graph_store areas.json, the /tape-areas page), cut into ranges along
# a trip when it is compiled (amr_line.trip_route). A "zones" key is refused by name.
#
# Parsed names: MISSION_NAME, SCHEMA, HOME, ATTACH, TRIP_CALLS, STOP_DISTANCE_M, CRUISE_MPS,
# JUNCTIONS, UTURNS, CIRCUITS {id: {"items", "legs", "home_depart", "home_arrive"}}, GROUPS,
# MACHINES {machine: group}, STATIONS {station: leg id}, UTURN_POINTS {id: {"direction",
# "machine", "leg"}}, POINTS {point: leg id}. Positions (a point after its release) are
# vehicle data: amr_line.trip_route checks them when a trip is compiled.

SITE_SCHEMA = "site-4"
_SITE_KEYS = ("schema", "mission_name", "home", "attach", "trip_calls", "stop_distance_m", "cruise_mps",
              "junctions", "uturns", "circuits", "groups", "uturn_points")
SHAPES = ("Y", "T", "X")
_ORDERS = {"Y": ("left", "right", "straight", "merge"), "X": ("cross",),
           # A T from its stem has no straight on; along its bar it is a Y.
           "T-stem": ("left", "right"), "T-bar": ("left", "right", "straight", "merge")}
_UTURN_KEYS = {"direction", "approach_mps", "decel_m", "max_approach_m", "lead_m"}


def is_site(doc):
    """A site mission of any schema generation (a site-3 file is refused by parse_site, by name)."""
    return isinstance(doc, dict) and doc.get("schema") in (SITE_SCHEMA, "site-3")


def _ident(v, where):
    if not isinstance(v, str) or not v.strip() or v != v.strip() or any(c in v for c in ":>/ "):
        raise ConfigError(f"{where}: expected an id without spaces, ':', '>' or '/', got {v!r}")
    return v


def _site_uturn(name, row, vehicle):
    where = f"uturns.{name}"
    if not isinstance(row, dict) or set(row) != _UTURN_KEYS:
        raise ConfigError(f"{where}: expected exactly {sorted(_UTURN_KEYS)}")
    if row["direction"] not in ("cw", "ccw"):
        raise ConfigError(f"{where}.direction must be cw or ccw")
    out = {"direction": row["direction"]}
    approach, rate, decel = _uturn_approach(row, where, vehicle)
    out.update(approach)
    out["lead_m"] = _bounded(row, "lead_m", where, 0.0, 10.0)
    if out["lead_m"] < out["decel_m"]:
        raise ConfigError(f"{where}.lead_m ({out['lead_m']:g}) must cover decel_m ({out['decel_m']:g}): "
                          f"the approach starts lead_m before the taught tape end")
    if rate > decel:
        raise ConfigError(f"{where}.decel_m: {rate:.0f} r/min/s is beyond drivers.ramp.auto.decel")
    return out


def _site_items(cid, raw, junctions, uturns):
    if not isinstance(raw, list) or len(raw) < 3:
        raise ConfigError(f"circuits.{cid}: expected a list of at least three items")
    items = []
    for i, it in enumerate(raw):
        where = f"circuits.{cid}[{i}]"
        if not isinstance(it, dict):
            raise ConfigError(f"{where}: expected an object")
        if set(it) == {"stop"}:
            items.append({"kind": "stop", "id": _ident(it["stop"], f"{where}.stop")})
        elif set(it) == {"uturn"}:
            if it["uturn"] not in uturns:
                raise ConfigError(f"{where}: U-turn {it['uturn']!r} is not in uturns")
            items.append({"kind": "uturn", "id": it["uturn"], "order": "pivot"})
        elif "junction" in it:
            if "order" not in it:
                raise ConfigError(f"{where}: junction {it['junction']!r} without an order - every "
                                  f"junction on a circuit says what to do there")
            j = junctions.get(it["junction"])
            if j is None:
                raise ConfigError(f"{where}: junction {it['junction']!r} is not in junctions")
            keys = {"junction", "order"} | ({"approach"} if j["shape"] == "T" else set())
            if "steer" in it:
                if it.get("order") != "merge":
                    raise ConfigError(f"{where}: steer only on a merge - a diverge says its side in "
                                      f"its order")
                if it["steer"] not in ("left", "right"):
                    raise ConfigError(f"{where}.steer: expected left or right, got {it['steer']!r}")
                keys = keys | {"steer"}
            if set(it) != keys:
                raise ConfigError(f"{where}: expected exactly {sorted(keys)} at {it['junction']} "
                                  f"(shape {j['shape']}" + ("; approach is stem or bar)" if j["shape"] == "T"
                                                           else ")"))
            shape = j["shape"]
            if shape == "T":
                if it["approach"] not in ("stem", "bar"):
                    raise ConfigError(f"{where}.approach: expected stem or bar, got {it['approach']!r}")
                shape = f"T-{it['approach']}"
            allowed = _ORDERS[shape]
            if it["order"] not in allowed:
                raise ConfigError(f"{where}: order {it['order']!r} at {it['junction']} ({shape}): "
                                  f"expected one of {list(allowed)}"
                                  + (" - a T has no straight on from its stem" if shape == "T-stem" else ""))
            items.append({"kind": "junction", "id": it["junction"], "order": it["order"],
                          **({"steer": it["steer"]} if "steer" in it else {})})
        else:
            raise ConfigError(f"{where}: expected {{'stop'}}, {{'uturn'}} or {{'junction', 'order'}}")
    return items


def leg_id(frm, order, to):
    """A tape leg's id: from node, the order taken there, to node ("J1:left>J2"). Persisted."""
    return f"{frm}:{order}>{to}"


def _site_legs(cid, items, junctions, home):
    """Items -> (legs with the home leg LAST, the home-leg stops of the departure, those
    of the arrival)."""
    nodes = [k for k, it in enumerate(items)
             if it["kind"] == "uturn" or (it["kind"] == "junction" and junctions[it["id"]]["laid"])]
    if not nodes:
        raise ConfigError(f"circuits.{cid}: no laid junction or U-turn - nothing to split the tape at")
    legs = []
    for a, b in zip(nodes, nodes[1:], strict=False):
        frm, to = items[a], items[b]
        legs.append({"id": leg_id(frm["id"], frm["order"], to["id"]), "from": frm["id"],
                     "order": frm["order"], "to": to["id"],
                     "stops": [it["id"] for it in items[a + 1:b] if it["kind"] == "stop"]})
    last, first = items[nodes[-1]], items[nodes[0]]
    before = [it["id"] for it in items[:nodes[0]] if it["kind"] == "stop"]
    after = [it["id"] for it in items[nodes[-1] + 1:] if it["kind"] == "stop"]
    legs.append({"id": leg_id(last["id"], last["order"], first["id"]), "from": last["id"],
                 "order": last["order"], "to": first["id"], "stops": after + before})
    # The home leg is driven twice (out of the bay, back into it): `after` then `before`
    # in tape order, but `before` is the trip's start.
    return legs, before, after


def _parse_site(doc, vehicle):
    if not isinstance(doc, dict):
        raise ConfigError("mission must be a JSON object")
    if "zones" in doc:
        raise ConfigError("zones: retired 2026-10-25 - high-speed zones are areas drawn on the map "
                          "(/tape-areas), not mission data")
    unknown = set(doc) - set(_SITE_KEYS)
    if unknown:
        raise ConfigError(f"site mission: unknown key(s) {sorted(unknown)}")
    missing = set(_SITE_KEYS) - set(doc)
    if missing:
        raise ConfigError(f"site mission: missing key(s) {sorted(missing)}")
    out = {"SCHEMA": SITE_SCHEMA, "MISSION_NAME": _coerce(doc["mission_name"], str, "mission_name")}
    home, attach = _ident(doc["home"], "home"), _ident(doc["attach"], "attach")
    if home == attach:
        raise ConfigError("home and attach must be different stations")
    out["HOME"], out["ATTACH"] = home, attach
    calls = doc["trip_calls"]
    if isinstance(calls, bool) or not isinstance(calls, int) or not 1 <= calls <= 2:
        raise ConfigError(f"trip_calls: expected 1 or 2 (site D3: at most two machines a trip), "
                          f"got {calls!r}")
    out["TRIP_CALLS"] = calls
    out["STOP_DISTANCE_M"] = _bounded(doc, "stop_distance_m", "site mission", 0.0, 5.0)
    normal_mps = vehicle.AUTO_RPM * vehicle.MPS_PER_RPM
    out["CRUISE_MPS"] = _bounded(doc, "cruise_mps", "site mission", 0.0, round(normal_mps, 3))
    rate, decel = _decel_needed(vehicle, vehicle.AUTO_RPM, out["STOP_DISTANCE_M"])
    if rate > decel:
        raise ConfigError(f"stop_distance_m: stopping from {vehicle.AUTO_RPM:.0f} r/min in "
                          f"{out['STOP_DISTANCE_M']:g} m needs {rate:.0f} r/min/s, "
                          f"beyond drivers.ramp.auto.decel")

    if not isinstance(doc["junctions"], dict):
        raise ConfigError("junctions: expected an object")
    junctions = {}
    for jid, row in doc["junctions"].items():
        _ident(jid, f"junctions.{jid}")
        if not isinstance(row, dict) or set(row) != {"shape", "laid"}:
            raise ConfigError(f"junctions.{jid}: expected exactly ['laid', 'shape']")
        if row["shape"] not in SHAPES:
            raise ConfigError(f"junctions.{jid}.shape: expected one of {list(SHAPES)}, got {row['shape']!r}")
        junctions[jid] = {"shape": row["shape"], "laid": _coerce(row["laid"], bool, f"junctions.{jid}.laid")}
    if not isinstance(doc["uturns"], dict):
        raise ConfigError("uturns: expected an object")
    uturns = {_ident(k, f"uturns.{k}"): _site_uturn(k, v, vehicle) for k, v in doc["uturns"].items()}
    clash = set(junctions) & set(uturns)
    if clash:
        raise ConfigError(f"{sorted(clash)} are both junctions and U-turns")
    out["JUNCTIONS"], out["UTURNS"] = junctions, uturns

    if not isinstance(doc["circuits"], dict) or not doc["circuits"]:
        raise ConfigError("circuits: expected a non-empty object")
    circuits, stations = {}, {}
    for cid, raw in doc["circuits"].items():
        _ident(cid, f"circuits.{cid}")
        items = _site_items(cid, raw, junctions, uturns)
        stops = [it["id"] for it in items if it["kind"] == "stop"]
        if items[0] != {"kind": "stop", "id": home} or items[-1] != {"kind": "stop", "id": home}:
            raise ConfigError(f"circuits.{cid}: must start and end with {{'stop': '{home}'}}")
        if stops.count(home) != 2:
            raise ConfigError(f"circuits.{cid}: {home} only at the start and the end")
        if stops.count(attach) != 1:
            raise ConfigError(f"circuits.{cid}: passes {attach} {stops.count(attach)} times, expected once")
        inner = stops[1:-1]
        dup = sorted({s for s in inner if inner.count(s) > 1})
        if dup:
            raise ConfigError(f"circuits.{cid}: stop(s) {dup} twice - one station is one place on one pass")
        if stops.index(attach) != 1:
            raise ConfigError(f"circuits.{cid}: {attach} must be the first stop after {home} "
                              f"(trolleys attach before any machine)")
        turns = [it["id"] for it in items if it["kind"] == "uturn"]
        if len(set(turns)) != len(turns):
            raise ConfigError(f"circuits.{cid}: a U-turn twice")
        legs, before, after = _site_legs(cid, items, junctions, home)
        for leg in legs:
            for sid in leg["stops"]:
                if sid in stations and stations[sid] != leg["id"]:
                    raise ConfigError(f"circuits.{cid}: station {sid} lies on {leg['id']} here and on "
                                      f"{stations[sid]} in another circuit - one station, one place")
                stations[sid] = leg["id"]
        steers = {f"{it['id']}:{it['order']}": it["steer"] for it in items if it.get("steer")}
        circuits[cid] = {"items": items, "legs": legs, "home_depart": before, "home_arrive": after,
                         "steers": steers}
    out["CIRCUITS"] = circuits
    out["STATIONS"] = stations
    uturn_points = _site_points(doc, junctions, uturns, stations)

    if not isinstance(doc["groups"], dict) or not doc["groups"]:
        raise ConfigError("groups: expected a non-empty object")
    groups, machines = {}, {}
    for name, g in doc["groups"].items():
        where = f"groups.{name}"
        _ident(name, where)
        if not isinstance(g, dict) or set(g) != {"circuit", "machines"}:
            raise ConfigError(f"{where}: expected exactly ['circuit', 'machines']")
        cid = g["circuit"]
        if cid not in circuits:
            raise ConfigError(f"{where}.circuit: {cid!r} is not in circuits")
        items = circuits[cid]["items"]
        pos = {it["id"]: k for k, it in enumerate(items) if it["kind"] == "stop"}
        pos[home] = 0
        turn_at = [k for k, it in enumerate(items) if it["kind"] == "uturn"]
        if not isinstance(g["machines"], dict) or not g["machines"]:
            raise ConfigError(f"{where}.machines: expected a non-empty object")
        rows = {}
        for m, act in g["machines"].items():
            mw = f"{where}.machines.{m}"
            _ident(m, mw)
            if m in machines:
                raise ConfigError(f"{mw}: machine {m} is already in group {machines[m]} - a machine "
                                  f"belongs to one group")
            if not isinstance(act, dict) or set(act) not in ({"swap"}, {"release", "take"},
                                                            {"release", "take", "uturn"}):
                raise ConfigError(f"{mw}: expected {{'swap': stop}} or {{'release': stop, 'take': stop}} "
                                  f"(and optionally 'uturn': a uturn_points id)")
            act = dict(act)
            point = act.pop("uturn", None)
            if point is not None:
                if point not in uturn_points:
                    raise ConfigError(f"{mw}.uturn: {point!r} is not in uturn_points")
                if uturn_points[point]["machine"]:
                    raise ConfigError(f"{mw}.uturn: {point} is already {uturn_points[point]['machine']}'s "
                                      f"U-turn point - one point, one machine")
                uturn_points[point].update(machine=m, leg=stations[act["release"]]
                                           if act["release"] in stations else None)
            for kind, sid in act.items():
                if sid in (home, attach) or sid not in pos:
                    raise ConfigError(f"{mw}.{kind}: stop {sid!r} is not a machine stop on {cid}")
            if "release" in act:
                if not turn_at:
                    raise ConfigError(f"{mw}: release/take needs a U-turn on {cid} between them")
                r, t = pos[act["release"]], pos[act["take"]]
                if not r < turn_at[0] < t:
                    raise ConfigError(f"{mw}: the release ({act['release']}) must come before the U-turn and "
                                      f"the take-back ({act['take']}) after it - the AGV never pivots "
                                      f"with a trolley attached")
            if point is not None:
                act["uturn"] = point
            rows[m] = act
            machines[m] = name
        groups[name] = {"circuit": cid, "machines": rows}
    out["GROUPS"], out["MACHINES"] = groups, machines
    unused = sorted(k for k, v in uturn_points.items() if not v["machine"])
    if unused:
        raise ConfigError(f"uturn_points {unused}: no machine's uturn - a U-turn point belongs to "
                          f"the machine after whose release the trip turns")
    out["UTURN_POINTS"] = uturn_points
    out["POINTS"] = {k: v["leg"] for k, v in uturn_points.items()}
    return out


def _site_points(doc, junctions, uturns, stations):
    """uturn_points: named here, placed by teaching (tracked plan 4 section 2.2)."""
    taken = set(junctions) | set(uturns) | set(stations)
    if not isinstance(doc["uturn_points"], dict):
        raise ConfigError("uturn_points: expected an object")
    points = {}
    for k, row in doc["uturn_points"].items():
        where = f"uturn_points.{k}"
        _ident(k, where)
        if k in taken:
            raise ConfigError(f"{where}: {k} is already a station, junction or tape-end U-turn")
        if not isinstance(row, dict) or set(row) != {"direction"}:
            raise ConfigError(f"{where}: expected exactly ['direction']")
        if row["direction"] not in ("cw", "ccw"):
            raise ConfigError(f"{where}.direction must be cw or ccw")
        points[k] = {"direction": row["direction"], "machine": "", "leg": None}
    return points


def parse_site(doc, vehicle=None):
    """A site mission document -> the validated names. MissionError on any problem."""
    if not is_site(doc):
        raise MissionError(f"not a site mission (schema must be {SITE_SCHEMA!r})")
    if doc.get("schema") != SITE_SCHEMA:
        raise MissionError(f"schema {doc.get('schema')!r} is retired: {SITE_SCHEMA} adds cruise_mps "
                           f"and uturn_points (tracked plan 4 section 2.2)")
    return _as_mission_error(_parse_site, doc, vehicle)


def _path(name, directory=None):
    """missions/<name>.json, refusing anything that is not a plain name."""
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        raise MissionError(f"not a mission name: {name!r}")
    return os.path.join(directory or MISSION_DIR, f"{name}.json")


def _read_doc(name, directory=None, have=None):
    """The JSON of missions/<name>.json. `have()` lists the alternatives for a missing
    file; it is only called on that error path."""
    path = _path(name, directory)
    try:
        with open(path) as f:
            return json.load(f)
    except OSError:
        raise MissionError(f"no mission {name!r} ({path})" + (f"; have {have()}" if have else "")) from None
    except ValueError as e:
        raise MissionError(f"mission {name!r}: not valid JSON ({e})") from None


def _named(out, name):
    if out["MISSION_NAME"] != name:
        raise MissionError(f"mission_name {out['MISSION_NAME']!r} does not match the file name {name!r}")
    return out


def load_site(name, vehicle=None, directory=None):
    """missions/<name>.json as a site mission."""
    return _named(parse_site(_read_doc(name, directory), vehicle), name)


def list_site_missions(directory=None):
    d = directory or MISSION_DIR
    out = []
    try:
        names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            if is_site(_read_doc(n, d)):
                out.append(n)
        except MissionError:
            continue
    return out
