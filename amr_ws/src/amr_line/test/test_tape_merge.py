"""One lap of a new circuit added to a graph that holds legs no pass has (amr_line.tape_merge). Pure."""

import argparse
import copy
import math
import random

import pytest
from agv_core import mission as missions

from amr_line import tape_graph as tg
from amr_line import tape_graph_store as store
from amr_line import tape_merge as tm
from amr_line import tape_teach as tt
from amr_line import trip as tripmod
from amr_line import trip_route

# C-M is what the base graph holds, C-B the circuit a lap adds. They share the way out to J-B, and the
# way home from J-C. Like C-BTU: its tail joins C-M's return at J-F with a new order, J-F:merge>J-C.
#
#   J-C:left>J-A    (0,0)->(10,0)                 HOME at 5, the drawn leg
#   J-A:merge>J-B   (10,0)->(10,10)               ATT at 3
#   J-B:right>U     (10,10)->(30,10)              MW-1 at 8
#   U:pivot>J-F     (30,10)->(0,10)->(0,5)        ME-1 at 12
#   J-F:left>J-C    (0,5)->(0,0)
#   J-B:straight>J-E   (10,10)->(10,20)           new
#   J-E:right>J-F      (10,20)->(-5,20)->(-5,8)->(0,5)     new, R-1 at 5 (x 5), R-2 at 10 (x 0)
#   J-F:merge>J-C      (0,5)->(0,0)               new
DOC = {
    "schema": "site-4",
    "mission_name": "t",
    "home": "HOME",
    "attach": "ATT",
    "trip_calls": 1,
    "stop_distance_m": 0.5,
    "cruise_mps": 0.4,
    "junctions": {n: {"shape": "Y", "laid": True} for n in ("J-A", "J-B", "J-C", "J-E", "J-F")},
    "uturns": {
        "U": {"direction": "cw", "approach_mps": 0.1, "decel_m": 0.3, "max_approach_m": 2.0, "lead_m": 1.5}
    },
    "circuits": {
        "C-M": [
            {"stop": "HOME"},
            {"junction": "J-A", "order": "merge"},
            {"stop": "ATT"},
            {"junction": "J-B", "order": "right"},
            {"stop": "MW-1"},
            {"uturn": "U"},
            {"stop": "ME-1"},
            {"junction": "J-F", "order": "left"},
            {"junction": "J-C", "order": "left"},
            {"stop": "HOME"},
        ],
        "C-B": [
            {"stop": "HOME"},
            {"junction": "J-A", "order": "merge"},
            {"stop": "ATT"},
            {"junction": "J-B", "order": "straight"},
            {"junction": "J-E", "order": "right"},
            {"stop": "R-1"},
            {"stop": "R-2"},
            {"junction": "J-F", "order": "merge"},
            {"junction": "J-C", "order": "left"},
            {"stop": "HOME"},
        ],
    },
    "groups": {
        "M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"}}},
        "B": {"circuit": "C-B", "machines": {"B1": {"swap": "R-1"}, "B2": {"swap": "R-2"}}},
    },
    "uturn_points": {},
}
BINDING = {"map_id": "t", "map_revision": 1, "map_sha256": "ab" * 32}
BASE = {
    "J-C:left>J-A": [(0, 0), (10, 0)],
    "J-A:merge>J-B": [(10, 0), (10, 10)],
    "J-B:right>U": [(10, 10), (30, 10)],
    "U:pivot>J-F": [(30, 10), (0, 10), (0, 5)],
    "J-F:left>J-C": [(0, 5), (0, 0)],
}
NEW = {
    "J-B:straight>J-E": [(10, 10), (10, 20)],
    "J-E:right>J-F": [(10, 20), (-5, 20), (-5, 8), (0, 5)],
    "J-F:merge>J-C": [(0, 5), (0, 0)],
}
STOPS = {
    "HOME": ("J-C:left>J-A", 5.0),
    "ATT": ("J-A:merge>J-B", 3.0),
    "MW-1": ("J-B:right>U", 8.0),
    "ME-1": ("U:pivot>J-F", 12.0),
}
R_POSES = {"R-1": [5.0, 20.0, math.pi], "R-2": [0.0, 20.0, math.pi]}


def mission(doc=DOC):
    return missions.parse_site(copy.deepcopy(doc))


