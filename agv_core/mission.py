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
    zone_outer    v2.1 (2026-10-08, tracked-speed-plan-1): the outer tag of a high-
    zone_inner    zone pair at a straight's end. Outer then inner = entering the
                  straight: HIGH for the mission's budget. Inner while HIGH =
                  leaving. Shared ids: one outer and one inner id for every pair
                  (amr_line.speed_zone). The v2 speed_toggle is refused.

    ignore_s      after a read is ACTED ON, the same tag is ignored this long.
                  A stop's window restarts at departure, since a parked vehicle
                  outlasts any window. Zone tags allow at most 2 s: one corner
                  reads the outer id twice, >= 1.8 m apart (3.6 s at NORMAL).

high_zone (v2.1): null (the run stays at NORMAL) or
    {"shortest_straight_m": surveyed inner tag to inner tag, "pair_spacing_m": 0.5}
from which the one HIGH budget for every straight is derived:
    high_for_m = shortest_straight_m - brake_m - autopilot.high_margin_m
    brake_m    = (v_high + v_normal) / 2 x autopilot.high_ramp_s

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

MISSION_NAME, BRANCH_DEFAULT, BRANCH_LATCH, TAGS {tag: row}, HOME (row | None),
DESTINATIONS (labels), HIGH_ZONE ({"inner", "outer", "high_for_m", "arm_m",
"spacing_m", "brake_m"} | None).

