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
         "approach_mps": 0.1, "max_approach_m": 2.0}
TOGGLE = {"tag": "0040", "action": "speed_toggle", "ignore_s": 5, "ramp_s": 2.0}


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
    m = mission.load("empty")
    check("empty loads with nothing site-specific",
          m["TAGS"] == {} and m["HOME"] is None and m["DESTINATIONS"] == []
          and m["BRANCH_LATCH"] == [] and m["BRANCH_DEFAULT"] == "straight")
    check("empty is always offered", "empty" in mission.list_missions())
    tmp = tempfile.mkdtemp()
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
    check("the U-turn is cw at 0.1 m/s", m["TAGS"]["0030"]["direction"] == "cw"
          and m["TAGS"]["0030"]["approach_mps"] == 0.1)
    check("the toggle ramps over 2 s and locks out 5 s",
          m["TOGGLE_TAGS"] == ("0040",) and m["TAGS"]["0040"]["ramp_s"] == 2.0
          and m["TAGS"]["0040"]["ignore_s"] == 5.0)


def test_refusals():
    print("\nmission: refusals")
    refused("a tag written as a number never matches the reader's hex text",
            base([stop(tag=10)]), "hex")
    refused("a tag of the wrong width is refused", base([stop(tag="010")]), "hex characters")
    refused("a tag listed twice is refused", base([HOME, stop(tag="0010", label="X")]), "listed twice")
    refused("a branch tag reused as a stop tag is refused",
            base([HOME], branch_latch=[{"entry_tag": "0010", "exit_tag": "0011", "branch": "left"}]),
            "branch_latch")
    refused("an unknown action is refused", base([dict(TOGGLE, action="slow")]), "action")
    refused("an unknown role is refused", base([stop(role="sometimes")]), "role")
    refused("a key from another action is refused", base([dict(TOGGLE, direction="cw")]), "unknown key")
    refused("a missing key is refused",
            base([{k: v for k, v in UTURN.items() if k != "max_approach_m"}]), "missing key")
    refused("a stop distance past 5 m is refused", base([HOME, stop(stop_distance_m=9)]), "(0, 5]")
    refused("a negative ignore window is refused", base([dict(TOGGLE, ignore_s=-1)]), "[0, 30]")
    refused("a stop needs a label", base([stop(label=" ")]), "label")
    refused("two stops with one label are refused",
            base([HOME, stop(), stop(tag="0120")]), "already")
    refused("two homes are refused", base([HOME, stop("0011", "home", "Home 2")]), "home stops")
    refused("destinations without a home are refused", base([stop()]), "need a home")
    refused("a U-turn direction other than cw/ccw is refused",
            base([dict(UTURN, direction="left")]), "cw or ccw")
    refused("a U-turn approach faster than slow speed is refused",
            base([dict(UTURN, approach_mps=5.0)]), "approach_mps")
    refused("speed toggles with different windows are refused",
            base([TOGGLE, dict(TOGGLE, tag="0041", ignore_s=3)]), "lockout")
    refused("a stop shorter than the drives can decelerate is refused",
            base([HOME, stop(stop_distance_m=0.01)]), "decel")
    refused("an unknown key is refused", base(extra=1), "unknown key")
    refused("a v1 route document is refused by name, not half-loaded",
            base(route=[], route_guard={}), "retired v1")
    m = mission.parse(base([HOME, stop(tag="0110"), UTURN, dict(TOGGLE, tag="00a4")]))
    check("a lower-case tag loads, normalised to the panel's uppercase", "00A4" in m["TAGS"])


TESTS = [test_empty_and_listing, test_the_site_table_loads, test_refusals]
