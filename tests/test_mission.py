"""Vehicle profile vs mission file: the split, the empty mission, route-less tags."""
import copy
import json
import os
import shutil
import tempfile

from helpers import ROOT, check, mission_doc, parse, profile_doc
import canworker
import config
import events
import runlog
import server


def _refused(name, mutate, expect, mission=None):
    profile = profile_doc()
    m = copy.deepcopy(mission) if mission is not None else mission_doc()
    mutate(profile, m)
    try:
        parse(profile, m)
    except config.ConfigError as e:
        check(name, expect in str(e), str(e))
    else:
        check(name, False, "accepted")


def _routeless():
    """The GY layout without its route: outbound speed pair only, guard off."""
    m = mission_doc()
    m["route"] = []
    m["route_guard"]["legs"] = []
    m["high_speed_mode"] = [r for r in m["high_speed_mode"] if r["direction"] == "outbound"]
    return m


def _write(doc, name, tmp):
    path = os.path.join(tmp, f"{name}.json")
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


def test_shipped_missions_and_selection():
    print("\nmission files: selection and the empty template")
    check("the profile names its mission", config.MISSION == "gy-demo", str(config.MISSION))
    check("the default load uses it",
          config.MISSION_NAME == "gy-demo" and len(config.ROUTE) == 4
          and config.AUTO_RPM_HIGH == 2000.0 and config.SPEED_SWITCH_S == 3.0
          and config.MISSION_PATH_LOADED.endswith(os.path.join("missions", "gy-demo.json")))
    tmp = tempfile.mkdtemp()
    try:
        config.load(mission="empty")
        check("the empty template loads with nothing site-specific",
              config.MISSION_NAME == "empty" and config.ROUTE == [] and config.STOP_TAGS == {}
              and config.HIGH_SPEED_MODE == [] and config.U_TURN_TAGS == {}
              and config.BRANCH_LATCH == [] and config.BRANCH_DEFAULT == "straight")
        check("...with null site speeds and no switch rate",
              config.AUTO_RPM_HIGH is None and config.SPEED_SWITCH_RPM_S is None)
        check("...and it is exactly the built-in empty mission",
              json.loads((ROOT / "missions" / "empty.json").read_text()) == config.EMPTY_MISSION)
        empty_rows = [s["name"] for s in config.describe() if not s["rows"]]
        check("/params still renders every section with rows", not empty_rows, str(empty_rows))
        data = server.app.test_client().get("/api/config").get_json()
        check("/api/config names the mission and its file",
              data["mission"] == "empty" and data["mission_path"].endswith("empty.json"))

        os.environ[config.MISSION_ENV_VAR] = "empty"
        try:
            config.load()
            check("AGV_MISSION overrides the profile's mission", config.MISSION_NAME == "empty")
        finally:
            del os.environ[config.MISSION_ENV_VAR]

        profile = profile_doc()
        profile["mission"] = None
        config.load(_write(profile, "agv-01", tmp))
        check("profile mission null loads the built-in empty mission, no file needed",
              config.MISSION_PATH_LOADED is None and config.ROUTE == []
              and config.MISSION_NAME == "empty")

        try:
            config.load(mission="no-such-mission")
            check("a missing mission is fatal", False, "accepted")
        except config.ConfigError as e:
            check("a missing mission names the env var and what exists",
                  config.MISSION_ENV_VAR in str(e) and "gy-demo" in str(e) and "empty" in str(e),
                  str(e)[:100])
        try:
            config.load(mission=_write(mission_doc(), "other-site", tmp))
            check("mission_name must match the file name", False, "accepted")
        except config.ConfigError as e:
            check("mission_name must match the file name", "mission_name" in str(e), str(e))
        profile = profile_doc()
        profile["mission"] = ""
        try:
            config.load(_write(profile, "agv-01", tmp))
            check("a blank mission name is refused", False, "accepted")
        except config.ConfigError as e:
            check("a blank mission name is refused", "mission" in str(e), str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        config.load()
    check("the real profile and mission are restored", config.MISSION_NAME == "gy-demo")


def test_split_validation():
    print("\nmission validation")
    _refused("a site speed left in the profile is refused",
             lambda p, m: p["autopilot"].update(auto_rpm_high=2000.0), "unknown key")
    _refused("a mission table left in the profile is refused",
             lambda p, m: p.update(u_turn=[]), "unknown top-level")
    _refused("an unknown mission key is refused",
             lambda p, m: m.update(extra=[]), "unknown key")
    _refused("a missing mission key is refused",
             lambda p, m: m.pop("u_turn"), "missing key")
    _refused("high-speed rules need both site speeds",
             lambda p, m: m["speed"].update(auto_rpm_high=None), "required when high_speed_mode")
    _refused("a mission tag the reader ignores is refused",
             lambda p, m: m["u_turn"][0].update(tag=p["rfid"]["ignore_tags"][0]), "ignored")
    _refused("a one-station route is refused", lambda p, m: m.update(route=m["route"][:1]),
             "at least two stations, or none")

    ns = parse(mission=_routeless())
    check("a route-less mission loads, stops matched by tag",
          ns["ROUTE"] == [] and set(ns["STOP_TAGS_ANY"]) == {"0010", "0011"})
    check("a routed mission needs no tag-only stop table", parse()["STOP_TAGS_ANY"] == {})

    def unroute(p, m):
        m["route"], m["route_guard"]["legs"] = [], []
    _refused("without a route, a reversed speed pair is refused",
             unroute, "entry-only or exit-only")
    _refused("without a route, route_guard cannot be enabled",
             lambda p, m: m["route_guard"].update(
                 enabled=True, high_speed_max_m={"outbound": 1.0, "inbound": 1.0},
                 station_decel_limit_rpm_s=1600.0),
             "without a route", mission=_routeless())
    _refused("without a route, one tag cannot have two stop distances",
             lambda p, m: m["stop_until_start_button"].append(
                 {"tag": "0010", "direction": "inbound", "stop_distance_m": 0.6}),
             "two stop distances", mission=_routeless())


def _scan(c, tag):
    seq = c._rfid_cursor + 1
    c._scan_route(dict(encounter_seq=seq, generation=c._rfid_generation, comms_ok=True,
                       tag_age_s=0, encounters=[(seq, tag)]))


def test_controller_without_a_route():
    print("\nauto without a route in the mission")
    tmp = tempfile.mkdtemp()
    try:
        config.load(mission="empty")
        c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        c._auto_running = True
        s = c.snapshot()
        check("an empty mission reports the route as disabled",
              s["route"]["enabled"] is False and s["route_display"]["sequence"] == []
              and s["route_display"]["next_departure_direction"] is None)
        _scan(c, "0010")
        check("with an empty mission a tag is not a station",
              c._stop_hold is None
              and c.snapshot()["route_display"]["last_encounter"]["action"] == "no route action")

        config.load(mission=_write(_routeless(), "gy-demo", tmp))
        c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        c._auto_running = True
        _scan(c, "0020")
        check("a speed entry tag selects high speed without a route", c._route.high)
        _scan(c, "0021")
        check("...and the exit clears it", not c._route.high)
        c._follower._v_rpm = config.AUTO_RPM
        _scan(c, "0010")
        check("a station tag still stops the run, named by its tag",
              c._stop_hold == "0010" and "station tag 0010" in (c._last_stop_reason or ""))
        c._resume_from_stop()
        check("Start resumes with the departed tag suppressed",
              c._stop_hold is None and c._departure_tag == "0010")
        _scan(c, "0010")
        check("...so the tag it is still standing on does not stop it again",
              c._stop_hold is None
              and c.snapshot()["route_display"]["last_encounter"]["action"] == "suppressed")
        _scan(c, "0031")
        check("a U-turn tag still starts a U-turn",
              c._uturn_req == {"tag": "0031", "direction": "ccw"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        config.load()
        events.clear()


TESTS = [test_shipped_missions_and_selection, test_split_validation,
         test_controller_without_a_route]
