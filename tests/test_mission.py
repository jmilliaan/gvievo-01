"""Tape-mission validation (agv_core/mission.py, ported from gy-demo 2026-10-02).

The repo ships no site mission: "empty" is built in and is plain line following.
Every refusal below is a rule that would otherwise fail SILENTLY on the floor - a
tag that never matches produces no error, only a vehicle driving past.
"""
import copy
import json
import os
import tempfile

from helpers import check

from agv_core import mission


def base(**over):
    d = copy.deepcopy(mission.EMPTY)
    d["mission_name"] = "t"
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
          m["ROUTE"] == [] and m["STOP_TAGS"] == {} and m["U_TURN_TAGS"] == {}
          and m["BRANCH_LATCH"] == [] and m["BRANCH_DEFAULT"] == "straight")
    check("...and no speed keys: tracked speeds are the profile's", not any("SPEED" in k or "RPM" in k for k in m))
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


def test_refusals():
    print("\nmission: refusals")
    stop = {"tag": "0010", "stop_distance_m": 0.4, "direction": "outbound"}
    refused("a tag written as a number never matches the reader's hex text",
            base(stop_until_start_button=[dict(stop, tag=10)]), "hex")
    refused("a stop distance past 5 m is refused",
            base(stop_until_start_button=[dict(stop, stop_distance_m=9)]), "(0, 5]")
    refused("a branch tag reused as a station tag is refused",
            base(branch_latch=[{"entry_tag": "0010", "exit_tag": "0011", "branch": "left"}],
                 stop_until_start_button=[stop]), "another rule type")
    refused("a high_speed_mode table (removed 2026-10-02) is refused, not ignored",
            base(high_speed_mode=[{"entry_tag": "0020", "exit_tag": "0021", "direction": "outbound"}]),
            "unknown key")
    refused("a mission speed section (removed 2026-10-02) is refused, not ignored",
            base(speed={"auto_rpm_high": 2000.0, "speed_switch_accel_decel_s": 3.0}),
            "unknown key")
    refused("a U-turn direction other than cw/ccw is refused",
            base(u_turn=[{"tag": "0030", "direction": "left"}]), "cw or ccw")
    refused("route-less, one station tag cannot carry two distances",
            base(stop_until_start_button=[stop, dict(stop, direction="inbound", stop_distance_m=0.6)]),
            "two stop")
    refused("an unknown key is refused", base(extra=1), "unknown key")
    m = mission.parse(base(stop_until_start_button=[stop], u_turn=[{"tag": "0030", "direction": "ccw"}]))
    check("a route-less station stops by tag alone", m["STOP_TAGS_ANY"] == {"0010": {"stop_distance_m": 0.4}})
    check("...and the U-turn table is keyed by tag", m["U_TURN_TAGS"] == {"0030": "ccw"})


def test_speed_toggle_tags_are_their_own_namespace():
    print("\nmission: profile speed-toggle tags")
    from agv_core import config
    saved = config.SPEED_TOGGLE_TAGS
    config.SPEED_TOGGLE_TAGS = ("0040", "0041")
    try:
        refused("a station tag that is also a speed toggle tag is refused",
                base(stop_until_start_button=[{"tag": "0041", "stop_distance_m": 0.4,
                                               "direction": "outbound"}]), "speed_toggle_tags")
        refused("a U-turn tag that is also a speed toggle tag is refused",
                base(u_turn=[{"tag": "0040", "direction": "cw"}]), "speed_toggle_tags")
        m = mission.parse(base(u_turn=[{"tag": "0030", "direction": "cw"}]))
        check("disjoint tags load", m["U_TURN_TAGS"] == {"0030": "cw"})
    finally:
        config.SPEED_TOGGLE_TAGS = saved


TESTS = [test_empty_and_listing, test_refusals, test_speed_toggle_tags_are_their_own_namespace]
