import math

import numpy as np
import pytest
from amr_maps.generate_sim_factory import build
from amr_maps.grid import Grid, GridMeta
from amr_navigation.compiler import compile_route
from amr_navigation.route import Limits, MapRef, Route, RouteError, StartPose, Step
from amr_navigation.validate import validate

from amr_navigation import footprint as fpmod
from amr_navigation import store

FP = fpmod.Footprint(((-0.5, -0.35), (1.1, -0.35), (1.1, 0.35), (-0.5, 0.35)), 0.20)


class Manifest:  # the fields validate() reads from amr_mission.map_bundle.Manifest
    map_id, revision, sha256 = "sim_factory", 1, "abc123"


def route(steps, start=(0.0, 0.0, 0.0), repeat=1, sha="abc123") -> Route:
    return Route("r1", MapRef("sim_factory", 1, sha), StartPose(*start), steps, Limits(), repeat_count=repeat)


def straight(sid, x, y):
    return Step(sid, "straight", to=(x, y))


def rotate(sid, direction, angle):
    return Step(sid, "rotate", direction=direction, angle_deg=angle)


# ---- compiler ----------------------------------------------------------------


@pytest.mark.parametrize("direction", ["cw", "ccw"])
@pytest.mark.parametrize("angle", [45, 90, 180, 270])
def test_all_eight_turns_keep_full_magnitude(direction, angle):
    c = compile_route(route([rotate("t", direction, angle)]))
    st = c.steps[0]
    expected = math.radians(angle) * (1 if direction == "ccw" else -1)
    assert st.signed_angle_rad == pytest.approx(expected)
    assert st.end[2] == pytest.approx(math.atan2(math.sin(expected), math.cos(expected)))
    assert st.time_allowance_s > abs(expected) / 0.30


def test_cw_270_is_not_ccw_90():
    a = compile_route(route([rotate("t", "cw", 270)])).steps[0]
    b = compile_route(route([rotate("t", "ccw", 90)])).steps[0]
    assert a.end[2] == pytest.approx(b.end[2])  # same final heading
    assert a.signed_angle_rad == pytest.approx(-3 * math.pi / 2)
    assert b.signed_angle_rad == pytest.approx(math.pi / 2)


def test_spec_example_ends_facing_west():
    r = route(
        [
            straight("s1", 3.0, 0.0),
            rotate("s2", "ccw", 90),
            straight("s3", 3.0, 2.0),
            rotate("s4", "cw", 270),
            straight("s5", 1.0, 2.0),
        ],
    )
    c = compile_route(r)
    assert c.steps[1].end[2] == pytest.approx(math.pi / 2)
    assert abs(c.steps[3].end[2]) == pytest.approx(math.pi)  # north -> west via the long clockwise sweep
    assert c.end[:2] == pytest.approx((1.0, 2.0))
    assert c.total_length_m == pytest.approx(7.0)
    assert len(c.steps[0].samples) == 61 and c.steps[0].samples[-1][:2] == pytest.approx((3.0, 0.0))


def test_bend_is_rejected_not_rounded():
    with pytest.raises(RouteError) as e:
        compile_route(route([straight("s1", 3.0, 0.02)]))
    assert e.value.step_id == "s1" and "turn" in str(e.value)


def test_backwards_and_zero_length_rejected():
    with pytest.raises(RouteError, match="forward"):
        compile_route(route([straight("s1", -1.0, 0.0)]))
    with pytest.raises(RouteError, match="forward"):
        compile_route(route([straight("s1", 0.01, 0.0)]))


def test_bad_angles_and_directions_rejected():
    with pytest.raises(RouteError, match="angle_deg"):
        compile_route(route([rotate("t", "cw", 60)]))
    with pytest.raises(RouteError, match="direction"):
        compile_route(route([rotate("t", "left", 90)]))
    with pytest.raises(RouteError, match="no steps"):
        compile_route(route([]))
    with pytest.raises(RouteError, match="duplicate"):
        compile_route(route([rotate("t", "cw", 90), rotate("t", "cw", 90)]))


def test_arbitrary_start_heading_then_explicit_turns():
    r = route(
        [straight("s1", 2 * math.cos(0.7), 2 * math.sin(0.7)), rotate("s2", "ccw", 45)],
        start=(0.0, 0.0, math.degrees(0.7)),
    )
    c = compile_route(r)
    assert c.steps[0].length_m == pytest.approx(2.0)
    assert c.end[2] == pytest.approx(0.7 + math.pi / 4)


def test_closure_detection():
    sq = [
        straight("a", 2.0, 0.0),
        rotate("b", "ccw", 90),
        straight("c", 2.0, 2.0),
        rotate("d", "ccw", 90),
        straight("e", 0.0, 2.0),
        rotate("f", "ccw", 90),
        straight("g", 0.0, 0.0),
        rotate("h", "ccw", 90),
    ]
    assert compile_route(route(sq)).closes
    assert not compile_route(route(sq[:-1])).closes


# ---- yaml round trip --------------------------------------------------------------


def test_yaml_round_trip():
    r = route([straight("s1", 3.0, 0.0), rotate("s2", "cw", 270)], repeat=2)
    back = Route.loads(r.dumps())
    assert back.to_dict() == r.to_dict()
    assert back.steps[1].angle_deg == 270 and back.steps[1].direction == "cw"
    with pytest.raises(RouteError, match="schema_version"):
        Route.loads("schema_version: 7\n")


