"""Tape-AGV missions: missions/<name>.json, validated against the vehicle profile.

Ported 2026-10-02 from gy-demo's config.py, where the mission document was the
SITE half of the profile (branch_latch, stop_until_start_button,
high_speed_mode, route, route_guard, u_turn, branch_default, site speeds). The
validators below are COPIED, not re-derived - the tag-namespace disjointness
and hex-string-not-number rules are the reason this table cannot fail silently -
with one signature change: they read the vehicle from a passed `vehicle`
(agv_core.config by default) instead of a namespace being built.

    list_missions()          -> ["empty", "gy-demo", ...]
    load(name, vehicle=None) -> dict of the names below, or MissionError

MISSION_NAME, AUTO_RPM_HIGH, SPEED_SWITCH_S, SPEED_SWITCH_RPM_S, BRANCH_DEFAULT,
BRANCH_LATCH, STOP_TAGS {(direction, tag): rule}, STOP_TAGS_ANY {tag: rule}
(route-less only), ROUTE, HIGH_SPEED_MODE, ROUTE_GUARD, U_TURN_TAGS {tag: cw|ccw}.

"empty" (or no mission at all) is plain line following: no stations, no zones.
Free of ROS; the line layer and the web both read it.
"""
import json
import math
import os

from agv_core.config import ConfigError, _coerce

MISSION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "missions")


class MissionError(ConfigError):
    """A mission file that cannot be run as written."""


