"""A trip on one S axis (tracked plan 4, section 2.3): amr_line.trip_route on the site_fixture
circuit. Pure: no job, no clock."""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from site_fixture import TAUGHT, graph, site  # noqa: E402

from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import trip as tr  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402


def trip(m, *machines):
    return tr.Trip(m, "M", list(machines))


def plain():
    """No machine has a U-turn point: every trip turns at the tape end."""
    m = site(uturn_points={}, zones={},
             groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"},
                                                          "M2": {"release": "MW-2", "take": "ME-2"}}}})
    return m, graph(m, skip=("UT-M1", "UT-M2", "ZA", "ZB"))


def by(route, kind):
    return [e for e in route.events if e["kind"] == kind]


def test_a_tape_end_trip_is_the_whole_circuit_with_only_its_stops():
    m, g = plain()
    r = trr.compile_trip(trip(m, "M2"), m, g)
    assert [(s["id"], round(s["S"], 2), s["role"]) for s in r.stops] == [
        ("HOME", 5.0, "start"), ("ATT", 13.0, "attach"), ("MW-2", 34.0, "machine"),
        ("ME-2", 46.0, "machine"), ("HOME", 85.0, "home")]
    assert r.uturn["mode"] == "tapeend" and r.uturn["id"] == "U" and r.uturn["S"] == pytest.approx(40.0)
    assert r.uturn["lead_m"] == 1.5 and r.zones == []
    # orders only at the diverges, armed junction_lead_m before the fork, never before the node behind
    assert [(e["id"], e["order"], round(e["S"], 2)) for e in by(r, "order")] == [
        ("J-B", "right", 18.6), ("J-C", "left", 78.6)]
    kinds = [(n["id"], n["kind"], n["fork"]) for n in r.nodes]
    assert kinds == [("J-A", "junction", True), ("J-B", "junction", True), ("U", "uturn", False),
                     ("J-C", "junction", True)]
    assert [e["kind"] for e in r.events] == ["stop", "order", "stop", "uturn", "stop", "order", "stop"]


def test_a_mid_line_trip_is_cut_at_its_u_turn_point_and_enters_the_return_leg_there():
    m = site(trip_calls=1)
    r = trr.compile_trip(trip(m, "M1"), m, graph(m))
    seg = [(leg.id, round(lo, 2), round(hi, 2)) for _s0, leg, lo, hi in r.segments]
    assert seg == [("J-C:left>J-A", 0.0, 10.0), ("J-A:merge>J-B", 0.0, 10.0), ("J-B:right>U", 0.0, 11.0),
                   ("U:pivot>J-C", 9.0, 40.0), ("J-C:left>J-A", 0.0, 10.0)]
    assert [(s["id"], round(s["S"], 2)) for s in r.stops] == [
        ("HOME", 5.0), ("ATT", 13.0), ("MW-1", 28.0), ("ME-1", 34.0), ("HOME", 67.0)]
    ut = next(n for n in r.nodes if n["kind"] == "uturn")
    assert ut["id"] == "UT-M1" and ut["mirror"] and ut["S"] == pytest.approx(31.0)
    assert r.uturn["mode"] == "midline" and r.uturn["direction"] == "cw"
    # the same floor point on both sides of the cut
    assert r.point(30.9)[:2] == pytest.approx(r.point(31.1)[:2], abs=1e-6)


def test_two_calls_turn_after_the_farthest_release():
    m = site()
    r = trr.compile_trip(trip(m, "M1", "M2"), m, graph(m))
    assert r.uturn["id"] == "UT-M2"
    assert [s["id"] for s in r.stops] == ["HOME", "ATT", "MW-1", "MW-2", "ME-2", "ME-1", "HOME"]
    me2 = r.stop("ME-2")["S"]
    assert me2 == pytest.approx(37.0 + 3.0)       # entered at s 3, ME-2 at s 6