def base_graph(m):
    legs = []
    for lid, pts in BASE.items():
        frm, rest = lid.split(":")
        order, to = rest.split(">")
        end = "uturn" if to == "U" else "fork"
        legs.append(
            tg.Leg(
                lid, frm, order, to, tg.resample(pts), end_kind=end, fork_back_m=0.3 if end == "fork" else 0.0
            )
        )
    g = tg.Graph(BINDING, legs, revision=6, mission="t", notes=["the drawn leg"])
    for sid, (lid, s) in STOPS.items():
        x, y, h = g.legs[lid].line.point(s)
        g.put_station(tt.project_station(g, m, sid, (x, y, h)))
    return g


def lap(offset=(0.0, 0.0), drop_fork=None, started="2026-11-07T11:00:00"):
    """A C-B lap, from HOME and back to it, with fork episodes at each junction."""
    route = [(5, 0), (10, 0), (10, 10), (10, 20), (-5, 20), (-5, 8), (0, 5), (0, 0), (5, 0)]
    line = tg.Polyline(route)
    nodes = [5.0, 15.0, 25.0]  # J-A, J-B, J-E
    nodes += [line.project(0.0, 5.0, 30.0, None)[0], line.project(0.0, 0.0, 50.0, None)[0]]  # J-F, J-C
    rnd = random.Random(1)
    rec = tt.PassRecorder("C-B", started=started)
    s, t = 0.0, 0.0
    while s <= line.length:
        nlcp = 6 if any(k != drop_fork and n - 0.3 <= s < n for k, n in enumerate(nodes)) else 2
        rec.tick(t, s, nlcp)
        if round(s / 0.02) % 5 == 0:
            x, y, h = line.point(s)
            n = rnd.gauss(0, 0.005)
            rec.pose(t, x + offset[0] - n * math.sin(h), y + offset[1] + n * math.cos(h))
        s += 0.02
        t += 0.04
    return rec.to_dict()


def test_only_the_missing_legs_are_added_and_the_rest_is_kept_exactly():
    m = mission()
    base = base_graph(m)
    g, report = tm.merge_lap(base, lap(), m, R_POSES)
    assert set(g.legs) == set(BASE) | set(NEW), report
    for lid in BASE:
        assert g.legs[lid] is base.legs[lid], f"{lid} must not be rebuilt"
    for sid in STOPS:
        assert g.stations[sid] is base.stations[sid]
    assert set(base.legs) == set(BASE) and "R-1" not in base.stations, "the base is not changed"
    assert g.stations["R-1"].leg == "J-E:right>J-F" and g.stations["R-1"].s == pytest.approx(5.0, abs=0.1)
    assert g.stations["R-2"].s == pytest.approx(10.0, abs=0.1)
    assert g.legs["J-E:right>J-F"].fork_back_m == pytest.approx(0.3, abs=0.03)
    assert g.notes[0] == "the drawn leg" and "C-B added" in g.notes[1]


def test_every_trip_compiles_and_the_old_circuit_is_unchanged():
    m = mission()
    base = base_graph(m)
    g, _ = tm.merge_lap(base, lap(), m, R_POSES)
    assert tm.check_trips(g, m) == []
    before = trip_route.compile_trip(tripmod.Trip(m, "M", ["M1"]), m, base)
    after = trip_route.compile_trip(tripmod.Trip(m, "M", ["M1"]), m, g)
    assert after.stops == before.stops and after.events == before.events
    r = trip_route.compile_trip(tripmod.Trip(m, "B", ["B2"]), m, g)
    assert [s["id"] for s in r.stops] == ["HOME", "ATT", "R-2", "HOME"]
    assert [(e["id"], e["order"]) for e in r.events if e["kind"] == "order"] == [
        ("J-E", "right"),
        ("J-C", "left"),
    ], "no side armed at the merge into J-F: the AGV holds the tape it is on"


def test_the_base_graph_alone_cannot_run_the_new_circuit():
    m = mission()
    bad = dict(tm.check_trips(base_graph(m), m))
    assert set(bad) == {"B1", "B2"}


def test_a_lap_off_the_graph_is_refused_at_the_join():
    m = mission()
    with pytest.raises(tm.MergeError, match="ends .* m from where"):
        tm.merge_lap(
            base_graph(m),
            lap(offset=(0.0, 1.5)),
            m,
            {k: [v[0], v[1] + 1.5, v[2]] for k, v in R_POSES.items()},
        )


