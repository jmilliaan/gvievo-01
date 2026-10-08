"""Tape-mission validation (agv_core/mission.py, schema v2 2026-10-08: the tag table).

Every refusal below is a rule that would otherwise fail SILENTLY on the floor - a
tag that never matches produces no error, only a vehicle driving past.
"""
import copy
import json
import os
import tempfile

from helpers import check

from agv_core import mission


def stop(tag="0110", role="destination", label="MRU1", **over):
    row = {"tag": tag, "action": "stop", "ignore_s": 4, "stop_distance_m": 0.5,
           "role": role, "label": label}
    row.update(over)
    return row


HOME = stop("0010", "home", "Home", ignore_s=2)
UTURN = {"tag": "0030", "action": "u_turn", "ignore_s": 2, "direction": "cw",
         "approach_mps": 0.1, "decel_m": 0.3, "max_approach_m": 2.0}
INNER = {"tag": "0040", "action": "zone_inner", "ignore_s": 1}
OUTER = {"tag": "0060", "action": "zone_outer", "ignore_s": 1}
ZONE = {"shortest_straight_m": 18.0, "pair_spacing_m": 0.5}


def base(tags=(), **over):
    d = copy.deepcopy(mission.EMPTY)
    d["mission_name"] = "t"
    d["tags"] = [copy.deepcopy(r) for r in tags]
    d.update(over)
    return d


def refused(name, doc, needle):
    try:
        mission.parse(doc)
        check(name, False, "accepted")
    except mission.MissionError as e:
        check(name, needle in str(e), str(e)[:80])


def test_empty_and_listing():
    print("\nmission: the built-in empty mission")
    m = mission.parse(mission.EMPTY)
    check("the built-in empty has nothing site-specific",
          m["TAGS"] == {} and m["HOME"] is None and m["DESTINATIONS"] == []
          and m["BRANCH_LATCH"] == [] and m["BRANCH_DEFAULT"] == "straight")
    m = mission.load("empty")
    turns = {t: r["direction"] for t, r in m["TAGS"].items()}
    check("missions/empty.json is plain line following with the U-turn tags only",
          turns == {"0180": "cw", "0190": "ccw"} and m["HOME"] is None and m["HIGH_ZONE"] is None
          and all(r["action"] == "u_turn" for r in m["TAGS"].values()), str(turns))
    # 2026-10-08 (operator): always branch left - the site missions, not the built-in fallback.
    check("both site missions branch left at every diverter and merge",
          m["BRANCH_DEFAULT"] == "left" and mission.load("line-a")["BRANCH_DEFAULT"] == "left"
          and m["BRANCH_LATCH"] == [] and mission.load("line-a")["BRANCH_LATCH"] == [])
    tmp = tempfile.mkdtemp()
    check("without the file, empty is the built-in one", mission.load("empty", directory=tmp)["TAGS"] == {})
    check("empty is always offered", "empty" in mission.list_missions())
    with open(os.path.join(tmp, "a.json"), "w") as f:
        json.dump(base(mission_name="b"), f)
    try:
        mission.load("a", directory=tmp)
        check("a mission_name that does not match its file is refused", False, "accepted")
    except mission.MissionError as e:
        check("a mission_name that does not match its file is refused", "does not match" in str(e))
    for bad in ("../x", ".hidden", ""):
        try:
            mission.load(bad, directory=tmp)
            check(f"name {bad!r} refused", False, "accepted")
        except mission.MissionError:
            check(f"name {bad!r} refused", True)


def test_the_site_table_loads():
    print("\nmission: missions/line-a.json, the site's RFID tag reference")
    m = mission.load("line-a")
    check("home is 0010", m["HOME"]["tag"] == "0010" and m["HOME"]["role"] == "home")
    check("four destinations, in table order", m["DESTINATIONS"] == ["MRU1", "MRU2", "MRU3", "MRU4"])
    check("trolley release stops every pass", m["TAGS"]["0020"]["role"] == "always")
    check("U-turn 0180 is cw, 0190 ccw, both slowing to 0.1 m/s within 0.3 m",
          m["TAGS"]["0180"]["direction"] == "cw" and m["TAGS"]["0190"]["direction"] == "ccw"
          and all(m["TAGS"][t]["approach_mps"] == 0.1 and m["TAGS"][t]["decel_m"] == 0.3
                  for t in ("0180", "0190")))
    from agv_core import config
    z = m["HIGH_ZONE"]
    check("high zone 0060 outer -> 0040 inner, budget from the 10 m surveyed straight",
          z["outer"] == "0060" and z["inner"] == "0040"
          and abs(z["high_for_m"] - (10.0 - z["brake_m"] - config.HIGH_MARGIN_M)) < 1e-9,
          f"{z['high_for_m']:.2f} m")


