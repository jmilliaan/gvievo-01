"""A trip on one S axis (tracked plan 4, section 2.3): amr_line.trip_route on the site_fixture
circuit. Pure: no job, no clock."""

import pytest
from site_fixture import AREAS, TAUGHT, graph, site  # noqa: E402

from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import trip as tr  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402


def trip(m, *machines):
    return tr.Trip(m, "M", list(machines))


def plain():
    """No machine has a U-turn point: every trip turns at the tape end."""
    m = site(uturn_points={},
             groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"},
                                                          "M2": {"release": "MW-2", "take": "ME-2"}}}})
    return m, graph(m, skip=("UT-M1", "UT-M2"))


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


def test_a_high_speed_area_becomes_ranges_wherever_the_trip_runs_inside_it():
    m = site(trip_calls=1)
    r = trr.compile_trip(trip(m, "M1"), m, graph(m), areas=AREAS)
    # out along x 11..17 (S 21..27, but from 21.25: 1 m after the corner onto the line at S 20 the AGV
    # is still straightening, trr.CURVE_SETTLE_M); back over the same tape after the cut at S 31
    assert r.zones == [(pytest.approx(21.25), pytest.approx(27.0), "Z-LINE", "high"),
                       (pytest.approx(35.0), pytest.approx(41.0), "Z-LINE", "high")]
    assert trr.compile_trip(trip(m, "M1"), m, graph(m)).zones == []
    # a corner of an area clipping the tape for less than AREA_MIN_M is no zone
    nick = {"N": {"polygon": [(4.0, -0.2), (4.5, -0.2), (4.5, 0.2), (4.0, 0.2)], "kind": "high"}}
    assert trr.compile_trip(trip(m, "M1"), m, graph(m), areas=nick).zones == []
    assert trr.inside([(0, 0), (2, 0), (2, 2), (0, 2)], 1, 1)
    # an unknown kind is no area at all (NORMAL), a missing one is HIGH
    odd = {"Z-LINE": {**AREAS["Z-LINE"], "kind": "turbo"}}
    assert trr.compile_trip(trip(m, "M1"), m, graph(m), areas=odd).zones == []
    bare = {"Z-LINE": {"polygon": AREAS["Z-LINE"]["polygon"]}}
    assert trr.compile_trip(trip(m, "M1"), m, graph(m), areas=bare).zones == r.zones
    assert not trr.inside([(0, 0), (2, 0), (1, 2)], 1.9, 1.9)


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
    assert set(TAUGHT) >= {"UT-M1", "UT-M2"}


def test_a_steered_merge_is_armed_like_an_order_and_keeps_its_leg_name():
    import copy

    from agv_core import mission as missions  # noqa: PLC0415
    from site_fixture import DOC  # noqa: PLC0415
    d = copy.deepcopy(DOC)
    d["circuits"]["C-M"][1]["steer"] = "left"           # J-A, the merge after HOME
    m = missions.parse_site(d)
    assert [leg["id"] for leg in m["CIRCUITS"]["C-M"]["legs"]][0] == "J-A:merge>J-B"
    r = trr.compile_trip(trip(m, "M1"), m, graph(m))
    assert [(e["id"], e["order"]) for e in r.events if e["kind"] == "order"] == [
        ("J-A", "left"), ("J-B", "right"), ("J-C", "left")]
    plain = site()
    r = trr.compile_trip(trip(plain, "M1"), plain, graph(plain))
    assert [e["id"] for e in r.events if e["kind"] == "order"] == ["J-B", "J-C"], "unsteered: no order"


# A NORMAL+ patch over x 13..15 of Z-LINE: S 23..25 on the way out, 37..39 on the way back.
PATCH = {"P-TRAFFIC": {"polygon": [(12.98, 9.5), (15.02, 9.5), (15.02, 10.5), (12.98, 10.5)], "kind": "plus"}}


