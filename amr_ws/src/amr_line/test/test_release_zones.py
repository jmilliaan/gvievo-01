"""trip_route.release_zones: where a trip crosses a RELEASE zone (contract v1.6 section 13), on the
site_fixture circuit. HOME S 5 (x 5 on the home leg), ATT S 13 (y 3 up J-A:merge>J-B), MW-2 S 34,
the tape end S 40, ME-2 S 46, HOME again S 85 (in from (0,0) along y 0)."""

import pytest
from site_fixture import graph, site  # noqa: E402

from amr_line import tape_graph as tg  # noqa: E402
from amr_line import trip as tr  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402

FRONT, TAIL, LEAD = 0.6, 4.8, 10.0
BOX = lambda x0, x1, y0, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]  # noqa: E731


def route(zones, machine="M2"):
    m = site(uturn_points={},
             groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"},
                                                          "M2": {"release": "MW-2", "take": "ME-2"}}}})
    g = graph(m, skip=("UT-M1", "UT-M2"))
    r = trr.compile_trip(tr.Trip(m, "M", [machine]), m, g)
    return trr.release_zones(r.segments, r.stops, zones, FRONT, TAIL, LEAD)


def test_no_zone_no_crossing():
    assert route({}) == []


def test_leaving_the_attach_stop_asks_there_and_releases_when_the_tail_is_clear():
    [z] = route({"C": BOX(9, 11, 4, 8)})           # just past ATT on the way out
    assert z["zone"] == "C" and z["ask_at"] == "ATT" and z["S_ask"] == pytest.approx(13.0)
    assert z["S_in"] == pytest.approx(14.0 - FRONT, abs=0.06)     # front reaches y 4
    assert z["S_out"] == pytest.approx(18.0 + TAIL, abs=0.06)     # last trolley past y 8
    assert not z["home"]


def test_home_bound_asks_on_the_move_and_releases_at_home():
    [z] = route({"C": BOX(-1, 1, 2, 6)})           # on the way down to HOME, nothing after but HOME
    assert z["home"] and z["ask_at"] is None
    assert z["S_in"] == pytest.approx(74.0 - FRONT, abs=0.06)
    assert z["S_ask"] == pytest.approx(z["S_in"] - LEAD)


def test_the_home_leg_before_the_start_is_not_driven():
    # x 1..3 on the home leg lies BEFORE the HOME stop at the start (behind the AGV) and after J-C at the
    # end: only the end counts, as a home-bound crossing.
    [z] = route({"C": BOX(1, 3, -1, 1)})
    assert z["home"] and z["S_in"] > 79.0


def test_two_runs_the_train_never_fully_leaves_are_one_crossing():
    # in at y 4..5 and again at y 6..7 on the way out: the gap (1 m) is shorter than the train
    [z] = route({"C": [(9, 4), (11, 4), (11, 5), (10.2, 5), (10.2, 6), (11, 6), (11, 7), (9, 7)]})
    assert z["S_out"] == pytest.approx(17.0 + TAIL, abs=0.06)


def test_a_stop_inside_a_zone_is_refused():
    with pytest.raises(tg.RouteError, match="MW-2"):
        route({"C": BOX(23, 25, 9, 11)})


def test_crossings_come_in_route_order_with_one_zone_per_crossing():
    zs = route({"OUT": BOX(9, 11, 4, 8), "HOME": BOX(-1, 1, 2, 6)})
    assert [z["zone"] for z in zs] == ["OUT", "HOME"]
    assert [z["home"] for z in zs] == [False, True]


def test_compile_trip_carries_them_and_none_without_zones():
    m = site(uturn_points={},
             groups={"M": {"circuit": "C-M", "machines": {"M2": {"release": "MW-2", "take": "ME-2"}}}})
    g = graph(m, skip=("UT-M1", "UT-M2"))
    r = trr.compile_trip(tr.Trip(m, "M", ["M2"]), m, g, release={"C": BOX(9, 11, 4, 8)})
    assert [z["zone"] for z in r.release_zones] == ["C"]
    assert trr.compile_trip(tr.Trip(m, "M", ["M2"]), m, g).release_zones == []