Free of ROS; the line layer and the web both read it.
"""
import json
import os

from agv_core.config import ConfigError, _coerce

MISSION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "missions")

ACTIONS = ("stop", "u_turn", "zone_inner", "zone_outer")
ZONE_ACTIONS = ("zone_inner", "zone_outer")
# 1 -> 2 s (2026-10-08, more leniency for cluster re-reads): through the tightest corner
# the outer id is read twice >= 1.8 m apart, 3.6 s at NORMAL - still outside 2 s.
ZONE_MAX_IGNORE_S = 2.0
# The outer tag waits this far beyond the pair spacing for its inner tag. 0.2 -> 0.7
# (field run 2026-10-08): with 4-tag clusters 0.5 m apart, the reader's FIRST reads were
# 0.65 and 0.99 m apart (weak reads, -69..-74 dBm, land anywhere in the read zone). Wider
# is safe: only outer -> inner grants HIGH, inner -> outer never arms, an expired arm is
# NORMAL. It must stay below the exit-outer -> entry-outer distance through a corner.
ZONE_ARM_TOLERANCE_M = 1.0  # 0.7 -> 1.0 the same day: slightly more leniency
# A budget shorter than this is not worth the two ramps.
ZONE_MIN_BUDGET_M = 3.0
ROLES = ("home", "always", "destination")

# Keys per action, beyond the common tag/action/ignore_s. "label" is optional on
# u_turn and speed_toggle rows, required on stops (the operator picks by it).
_KEYS = {
    "stop": {"stop_distance_m", "role", "label"},
    "u_turn": {"direction", "approach_mps", "decel_m", "max_approach_m"},
    "zone_inner": set(),
    "zone_outer": set(),
}
_COMMON = {"tag", "action", "ignore_s"}
_OPTIONAL = {"stop": set(), "u_turn": {"label"}, "zone_inner": {"label"}, "zone_outer": {"label"}}

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

    slow_speed is OPTIONAL and defaults to false. It is still type-checked: the
    string "True" is refused, not silently accepted as truthy.
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
                              f"carried HIGH into a corner. Use a zone_outer/zone_inner pair "
                              f"and the mission's high_zone block")
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
        elif action == "u_turn":
            if row["direction"] not in ("cw", "ccw"):
                raise ConfigError(f"{where}.direction must be cw or ccw")
            rec["direction"] = row["direction"]
            normal_mps = vehicle.AUTO_RPM * vehicle.MPS_PER_RPM
            rec["approach_mps"] = _bounded(row, "approach_mps", where, 0.0, round(normal_mps, 3))
            rec["max_approach_m"] = _bounded(row, "max_approach_m", where, 0.0, 5.0)
            rec["decel_m"] = _bounded(row, "decel_m", where, 0.0, 2.0)
            # NORMAL -> approach_mps over decel_m within the drives' deceleration. The
            # tag belongs in a NORMAL area; arriving HIGH, the rate is capped at runtime
            # and the slowdown takes longer than decel_m.
            creep_rpm = rec["approach_mps"] / vehicle.MPS_PER_RPM
            rate = (vehicle.AUTO_RPM ** 2 - creep_rpm ** 2) * vehicle.MPS_PER_RPM / (2.0 * rec["decel_m"])
            decel = float(vehicle.RAMP["auto"]["decel"])
            if rate > decel:
                raise ConfigError(f"{where}.decel_m: slowing from {vehicle.AUTO_RPM:.0f} r/min to "
                                  f"{rec['approach_mps']:g} m/s in {rec['decel_m']:g} m needs {rate:.0f} "
                                  f"r/min/s, beyond drivers.ramp.auto.decel {decel:.0f}")
        elif rec["ignore_s"] > ZONE_MAX_IGNORE_S:
            raise ConfigError(f"{where}.ignore_s must be <= {ZONE_MAX_IGNORE_S:g} s for a zone tag: "
                              f"one corner reads the outer id twice >= 1.8 m apart, and a longer "
                              f"window swallows the entry of the next straight")
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
    decel = float(vehicle.RAMP["auto"]["decel"])
    for r in tags.values():
        if r["action"] != "stop":
            continue
        rate = fastest_rpm ** 2 * vehicle.MPS_PER_RPM / (2.0 * r["stop_distance_m"])
        if rate > decel:
            raise ConfigError(f"tags ({r['tag']}): stopping from {fastest_rpm:.0f} r/min in "
                              f"{r['stop_distance_m']:g} m needs {rate:.0f} r/min/s, beyond "
                              f"drivers.ramp.auto.decel {decel:.0f}; commission a longer stop_distance_m")
    return homes[0] if homes else None


_MISSION_KEYS = ("mission_name", "branch_default", "branch_latch", "high_zone", "tags")


def _read_high_zone(raw, tags, vehicle):
    """high_zone + the zone rows -> the one budget every straight shares, or None."""
    inner = [t for t, r in tags.items() if r["action"] == "zone_inner"]
    outer = [t for t, r in tags.items() if r["action"] == "zone_outer"]
    if raw is None:
        if inner or outer:
            raise ConfigError("tags: zone rows need the high_zone block (shortest_straight_m, "
                              "pair_spacing_m); survey the shortest HIGH straight first")
        return None
    keys = {"shortest_straight_m", "pair_spacing_m"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ConfigError(f"high_zone: expected null or exactly {sorted(keys)}")
    if len(inner) != 1 or len(outer) != 1:
        raise ConfigError(f"high_zone: needs exactly one zone_inner and one zone_outer tag "
                          f"(shared by every pair), got {len(inner)} and {len(outer)}")
    spacing = _bounded(raw, "pair_spacing_m", "high_zone", 0.3, 1.0, lo_open=False)
    shortest = _bounded(raw, "shortest_straight_m", "high_zone", 0.0, 500.0)
    v_normal = vehicle.AUTO_RPM * vehicle.MPS_PER_RPM
    v_high = vehicle.AUTO_HIGH_RPM * vehicle.MPS_PER_RPM
    brake = (v_high + v_normal) / 2.0 * vehicle.HIGH_RAMP_S
    budget = shortest - brake - vehicle.HIGH_MARGIN_M
    if budget < ZONE_MIN_BUDGET_M:
        raise ConfigError(f"high_zone: {shortest:g} m straight leaves a {budget:.2f} m HIGH budget "
                          f"after {brake:.2f} m braking and {vehicle.HIGH_MARGIN_M:g} m margin "
                          f"(< {ZONE_MIN_BUDGET_M:g} m: not worth it)")
    return {"inner": inner[0], "outer": outer[0], "high_for_m": budget, "brake_m": brake,
            "spacing_m": spacing, "arm_m": spacing + ZONE_ARM_TOLERANCE_M}


def _parse_mission(doc, vehicle):
    if not isinstance(doc, dict):
        raise ConfigError("mission must be a JSON object")
    v1 = sorted(set(doc) & set(_V1_KEYS))
    if v1:
        raise ConfigError(f"mission: {v1} are the retired v1 route schema (2026-10-08); "
                          f"write the site's tag reference as the 'tags' table")
    unknown = set(doc) - set(_MISSION_KEYS)
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
    out["HIGH_ZONE"] = _read_high_zone(doc["high_zone"], out["TAGS"], vehicle)
    fastest = vehicle.AUTO_HIGH_RPM if out["HIGH_ZONE"] else vehicle.AUTO_RPM
    out["HOME"] = _check_table(out["TAGS"], vehicle, float(fastest))
    out["DESTINATIONS"] = [r["label"] for r in out["TAGS"].values()
                           if r["action"] == "stop" and r["role"] == "destination"]
    return out


def destinations(m):
    """The destination labels of a parsed mission (or None), in table order."""
    return list(m["DESTINATIONS"]) if m else []


def list_missions(directory=None):
    """Mission names on disk, sorted. "empty" is always offered."""
    d = directory or MISSION_DIR
    try:
        names = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
    except OSError:
        names = set()
    return sorted(names | {"empty"})


EMPTY = {
    "mission_name": "empty",
    "branch_default": "straight",
    "branch_latch": [],
    "high_zone": None,
    "tags": [],
}


def parse(doc, vehicle=None):
    """A mission document -> the validated names. MissionError on any problem."""
    if vehicle is None:
        from agv_core import config as vehicle  # noqa: PLC0415
    try:
        return _parse_mission(doc, vehicle)
    except MissionError:
        raise
    except ConfigError as e:
        raise MissionError(str(e)) from None


def load(name, vehicle=None, directory=None):
    """missions/<name>.json -> validated names. "empty" needs no file."""
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        raise MissionError(f"not a mission name: {name!r}")
    path = os.path.join(directory or MISSION_DIR, f"{name}.json")
    if name == "empty" and not os.path.exists(path):
        doc = EMPTY
    else:
        try:
            with open(path) as f:
                doc = json.load(f)
        except OSError:
            raise MissionError(f"no mission {name!r} ({path}); have {list_missions(directory)}") from None
        except ValueError as e:
            raise MissionError(f"mission {name!r}: not valid JSON ({e})") from None
    out = parse(doc, vehicle)
    if out["MISSION_NAME"] != name:
        raise MissionError(f"mission_name {out['MISSION_NAME']!r} does not match the file name {name!r}")
    return out