def test_a_missed_fork_is_refused():
    m = mission()
    with pytest.raises(tm.MergeError, match="missed MLS fork"):
        tm.merge_lap(base_graph(m), lap(drop_fork=2), m, R_POSES)


def test_a_stop_with_no_position_or_off_its_leg_is_refused():
    m = mission()
    with pytest.raises(tm.MergeError, match="no position for stop R-2"):
        tm.merge_lap(base_graph(m), lap(), m, {"R-1": R_POSES["R-1"]})
    with pytest.raises(tm.MergeError, match="wrong direction"):
        tm.merge_lap(base_graph(m), lap(), m, {**R_POSES, "R-2": [0.0, 20.0, 0.0]})
    with pytest.raises(tm.MergeError, match="from its leg"):
        tm.merge_lap(base_graph(m), lap(), m, {**R_POSES, "R-2": [0.0, 21.0, math.pi]})


def test_nothing_to_add_and_an_unknown_circuit_are_refused():
    m = mission()
    g, _ = tm.merge_lap(base_graph(m), lap(), m, R_POSES)
    with pytest.raises(tm.MergeError, match="already has every leg"):
        tm.merge_lap(g, lap(), m, R_POSES)
    with pytest.raises(tm.MergeError, match="not in the mission"):
        tm.merge_lap(base_graph(m), {**lap(), "circuit": "C-X"}, m, R_POSES)


# -- marks ---------------------------------------------------------------------------------------
MARKS = {
    "M1": {"role": "ATT", "marked": "2026-10-25T10:00:00"},
    "M2": {"marked": "2026-10-25T10:00:00"},  # before the lap: not this lap's
    "M9": {"marked": "2026-11-07T11:02:00"},
    "M10": {"marked": "2026-11-07T11:03:00"},
}
REC = {"started": "2026-11-07T11:00:00"}


def test_the_laps_own_marks_are_taken_in_the_order_they_were_made():
    assert tm.pick_marks(MARKS, REC, ["R-1", "R-2"]) == {"R-1": "M9", "R-2": "M10"}, (
        "M10 after M9, not as text"
    )


def test_the_wrong_number_of_marks_is_refused_by_name():
    with pytest.raises(tm.MergeError, match=r"2 mark\(s\) \(M9, M10\) for 3 stop"):
        tm.pick_marks(MARKS, REC, ["R-1", "R-2", "R-3"])


def test_marks_can_be_named():
    assert tm.pick_marks(MARKS, REC, ["R-1", "R-2"], ["M10", "M2"]) == {"R-1": "M10", "R-2": "M2"}
    with pytest.raises(tm.MergeError, match="no mark M77"):
        tm.pick_marks(MARKS, REC, ["R-1"], ["M77"])


# -- the command ---------------------------------------------------------------------------------
@pytest.fixture
def world(tmp_path, monkeypatch):
    m = mission()
    monkeypatch.setattr(tm.missions, "load_site", lambda _name: m)
    maps, state = str(tmp_path / "maps"), str(tmp_path / "state")
    (tmp_path / "maps" / "t" / "tapegraph").mkdir(parents=True)
    n = store.publish(maps, base_graph(m))
    store.write_active(state, "t", 1, n, "")
    store.save_pass(state, "t", 1, lap())
    store.save_marks(
        state,
        "t",
        1,
        {
            "M1": {
                "role": "ATT",
                "pose": [10.0, 3.0, math.pi / 2],
                "leg": "J-A:merge>J-B",
                "s": 3.0,
                "marked": "2026-10-25",
            },
            "M2": {"pose": R_POSES["R-1"], "leg": "", "s": 0.0, "marked": "2026-11-07T11:02:00"},
            "M3": {"pose": R_POSES["R-2"], "leg": "", "s": 0.0, "marked": "2026-11-07T11:03:00"},
        },
    )
    return maps, state, n


def args(maps, state, **over):
    base = {
        "circuit": "C-B",
        "mission": "t",
        "map": "",
        "map_revision": None,
        "base": None,
        "pass_started": "",
        "stops": "",
        "anchor": None,
        "maps_dir": maps,
        "state_dir": state,
        "publish": False,
    }
    return argparse.Namespace(**{**base, **over})