def _read_branch_latch(rows, tag_len, ignore_tags):
    """branch_latch -> validated rows, or [] when there are no junctions yet.

    An entry tag sets a direction and an exit tag clears it (branch.Ladder).
    Every check here exists to stop a rung being silently DEAD, which is the
    only failure mode this table has: a tag that never matches produces no
    error, no log line and no motion - the AGV simply drives past the junction.

    slow_speed is OPTIONAL and defaults to false, because most junctions do not
    need it and a table of diverters written before the flag existed must keep
    loading. It is the one key here that changes how fast the vehicle arrives at
    the diverter, so it is still type-checked like everything else: the string
    "True" is refused, not silently accepted as truthy.
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

        slow = _coerce(row.get("slow_speed", False), bool,
                       f"{where}.slow_speed")

        side = _coerce(row["branch"], str, f"{where}.branch")
        if side not in ("left", "right"):
            raise ConfigError(f"{where}.branch: expected 'left' or 'right', "
                              f"got {side!r}")

        tags = {}
        for key in ("entry_tag", "exit_tag"):
            raw = row[key]
            # The reader hands tags over as hex text (rfid.tag_of), so a JSON
            # number here can never match one - and would fail silently.
            if not isinstance(raw, str):
                raise ConfigError(
                    f"{where}.{key}: expected a {width}-character hex string "
                    f"like \"000A\", got {raw!r}. Tag ids come from "
                    f"rfid.tag_of() as hex text, so a number never matches.")
            tag = raw.upper()
            if len(tag) != width or any(c not in "0123456789ABCDEF" for c in tag):
                raise ConfigError(f"{where}.{key}: expected {width} hex "
                                  f"characters, got {raw!r}")
            if tag in ignore_tags:
                raise ConfigError(f"{where}.{key}: {tag} is also in "
                                  f"rfid.ignore_tags, so it is discarded before "
                                  f"the ladder can see it")
            tags[key] = tag

        if tags["entry_tag"] == tags["exit_tag"]:
            raise ConfigError(f"{where}: entry_tag and exit_tag are both "
                              f"{tags['entry_tag']} - the same read cannot both "
                              f"set and clear the latch")
        for key, tag in tags.items():
            if tag in seen:
                raise ConfigError(f"{where}.{key}: tag {tag} is already used by "
                                  f"{seen[tag]} - one tag cannot mean two things")
            seen[tag] = f"{where}.{key}"
        out.append({"entry_tag": tags["entry_tag"],
                    "exit_tag": tags["exit_tag"], "branch": side,
                    "slow_speed": slow})
    return out


def _rule_rows(rows, keys, where):
    if not isinstance(rows, list):
        raise ConfigError(f"{where}: expected a list")
    for i, row in enumerate(rows):
        loc = f"{where}[{i}]"
        if not isinstance(row, dict) or set(row) != set(keys):
            raise ConfigError(f"{loc}: expected exactly {sorted(keys)}")
        yield row, loc


def _tag(raw, width, where, forbidden):
    if not isinstance(raw, str) or len(raw) != width or any(
            c not in "0123456789ABCDEF" for c in raw.upper()):
        raise ConfigError(f"{where}: expected {width} hex characters")
    tag = raw.upper()
    if tag in forbidden:
        raise ConfigError(f"{where}: tag {tag} is ignored or assigned to another rule type")
    return tag


def _travel_direction(raw, where):
    if raw not in ("outbound", "inbound"):
        raise ConfigError(f"{where}.direction must be outbound or inbound")
    return raw


def _read_stop_tags(rows, tag_len, ignore_tags, branch_tags):
    """Direction-qualified stop parameters; physical stations live in route."""
    out = {}
    for row, loc in _rule_rows(rows, ("tag", "direction", "stop_distance_m"),
                               "stop_until_start_button"):
        direction = _travel_direction(row["direction"], loc)
        tag = _tag(row["tag"], tag_len * 2, loc, ignore_tags | branch_tags)
        dist = _coerce(row["stop_distance_m"], float, loc + ".stop_distance_m")
        if not 0 < dist <= 5:
            raise ConfigError(f"{loc}.stop_distance_m must be in (0, 5] m")
        key = (direction, tag)
        if key in out:
            raise ConfigError(f"{loc}: duplicate direction/tag stop rule")
        out[key] = {"stop_distance_m": dist}
    return out


def _read_route(rows, speed_rows, stops, tag_len, ignored, branch_tags):
    stations, ids = [], set()
    for row, loc in _rule_rows(rows, ("id", "tag", "direction", "high_speed_to_next"),
                               "route"):
        ident = _coerce(row["id"], str, loc + ".id")
        if not ident.strip() or ident in ids:
            raise ConfigError(f"{loc}.id must be nonempty and unique")
        ids.add(ident)
        direction = _travel_direction(row["direction"], loc)
        tag = _tag(row["tag"], tag_len * 2, loc, ignored | branch_tags)
        if (direction, tag) not in stops:
            raise ConfigError(f"{loc}: no matching direction/tag stop rule")
        high = _coerce(row["high_speed_to_next"], bool, loc + ".high_speed_to_next")
        stations.append(dict(id=ident, tag=tag, direction=direction,
                             high_speed_to_next=high))
    # An empty route is a mission without one: plain line-following. A real
    # route needs a starting position and somewhere to go.
    if len(stations) == 1:
        raise ConfigError("route must contain at least two stations, or none; "
                          "first is initial position")
    if stations and stations[0]["direction"] != "outbound":
        raise ConfigError("route first station must be outbound")
    speed, contacts = [], set()
    stop_tags = {tag for direction, tag in stops}
    for row, loc in _rule_rows(speed_rows, ("entry_tag", "exit_tag", "direction"),
                               "high_speed_mode"):
        direction = _travel_direction(row["direction"], loc)
        tags = [_tag(row[k], tag_len * 2, loc + "." + k,
                     ignored | branch_tags | stop_tags)
                for k in ("entry_tag", "exit_tag")]
        for tag in tags:
            if (direction, tag) in contacts:
                raise ConfigError(f"{loc}: duplicate/ambiguous high-speed contact in {direction}")
            contacts.add((direction, tag))
        speed.append(dict(entry_tag=tags[0], exit_tag=tags[1], direction=direction))
    for i, station in enumerate(stations):
        departure = stations[(i + 1) % len(stations)]["direction"]
        if station["high_speed_to_next"] and not any(
                r["direction"] == departure for r in speed):
            raise ConfigError(f"route[{i}]: high-speed leg has no {departure} speed rule")
    return stations, speed


def _read_route_guard(raw, stations):
    keys = {'enabled', 'legs', 'high_speed_max_m', 'station_decel_limit_rpm_s'}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ConfigError(f"route_guard: expected exactly {sorted(keys)}")
    enabled = _coerce(raw['enabled'], bool, 'route_guard.enabled')

    def measured(value, where):
        if value is None:
            if enabled:
                raise ConfigError(f"{where}: measurement required before enabling route_guard")
            return None
        value = _coerce(value, float, where)
        if not math.isfinite(value) or value <= 0:
            raise ConfigError(f"{where}: expected a positive finite measurement")
        return value

    legs, ids = [], set()
    for row, loc in _rule_rows(raw['legs'], ('from_station', 'min_m', 'max_m'),
                               'route_guard.legs'):
        ident = _coerce(row['from_station'], str, loc + '.from_station')
        if ident in ids:
            raise ConfigError(f"{loc}: duplicate from_station")
        ids.add(ident)
        lo, hi = (measured(row[k], loc + '.' + k) for k in ('min_m', 'max_m'))
        if (lo is None) != (hi is None) or (lo is not None and lo >= hi):
            raise ConfigError(f"{loc}: provide both bounds with min_m < max_m")
        legs.append(dict(from_station=ident, min_m=lo, max_m=hi))
    if ids != {r['id'] for r in stations}:
        raise ConfigError('route_guard.legs: require exactly one row per route station')
    high = raw['high_speed_max_m']
    if not isinstance(high, dict) or set(high) != {'outbound', 'inbound'}:
        raise ConfigError('route_guard.high_speed_max_m: require outbound and inbound')
    high = {k: measured(v, 'route_guard.high_speed_max_m.' + k) for k, v in high.items()}
    limit = measured(raw['station_decel_limit_rpm_s'], 'route_guard.station_decel_limit_rpm_s')
    return dict(enabled=enabled, legs=legs, high_speed_max_m=high,
                station_decel_limit_rpm_s=limit)


def _read_u_turn(rows, tag_len, forbidden):
    """u_turn -> {tag: "cw" | "ccw"}. AUTO only; never a route station."""
    out = {}
    for row, loc in _rule_rows(rows, ("tag", "direction"), "u_turn"):
        tag = _tag(row["tag"], tag_len * 2, loc + ".tag", forbidden)
        if row["direction"] not in ("cw", "ccw"):
            raise ConfigError(f"{loc}.direction must be cw or ccw")
        if tag in out:
            raise ConfigError(f"{loc}.tag: {tag} is listed twice")
        out[tag] = row["direction"]
    return out




_MISSION_KEYS = ("mission_name", "speed", "branch_default", "branch_latch",
                 "stop_until_start_button", "high_speed_mode", "route",
                 "route_guard", "u_turn")


def _optional_float(value, where):
    if value is None:
        return None
    value = _coerce(value, float, where)
    if not math.isfinite(value):
        raise ConfigError(f"{where}: expected a finite number or null")
    return value


def _parse_mission(doc, ns):
    """Mission document -> namespace entries, checked against the parsed profile.

    Tags are validated with the profile's reader settings (tag length, ignore
    list), because a mission tag the reader discards is a rule that never fires.
    """
    if not isinstance(doc, dict):
        raise ConfigError("mission must be a JSON object")
    unknown = set(doc) - set(_MISSION_KEYS)
    if unknown:
        raise ConfigError(f"mission: unknown key(s) {sorted(unknown)}")
    missing = set(_MISSION_KEYS) - set(doc)
    if missing:
        raise ConfigError(f"mission: missing key(s) {sorted(missing)}")

    out = {"MISSION_NAME": _coerce(doc["mission_name"], str, "mission_name")}
    speed, keys = doc["speed"], {"auto_rpm_high", "speed_switch_accel_decel_s"}
    if not isinstance(speed, dict) or set(speed) != keys:
        raise ConfigError(f"mission speed: expected exactly {sorted(keys)}")
    out["AUTO_RPM_HIGH"] = _optional_float(speed["auto_rpm_high"], "speed.auto_rpm_high")
    out["SPEED_SWITCH_S"] = _optional_float(speed["speed_switch_accel_decel_s"],
                                            "speed.speed_switch_accel_decel_s")
    out["BRANCH_DEFAULT"] = _coerce(doc["branch_default"], str, "branch_default")

    tag_len, ignored = ns["RFID_TAG_LEN"], set(ns["RFID_IGNORE_TAGS"])
    out["BRANCH_LATCH"] = _read_branch_latch(doc["branch_latch"], tag_len, ignored)
    branch_tags = {r[k] for r in out["BRANCH_LATCH"] for k in ("entry_tag", "exit_tag")}
    out["STOP_TAGS"] = _read_stop_tags(doc["stop_until_start_button"], tag_len,
                                       ignored, branch_tags)
    out["ROUTE"], out["HIGH_SPEED_MODE"] = _read_route(
        doc["route"], doc["high_speed_mode"], out["STOP_TAGS"], tag_len,
        ignored, branch_tags)
    out["ROUTE_GUARD"] = _read_route_guard(doc["route_guard"], out["ROUTE"])
    speed_tags = {r[k] for r in out["HIGH_SPEED_MODE"] for k in ("entry_tag", "exit_tag")}
    out["U_TURN_TAGS"] = _read_u_turn(
        doc["u_turn"], tag_len,
        ignored | branch_tags | {tag for _, tag in out["STOP_TAGS"]} | speed_tags)
    out["STOP_TAGS_ANY"] = {} if out["ROUTE"] else _routeless(out)
    return out


def _routeless(out):
    """Without a route there is no travel direction, so a tag must mean one thing.

    Returns {tag: stop rule} for station stops matched by tag alone.
    """
    if out["ROUTE_GUARD"]["enabled"]:
        raise ConfigError("route_guard cannot be enabled without a route")
    stops = {}
    for (_direction, tag), rule in sorted(out["STOP_TAGS"].items()):
        if tag in stops and stops[tag]["stop_distance_m"] != rule["stop_distance_m"]:
            raise ConfigError(f"stop_until_start_button: tag {tag} has two stop "
                              f"distances; without a route there is no direction "
                              f"to choose between them")
        stops[tag] = {"stop_distance_m": rule["stop_distance_m"]}
    entries = {r["entry_tag"] for r in out["HIGH_SPEED_MODE"]}
    exits = {r["exit_tag"] for r in out["HIGH_SPEED_MODE"]}
    both = sorted(entries & exits)
    if both:
        raise ConfigError(f"high_speed_mode: tag(s) {both} both set and reset high "
                          f"speed; without a route there is no direction, so each "
                          f"tag must be entry-only or exit-only")
    return stops



def _speeds(out, vehicle):
    """gy-demo's _derive/_validate rules for the site speeds and the guard."""
    guard = out["ROUTE_GUARD"]
    auto = float(vehicle.AUTO_RPM)
    if guard["enabled"]:
        if not vehicle.RFID_ENABLED:
            raise ConfigError("route_guard requires RFID enabled")
        limit = guard["station_decel_limit_rpm_s"]
        if limit > vehicle.RAMP["auto"]["decel"]:
            raise ConfigError("route_guard: station deceleration limit exceeds auto drive deceleration")
        cruise = out["AUTO_RPM_HIGH"] if out["HIGH_SPEED_MODE"] else auto
        for rule in out["STOP_TAGS"].values():
            rate = cruise ** 2 * vehicle.MPS_PER_RPM / (2 * rule["stop_distance_m"])
            if rate > limit:
                raise ConfigError("route_guard: high-speed station stop exceeds measured deceleration limit; "
                                  "reduce auto_rpm_high or commission a longer stop_distance_m")
    high, switch = out["AUTO_RPM_HIGH"], out["SPEED_SWITCH_S"]
    if out["HIGH_SPEED_MODE"] and (high is None or switch is None):
        raise ConfigError("mission speed.auto_rpm_high and "
                          "speed.speed_switch_accel_decel_s are required when "
                          "high_speed_mode has rules")
    if switch is not None and switch <= 0:
        raise ConfigError("speed_switch_accel_decel_s must be > 0")
    if high is not None and not auto < high <= vehicle.MOTOR_MAX_RPM:
        raise ConfigError("auto_rpm_high must exceed auto_rpm and not exceed motor_max_rpm")
    out["SPEED_SWITCH_RPM_S"] = ((high - auto) / switch
                                 if high is not None and switch is not None else None)
    if out["SPEED_SWITCH_RPM_S"] is not None and out["SPEED_SWITCH_RPM_S"] > vehicle.RAMP_ACCEL_RPM_S:
        raise ConfigError("speed_switch_accel_decel_s requests a rate above ramp_accel_rpm_s")
    if out["BRANCH_DEFAULT"] not in ("straight", "left", "right"):
        raise ConfigError(f"mission branch_default ({out['BRANCH_DEFAULT']!r}) must be "
                          "straight, left or right")


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
    "speed": {"auto_rpm_high": None, "speed_switch_accel_decel_s": None},
    "branch_default": "straight",
    "branch_latch": [],
    "stop_until_start_button": [],
    "high_speed_mode": [],
    "route": [],
    "route_guard": {"enabled": False, "legs": [],
                    "high_speed_max_m": {"outbound": None, "inbound": None},
                    "station_decel_limit_rpm_s": None},
    "u_turn": [],
}


def parse(doc, vehicle=None):
    """A mission document -> the validated names. MissionError on any problem."""
    if vehicle is None:
        from agv_core import config as vehicle  # noqa: PLC0415
    ns = {"RFID_TAG_LEN": vehicle.RFID_TAG_LEN, "RFID_IGNORE_TAGS": vehicle.RFID_IGNORE_TAGS}
    try:
        out = _parse_mission(doc, ns)
        _speeds(out, vehicle)
    except MissionError:
        raise
    except ConfigError as e:
        raise MissionError(str(e)) from None
    return out


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
