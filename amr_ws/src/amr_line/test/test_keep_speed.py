"""keep_speed (2026-11-24, AGV-02 C-STU through J-R3E): a junction its circuit item marks keep_speed is
no point of the speed envelope, so a trip inside a speed area passes it at the area's speed. Every
other junction still has the envelope back at the cruise by its fork."""
import copy
import json
import os
from types import SimpleNamespace

import pytest
from agv_core import config as vehicle  # noqa: E402
from agv_core import mission as missions  # noqa: E402
from site_fixture import DOC  # noqa: E402

from amr_line import site_run  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402

CRUISE = 0.4 * vehicle.RPM_PER_MPS
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def doc_with(item_over, index=3):
    """DOC with circuit C-M's item `index` (J-B right) replaced."""
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][index] = item_over
    return d


# -- the loader ---------------------------------------------------------------------------------
def test_the_loader_takes_keep_speed_on_a_straight_on_and_passes_it_with_the_circuit():
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][1] = {"junction": "J-A", "order": "merge", "steer": "left", "keep_speed": True}
    m = missions.parse_site(d)
    assert m["CIRCUITS"]["C-M"]["keep_speed"] == ["J-A:merge"]
    assert m["CIRCUITS"]["C-M"]["steers"] == {"J-A:merge": "left"}
    plain = missions.parse_site(copy.deepcopy(DOC))
    assert plain["CIRCUITS"]["C-M"]["keep_speed"] == []


def test_keep_speed_false_is_the_same_as_none():
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][1] = {"junction": "J-A", "order": "merge", "keep_speed": False}
    assert missions.parse_site(d)["CIRCUITS"]["C-M"]["keep_speed"] == []


@pytest.mark.parametrize("item, words", [
    ({"junction": "J-B", "order": "right", "keep_speed": True}, "only on a straight on"),
    ({"junction": "J-B", "order": "right", "keep_speed": "yes"}, "only on a straight on"),
])
def test_the_loader_refuses_keep_speed_on_a_diverge(item, words):
    with pytest.raises(missions.MissionError, match=words):
        missions.parse_site(doc_with(item))


def test_the_loader_refuses_a_keep_speed_that_is_not_a_boolean():
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][1] = {"junction": "J-A", "order": "merge", "keep_speed": 1}
    with pytest.raises(missions.MissionError, match="expected true or false"):
        missions.parse_site(d)


def test_the_loader_refuses_keep_speed_on_a_stop_or_an_unlaid_junction():
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][2] = {"stop": "ATT", "keep_speed": True}
    with pytest.raises(missions.MissionError):
        missions.parse_site(d)
    d = copy.deepcopy(DOC)
    d["junctions"]["J-A"]["laid"] = False
    d["circuits"]["C-M"][1] = {"junction": "J-A", "order": "merge", "keep_speed": True}
    with pytest.raises(missions.MissionError, match="not laid"):
        missions.parse_site(d)


def test_agv2_keeps_speed_through_j_r3e_on_c_stu_only():
    with open(os.path.join(REPO, "missions", "site-103-agv2.json")) as fh:
        m = missions.parse_site(json.load(fh))
    assert m["CIRCUITS"]["C-STU"]["keep_speed"] == ["J-R3E:merge", "J-R3E:straight"]
    assert m["CIRCUITS"]["C-ROW3"]["keep_speed"] == []


# -- the envelope -------------------------------------------------------------------------------
# A straight 40 m trip: one HIGH zone [5, 35), one straight-on junction with its fork at S 20.
ZONE = (5.0, 35.0, "Z", "high")
NODE = {"id": "J-X", "kind": "junction", "order": "straight", "S": 20.4, "S_fork": 20.0, "fork": True,
        "sigma": 0.05, "leg_in": "a", "leg_out": "b"}


def run_on(keep):
    site = {"MISSION_NAME": "t", "HOME": "HOME", "STOP_DISTANCE_M": 0.5, "CRUISE_MPS": 0.4,
            "CIRCUITS": {"C-X": {"keep_speed": ["J-X:straight"] if keep else []}}}
    route = SimpleNamespace(ident="trip:x", circuit="C-X", events=[], nodes=[dict(NODE)], zones=[ZONE],
                            uturn=None, stops=[{"id": "HOME"}, {"id": "HOME"}], notes=[])
    trip = SimpleNamespace(describe=lambda: "t")
    r = site_run.SiteRun(site, trip, route, tl.Params())
    r._step_ok = True
    return r


def ceiling_at(r, S):
    r.locate({"route": "trip:x", "started": True, "S": S, "sigma": 0.01, "lost": ""})
    r._speed()
    return r._ceiling


def test_a_plain_junction_has_the_envelope_back_at_the_cruise_by_its_fork():
    r = run_on(keep=False)
    assert ceiling_at(r, 12.0) == pytest.approx(vehicle.AUTO_HIGH_RPM), "HIGH well before the fork"
    assert ceiling_at(r, 19.5) < vehicle.AUTO_HIGH_RPM - 100.0, "slowing into the fork"
    assert ceiling_at(r, 20.0 - site_run.ENVELOPE_MARGIN_M) <= CRUISE + 1.0, "at the cruise by the fork"
    # Past the fork the ceiling is HIGH again; the drives' ramp makes the climb.
    assert ceiling_at(r, 20.5) == pytest.approx(vehicle.AUTO_HIGH_RPM), "HIGH again past it"


def test_a_keep_speed_junction_is_passed_at_the_zone_speed():
    r = run_on(keep=True)
    for S in (12.0, 19.0, 19.7, 20.0, 20.5):
        assert ceiling_at(r, S) == pytest.approx(vehicle.AUTO_HIGH_RPM), S
    assert r._high
    # The zone's end still brings it down: keep_speed lifts the junction, nothing else.
    assert ceiling_at(r, 34.9) <= CRUISE + 1.0