# ---- footprint sweeps and validation ----------------------------------------------


def test_footprint_rasterize_and_reach():
    g = Grid(np.zeros((100, 100), dtype=np.int8), GridMeta(0.05, -2.5, -2.5))
    mask = fpmod.swept_line(g, fpmod.Footprint(FP.polygon, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    area = mask.sum() * 0.05 * 0.05
    assert area == pytest.approx(1.6 * 0.7, rel=0.05)
    assert FP.reach_m == pytest.approx(math.hypot(1.1, 0.35))
    disc = fpmod.swept_rotation(g, fpmod.Footprint(FP.polygon, 0.0), (0.0, 0.0))
    assert disc.sum() * 0.0025 == pytest.approx(math.pi * FP.reach_m**2, rel=0.05)
    assert FP.as_costmap_string().startswith("[[-0.500, -0.350]")


def test_valid_route_in_the_aisle():
    g = build()
    r = route([straight("s1", 15.0, 0.0), rotate("s2", "ccw", 180), straight("s3", 2.0, 0.0)])
    v = validate(r, Manifest, g, FP)
    assert v.ok, [i.to_dict() for i in v.issues]
    assert v.compiled.total_length_m == pytest.approx(28.0)


def test_line_through_a_rack_is_rejected():
    g = build()
    r = route(
        [straight("s1", 5.0, 0.0), rotate("s2", "ccw", 90), straight("s3", 5.0, 4.0)]
    )  # north into rack row C
    v = validate(r, Manifest, g, FP)
    assert not v.ok
    codes = {(i.code, i.step_id) for i in v.issues}
    assert ("clearance", "s3") in codes


def test_rotation_sweep_next_to_a_wall_is_rejected():
    g = build()
    # Drive to 0.8 m from the west wall's inner face (x = -2.8) facing it: the 1.1 m nose sweeps into it.
    r = route([straight("s1", -2.0, 0.0), rotate("s2", "cw", 180)], start=(0.0, 0.0, 180.0))
    v = validate(r, Manifest, g, FP)
    assert not v.ok
    assert any(i.code == "clearance" and i.step_id == "s2" for i in v.issues)


def test_unknown_cells_block_and_keepout_blocks():
    g = build()
    g.data[
        g.world_to_cell(8.0, 0.0)[0] - 3 : g.world_to_cell(8.0, 0.0)[0] + 3,
        g.world_to_cell(8.0, 0.0)[1] - 3 : g.world_to_cell(8.0, 0.0)[1] + 3,
    ] = -1
    v = validate(route([straight("s1", 12.0, 0.0)]), Manifest, g, FP)
    assert any("unknown" in i.message and i.step_id == "s1" for i in v.issues)
    g2 = build()
    ko = Grid(np.zeros(g2.data.shape, dtype=np.int8), g2.meta)
    r, c = g2.world_to_cell(6.0, 0.0)
    ko.data[r - 2 : r + 2, c - 2 : c + 2] = 100
    v = validate(route([straight("s1", 12.0, 0.0)]), Manifest, g2, FP, keepout=ko)
    assert any("keepout" in i.message for i in v.issues)


def test_map_reference_and_repeat_rules():
    g = build()
    v = validate(route([straight("s1", 5.0, 0.0)], sha="other"), Manifest, g, FP)
    assert any(i.code == "map_hash" for i in v.issues)
    r = route([straight("s1", 5.0, 0.0)])
    r.map.revision = 2
    assert any(i.code == "map_ref" for i in validate(r, Manifest, g, FP).issues)
    v = validate(route([straight("s1", 5.0, 0.0)], repeat=3), Manifest, g, FP)
    assert any(i.code == "repeat" for i in v.issues)
    assert any(
        i.code == "repeat"
        for i in validate(route([straight("s1", 5.0, 0.0)], repeat=0), Manifest, g, FP).issues
    )


# ---- stores -----------------------------------------------------------------------


def test_route_store_revisions(tmp_path):
    r = route([straight("s1", 5.0, 0.0)])
    rev, path, sha = store.save_route(str(tmp_path), r)
    assert rev == 1 and path.endswith("rev1.yaml") and len(sha) == 64
    rev2, _, sha2 = store.save_route(str(tmp_path), route([straight("s1", 6.0, 0.0)]))
    assert rev2 == 2 and sha2 != sha
    assert store.list_routes(str(tmp_path), "sim_factory") == {"r1": [1, 2]}
    back, back_sha = store.load_route(str(tmp_path), "sim_factory", "r1", 1)
    assert back.revision == 1 and back_sha == sha
    p = store.save_mission(str(tmp_path), "m1", "sim_factory", 1, "abc123", "r1", 2, sha2)
    m = store.load_mission(str(tmp_path), "m1")
    assert m["route"] == {"id": "r1", "revision": 2, "sha256": sha2} and p.endswith("m1.yaml")
    assert [x["mission_id"] for x in store.list_missions(str(tmp_path))] == ["m1"]
    with pytest.raises(store.StoreError):
        store.save_mission(str(tmp_path), "../x", "sim_factory", 1, "a", "r1", 1, "b")