def test_a_normal_plus_area_over_a_high_one_wins_where_they_overlap():
    m = site(trip_calls=1)
    r = trr.compile_trip(trip(m, "M1"), m, graph(m), areas={**AREAS, **PATCH})
    out = [z for z in r.zones if z[0] < 30.0]
    assert [(z[2], z[3]) for z in out] == [("Z-LINE", "high"), ("P-TRAFFIC", "plus"), ("Z-LINE", "high")]
    assert out[0][0] == pytest.approx(21.25) and out[2][1] == pytest.approx(27.0)
    assert out[1][0] == pytest.approx(23.0, abs=0.06) and out[1][1] == pytest.approx(25.0, abs=0.06)
    # contiguous: the engine never sees a gap between HIGH and NORMAL+ on one straight
    assert out[0][1] == out[1][0] and out[1][1] == out[2][0]
    back = [(z[2], z[3]) for z in r.zones if z[0] >= 30.0]
    assert back == [("Z-LINE", "high"), ("P-TRAFFIC", "plus"), ("Z-LINE", "high")]


def test_a_short_normal_plus_patch_still_wins_and_alone_is_a_zone_by_the_same_rule():
    m = site(trip_calls=1)
    short = {"P": {"polygon": [(13.98, 9.5), (14.48, 9.5), (14.48, 10.5), (13.98, 10.5)], "kind": "plus"}}
    r = trr.compile_trip(trip(m, "M1"), m, graph(m), areas={**AREAS, **short})
    kinds = [(z[2], z[3]) for z in r.zones if z[0] < 30.0]
    assert kinds == [("Z-LINE", "high"), ("P", "plus"), ("Z-LINE", "high")], "0.5 m inside HIGH: kept"
    # alone, 0.5 m of tape is an area's corner clipping it, as for HIGH: no zone
    assert trr.compile_trip(trip(m, "M1"), m, graph(m), areas=short).zones == []
    only = trr.compile_trip(trip(m, "M1"), m, graph(m), areas=PATCH).zones
    assert [(z[2], z[3]) for z in only] == [("P-TRAFFIC", "plus")] * 2


def test_curved_tape_and_the_metre_after_it_are_no_zone_even_inside_an_area():
    """2026-11-11: STR-TO-ATT began on the end of the bend after HOME-N2, HS-BOIAC-MRU on the BTU curve
    into J-ML; the AGV sped up still turning and the curve guard took the whole zone away."""
    m = site(trip_calls=1)
    g = graph(m)
    r = trr.compile_trip(trip(m, "M1"), m, g)
    samples = trr._samples(r.segments, trr.AREA_STEP_M)
    bent = trr.curved(samples, 0.25)
    off = [S for (S, *_), b in zip(samples, bent, strict=True) if b]
    # the corner at S 20 (J-A:merge>J-B onto J-B:right>U): from half a chord before it to the settle after
    assert min(S for S in off if S > 15) == pytest.approx(20.0 - trr.CURVE_CHORD_M / 2, abs=0.06)
    settled = 20.0 + trr.CURVE_CHORD_M / 2 + trr.CURVE_SETTLE_M
    assert max(S for S in off if S < 25) == pytest.approx(settled, abs=0.06)
    assert not any(b for (S, *_), b in zip(samples, bent, strict=True) if 22.0 < S < 30.0), "straight"
    # the cut at the mid-line U-turn reverses the heading: a curve too
    assert any(b for (S, *_), b in zip(samples, bent, strict=True) if abs(S - 31.0) < 0.1)
    # an area over the corner: before it a zone, through it and the settle none, after it too short
    # (and on the way back, straight through the same box at S 40: a zone)
    corner = {"C": {"polygon": [(9.0, 8.0), (12.0, 8.0), (12.0, 11.0), (9.0, 11.0)], "kind": "high"}}
    zones = trr.compile_trip(trip(m, "M1"), m, g, areas=corner).zones
    assert [(z[2], round(z[0], 1)) for z in zones] == [("C", 18.0), ("C", 40.0)]
    assert zones[0][1] < 20.0 - trr.CURVE_CHORD_M / 2 + 0.01
    # a looser limit (a gentle site) keeps the old behaviour on this straight
    assert trr.area_ranges(r.segments, AREAS, kappa_max=100.0)[0][0] == pytest.approx(21.0)