def test_refusals():
    print("\nmission: refusals")
    refused("a tag written as a number never matches the reader's hex text",
            base([stop(tag=10)]), "hex")
    refused("a tag of the wrong width is refused", base([stop(tag="010")]), "hex characters")
    refused("a tag listed twice is refused", base([HOME, stop(tag="0010", label="X")]), "listed twice")
    refused("a branch tag reused as a stop tag is refused",
            base([HOME], branch_latch=[{"entry_tag": "0010", "exit_tag": "0011", "branch": "left"}]),
            "branch_latch")
    refused("an unknown action is refused", base([dict(INNER, action="slow")]), "action")
    refused("an unknown role is refused", base([stop(role="sometimes")]), "role")
    refused("a key from another action is refused", base([dict(INNER, direction="cw")], high_zone=ZONE),
            "unknown key")
    refused("a missing key is refused",
            base([{k: v for k, v in UTURN.items() if k != "max_approach_m"}]), "missing key")
    refused("a stop distance past 5 m is refused", base([HOME, stop(stop_distance_m=9)]), "(0, 5]")
    refused("a negative ignore window is refused", base([dict(UTURN, ignore_s=-1)]), "[0, 30]")
    refused("a stop needs a label", base([stop(label=" ")]), "label")
    refused("two stops with one label are refused",
            base([HOME, stop(), stop(tag="0120")]), "already")
    refused("two homes are refused", base([HOME, stop("0011", "home", "Home 2")]), "home stops")
    refused("destinations without a home are refused", base([stop()]), "need a home")
    refused("a U-turn direction other than cw/ccw is refused",
            base([dict(UTURN, direction="left")]), "cw or ccw")
    refused("a U-turn row without decel_m is refused",
            base([{k: v for k, v in UTURN.items() if k != "decel_m"}]), "decel_m")
    refused("a U-turn slowdown shorter than the drives can decelerate is refused",
            base([dict(UTURN, decel_m=0.05)]), "decel_m")
    refused("a U-turn approach faster than slow speed is refused",
            base([dict(UTURN, approach_mps=5.0)]), "approach_mps")
    refused("the retired speed toggle is refused with a pointer to the zone pair",
            base([{"tag": "0040", "action": "speed_toggle", "ignore_s": 5, "ramp_s": 2.0}]), "zone_outer")
    refused("a stop shorter than the drives can decelerate is refused",
            base([HOME, stop(stop_distance_m=0.01)]), "decel")
    refused("an unknown key is refused", base(extra=1), "unknown key")
    refused("a v1 route document is refused by name, not half-loaded",
            base(route=[], route_guard={}), "retired v1")
    m = mission.parse(base([HOME, stop(tag="0110"), UTURN, dict(INNER, tag="00a4"), OUTER], high_zone=ZONE))
    check("a lower-case tag loads, normalised to the panel's uppercase", "00A4" in m["TAGS"])


def test_high_zone():
    print("\nmission: high zone (v2.1, tracked-speed-plan-1)")
    from agv_core import config
    m = mission.parse(base([HOME, stop(), UTURN, INNER, OUTER], high_zone=ZONE))
    z = m["HIGH_ZONE"]
    v_n, v_h = config.AUTO_RPM * config.MPS_PER_RPM, config.AUTO_HIGH_RPM * config.MPS_PER_RPM
    brake = (v_n + v_h) / 2 * config.HIGH_RAMP_S
    check("one shared inner and outer id", z["inner"] == "0040" and z["outer"] == "0060")
    check("the budget is derived: straight - braking - margin",
          abs(z["high_for_m"] - (18.0 - brake - config.HIGH_MARGIN_M)) < 1e-9, f"{z['high_for_m']:.3f}")
    check("the entry window is the pair spacing plus a tolerance", abs(z["arm_m"] - 1.5) < 1e-9)
    refused("zone rows without the high_zone block are refused", base([INNER, OUTER]), "high_zone")
    refused("a high_zone without both tags is refused", base([INNER], high_zone=ZONE), "exactly one")
    refused("a zone tag ignore window over 2 s is refused",
            base([dict(INNER, ignore_s=5), OUTER], high_zone=ZONE), "<= 2")
    refused("a straight too short for the budget is refused",
            base([INNER, OUTER], high_zone=dict(ZONE, shortest_straight_m=4.0)), "not worth it")
    refused("a pair spacing outside [0.3, 1.0] m is refused",
            base([INNER, OUTER], high_zone=dict(ZONE, pair_spacing_m=0.1)), "pair_spacing_m")
    refused("a stop the drives cannot make from HIGH is refused when the mission has a zone",
            base([HOME, stop(stop_distance_m=0.1), INNER, OUTER], high_zone=ZONE), "decel")
    refused("a U-turn creep faster than NORMAL is refused",
            base([dict(UTURN, approach_mps=0.6)]), "approach_mps")


TESTS = [test_empty_and_listing, test_the_site_table_loads, test_refusals, test_high_zone]