def test_a_u_turn_point_before_its_release_is_refused():
    m = site()
    g = graph(m, skip=("UT-M2",))
    x, y, h = g.legs["J-B:right>U"].line.point(12.0)       # before MW-2 (14)
    from amr_line import tape_teach as tt  # noqa: PLC0415
    g.put_station(tt.project_station(g, m, "UT-M2", (x, y, h)))
    with pytest.raises(tg.RouteError, match="before M2's release MW-2"):
        trr.compile_trip(trip(m, "M2"), m, g)


def test_a_take_back_before_the_u_turn_points_return_is_refused():
    m = site()
    g = graph(m, skip=("ME-1",))
    from amr_line import tape_teach as tt  # noqa: PLC0415
    x, y, h = g.legs["U:pivot>J-C"].line.point(5.0)        # UT-M1 enters the return leg at 9
    g.put_station(tt.project_station(g, m, "ME-1", (x, y, h)))
    with pytest.raises(tg.RouteError, match="ME-1 .* before the U-turn point's return"):
        trr.compile_trip(trip(m, "M1"), m, g)


def test_what_is_not_taught_is_named_and_only_the_trips_own_stations_count():
    m = site()
    with pytest.raises(tg.RouteError, match="not taught: MW-1, U-turn point UT-M1"):
        trr.compile_trip(trip(m, "M1"), m, graph(m, skip=("MW-1", "UT-M1")))
    # MW-2 / ME-2 / UT-M2 are another machine's: a trip to M1 does not need them
    trr.compile_trip(trip(m, "M1"), m, graph(m, skip=("MW-2", "ME-2", "UT-M2")))


def test_a_zone_lies_between_its_points_and_a_reversed_one_is_refused():
    m = site()
    r = trr.compile_trip(trip(m, "M1"), m, graph(m))
    assert r.zones == [(pytest.approx(21.0), pytest.approx(27.0), "Z-LINE")]
    g = graph(m, skip=("ZA", "ZB"))
    from amr_line import tape_teach as tt  # noqa: PLC0415
    for sid, s in (("ZA", 7.0), ("ZB", 1.0)):
        x, y, h = g.legs["J-B:right>U"].line.point(s)
        g.put_station(tt.project_station(g, m, sid, (x, y, h)))
    with pytest.raises(tg.RouteError, match="Z-LINE: its end ZB is not after its start ZA"):
        trr.compile_trip(trip(m, "M1"), m, g)
    r = trr.compile_trip(trip(m, "M1"), m, graph(m, skip=("ZB",)))
    assert r.zones == [] and any("ZB not taught - NORMAL there" in n for n in r.notes)


def test_the_locator_runs_on_a_trip_route_and_mirrors_at_a_mid_line_u_turn():
    m = site(trip_calls=1)
    r = trr.compile_trip(trip(m, "M1"), m, graph(m))
    loc = tl.TapeLocator(r, tl.Params())
    loc.readiness(True)
    loc.start(r.S_start, 0.02, 0.0, 0.0)
    loc.predict(1.0, 25.97)                     # stopped 3 cm short of the point (S 31)
    assert loc.S == pytest.approx(30.97)
    assert loc.uturn_done("UT-M1") and loc.S == pytest.approx(31.03)
    assert loc.sigma == pytest.approx(0.02 + 0.01 * 25.97), "a mid-line pivot measures nothing"
    # the floor point it stands on is the same before and after
    assert r.point(30.97)[:2] == pytest.approx(r.point(31.03)[:2], abs=1e-6)
    # AMCL corrections project inside the cut windows: on the return leg, not the way out
    x, y, _ = r.point(33.0)
    hit = r.project(x, y, 31.5, 34.5, hint=33.0)
    assert hit[0] == pytest.approx(33.0, abs=1e-6)


def test_the_teaching_positions_of_the_fixture_are_consistent():
    assert set(TAUGHT) >= {"UT-M1", "UT-M2", "ZA", "ZB"}