def test_a_report_writes_nothing(world):
    maps, state, n = world
    said = []
    assert tm.run(args(maps, state), said.append) is None
    assert store.list_revisions(maps, "t") == [n]
    assert not store.load_stations(state, "t", 1)
    assert not store.load_marks(state, "t", 1)["M2"].get("role")
    assert any("report only" in s for s in said) and any("R-1 = M2" in s for s in said)


def test_publish_writes_the_next_revision_and_the_stops_but_never_activates_it(world):
    maps, state, n = world
    said = []
    assert tm.run(args(maps, state, publish=True), said.append) == n + 1
    assert store.read_active(state)["graph_revision"] == n, "the owner activates it"
    g, _ = store.load(maps, "t", n + 1)
    assert set(g.legs) == set(BASE) | set(NEW) and {"R-1", "R-2"} <= set(g.stations)
    was, _ = store.load(maps, "t", n)
    assert "R-1" not in was.stations and len(was.legs) == len(BASE), "the old revision stays usable"
    marks = store.load_marks(state, "t", 1)
    assert marks["M2"]["role"] == "R-1" and marks["M2"]["leg"] == "J-E:right>J-F"
    assert store.load_stations(state, "t", 1)["R-2"]["mark"] == "M3"


def test_a_trip_that_fails_to_compile_refuses_the_publish(world, monkeypatch):
    maps, state, n = world
    monkeypatch.setattr(tm, "check_trips", lambda *_a: [("B1", "not taught")])
    with pytest.raises(tm.MergeError, match="B1: not taught"):
        tm.run(args(maps, state, publish=True), lambda _s: None)
    assert store.list_revisions(maps, "t") == [n]


def test_no_saved_pass_is_refused(world):
    maps, state, _n = world
    with pytest.raises(tm.MergeError, match="no saved C-X pass"):
        tm.run(args(maps, state, circuit="C-X"), lambda _s: None)


def test_named_anchors_override(world):
    maps, state, _n = world
    with pytest.raises(tm.MergeError, match="expected J-S=x,y"):
        tm.run(args(maps, state, anchor=["J-S"]), lambda _s: None)
    good = [
        f"{n}={x},{y}"
        for n, x, y in (("J-A", 10, 0), ("J-B", 10, 10), ("J-E", 10, 20), ("J-F", 0, 5), ("J-C", 0, 0))
    ]
    said = []
    tm.run(args(maps, state, anchor=good), said.append)
    assert any("from its position" in s for s in said), "all anchored: matched by position"


# -- the site mission ----------------------------------------------------------------------------
def test_the_repo_mission_joins_row_2_at_j_ml_with_no_j_r2e():
    m = missions.load_site("site-103")
    assert "J-R2E" not in m["JUNCTIONS"] and m["JUNCTIONS"]["J-LV"]["laid"]
    btu = [leg["id"] for leg in m["CIRCUITS"]["C-BTU"]["legs"]]
    assert btu == [
        "J-BMERGE:merge>J-N",
        "J-N:straight>J-S",
        "J-S:straight>X2",
        "X2:cross>J-LV",
        "J-LV:right>J-ML",
        "J-ML:merge>J-STEM",
        "J-STEM:merge>J-SMERGE",
        "J-SMERGE:merge>J-SPLIT",
        "J-SPLIT:right>J-BMERGE",
    ]
    assert m["CIRCUITS"]["C-BTU"]["legs"][4]["stops"] == [f"R2-{n}" for n in range(1, 9)]
    # The same tape home as C-MRU, the same steer; Right at J-ML holds the row 2 tape while the trunk
    # tape closes in from its left, as on both laps of 2026-11-07.
    assert m["CIRCUITS"]["C-BTU"]["steers"] == {**m["CIRCUITS"]["C-MRU"]["steers"], "J-ML:merge": "right"}


def test_the_repo_mission_leaves_the_mru_legs_as_they_were():
    m = missions.load_site("site-103")
    assert sorted(leg["id"] for leg in m["CIRCUITS"]["C-MRU"]["legs"]) == sorted(
        [
            "J-BMERGE:merge>J-N",
            "J-N:right>X1",
            "X1:cross>J-ML",
            "J-ML:merge>U-MRU",
            "U-MRU:pivot>J-ML",
            "J-ML:left>J-STEM",
            "J-STEM:merge>J-SMERGE",
            "J-SMERGE:merge>J-SPLIT",
            "J-SPLIT:right>J-BMERGE",
        ]
    )
