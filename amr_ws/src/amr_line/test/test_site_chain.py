"""A chain of orders (trip_route.decision_points, site_run._chain_tick): J-N then J-S on site 103,
whose forks have 0.15 m of one tape between them, driven on the MLS readings of the C-BTU teach
lap of 2026-11-07 (golden/lap2_jn_js_x2.json).

Between the two forks the STU tape lies against the lane and reads as one track sliding 16 mm to
the left; when it splits, straight on (the nearer track) is a coin toss. The trip holds LEFT
through J-N and RIGHT through J-S, RIGHT armed the moment J-N's order is taken, wherever S is.

The chain circuit, taught exactly (FORK_BACK as on g7):

    J-C:left>J-A      (0,0)->(10,0)                 HOME at 5
    J-A:merge>J-N     (10,0)->(10,10)               J-N's fork over its last 0.40 m
    J-N:straight>J-S  (10,10)->(10,10.5)            J-S's fork over its last 0.35 m: 0.15 m of one tape
    J-S:straight>X    (10,10.5)->(10,11.3)
    X:cross>J-C       (10,11.3)->(10,20)->(0,20)->(0,0)   ATT at 3, B-1 at 10
"""
import copy
import json
import pathlib

import pytest
from agv_core import config as vehicle  # noqa: E402
from agv_core import mission as missions  # noqa: E402

from amr_line import (
    branch,  # noqa: E402
    site_run,  # noqa: E402
)
from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import tape_teach as tt  # noqa: E402
from amr_line import trip as tripmod  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402

LAP2 = json.loads((pathlib.Path(__file__).parent / "golden" / "lap2_jn_js_x2.json").read_text())
READINGS = [(o, n, list(t)) for o, n, t in LAP2["readings"]]
JN, JS, X2 = (LAP2["landmarks"][k] for k in ("J-N", "J-S", "X2"))
STEP_M = 0.008                       # 0.4 m/s at 50 Hz

DOC = {
    "schema": "site-4", "mission_name": "chain", "home": "HOME", "attach": "ATT", "trip_calls": 1,
    "stop_distance_m": 0.5, "cruise_mps": 0.4,
    "junctions": {"J-A": {"shape": "Y", "laid": True}, "J-N": {"shape": "Y", "laid": True},
                  "J-S": {"shape": "Y", "laid": True}, "X": {"shape": "X", "laid": True},
                  "J-C": {"shape": "Y", "laid": True}},
    "uturns": {},
    "circuits": {"C-B": [{"stop": "HOME"}, {"junction": "J-A", "order": "merge"},
                         {"junction": "J-N", "order": "straight", "steer": "left"},
                         {"junction": "J-S", "order": "straight", "steer": "right"},
                         {"junction": "X", "order": "cross"}, {"stop": "ATT"}, {"stop": "B-1"},
                         {"junction": "J-C", "order": "left"}, {"stop": "HOME"}]},
    "groups": {"B": {"circuit": "C-B", "machines": {"B1": {"swap": "B-1"}}}},
    "uturn_points": {},
}
TRUE = {
    "J-C:left>J-A": ([(0, 0), (10, 0)], 0.4),
    "J-A:merge>J-N": ([(10, 0), (10, 10)], 0.4),
    "J-N:straight>J-S": ([(10, 10), (10, 10.5)], 0.35),
    "J-S:straight>X": ([(10, 10.5), (10, 11.3)], 0.05),
    "X:cross>J-C": ([(10, 11.3), (10, 20), (0, 20), (0, 0)], 0.4),
}
TAUGHT = {"HOME": ("J-C:left>J-A", 5.0), "ATT": ("X:cross>J-C", 3.0), "B-1": ("X:cross>J-C", 10.0)}


def site(**over):
    d = copy.deepcopy(DOC)
    d.update(over)
    return missions.parse_site(d)


def graph(m, skip=()):
    legs = []
    for lid, (pts, back) in TRUE.items():
        frm, rest = lid.split(":")
        order, to = rest.split(">")
        legs.append(tg.Leg(lid, frm, order, to, tg.resample(pts), end_kind="fork", fork_back_m=back))
    g = tg.Graph({"map_id": "t", "map_revision": 1, "map_sha256": "ab" * 32}, legs)
    for sid, (lid, s) in TAUGHT.items():
        if sid in skip:
            continue
        x, y, h = g.legs[lid].line.point(s)
        g.put_station(tt.project_station(g, m, sid, (x, y, h)))
    return g


def route(m=None, lead=1.0):
    m = m or site()
    return trr.compile_trip(tripmod.Trip(m, "B", ["B1"]), m, graph(m), junction_lead_m=lead)


def lane(o, tracks):
    """Which reading is the lane: the left tape at J-N (R2434 leaves right), the right one at J-S
    (the STU tape leaves left), the one near the centre at X2."""
    if JN[0] <= o <= JN[1]:
        return max(tracks)
    if JS[0] <= o <= JS[1]:
        return min(tracks)
    return min(tracks, key=abs)


def sensor(tracks, nlcp):
    return {"nlcp": nlcp, "has_track": bool(tracks), "track_level": 5,
            "tracks": [{"index": i + 1, "pos_mm": p, "width": 10} for i, p in enumerate(tracks)]}


def drive(readings=READINGS, bias=0.0, sigma=0.03, until=2.2):
    """SiteRun alone, fed the lap's readings by wheel travel, the follower's choice made the way
    the job makes it. Returns (run, [(offset, tracks, followed, intent)] at every two-track reading)."""
    m = site()
    r = route(m)
    run = site_run.SiteRun(m, tripmod.Trip(m, "B", ["B1"]), r, tl.Params())
    run.depart(0.0, None)
    jn = next(e for e in r.events if e.get("then"))
    S, followed, seen, k = jn["S_fork"] - 1.5, 0.0, [], 0
    while S < jn["S_fork"] + until and run.fault is None:
        o = S - jn["S_fork"]
        while k + 1 < len(readings) and readings[k + 1][0] <= o:
            k += 1
        _o, nlcp, tracks = readings[k] if readings[0][0] <= o <= readings[-1][0] + STEP_M else (o, 2, [0])
        run.locate({"route": r.ident, "started": True, "S": S + bias, "sigma": sigma, "lost": ""}, 0.0)
        run.advance(STEP_M)
        run.scan(0.0, None, True, None)
        if run.fault is not None:
            break
        choice, _high = run.steer(sensor(tracks, nlcp), [], followed)
        pick = branch.select_track(sensor(tracks, nlcp)["tracks"], choice, vehicle.BRANCH_POSITIVE_IS_LEFT,
                                   followed)
        if pick is not None:
            followed = pick["pos_mm"]
        if len(tracks) >= 2:
            seen.append((o, tracks, followed, run.branch.ladder.intent()))
        S += STEP_M
    return run, seen


# -- the route ----------------------------------------------------------------------------------
def test_j_s_is_chained_to_j_n_and_nothing_else_is():
    orders = [e for e in route().events if e["kind"] == "order"]
    assert [(e["id"], e["order"], e["held"]) for e in orders] == [
        ("J-N", "left", True), ("J-S", "right", True), ("J-C", "left", False)]
    jn, js, jc = orders
    assert jn["then"] == "J-S" and js["after"] == "J-N"
    assert abs(js["S_fork"] - jn["S_node"] - 0.15) < 0.01, "0.15 m of one tape, as on g7"
    assert "after" not in jc and "then" not in js, "X is between: J-C is armed by S as before"


def test_a_short_lead_makes_no_chain():
    assert not any("then" in e or "after" in e for e in route(lead=0.1).events)


def test_a_stop_between_two_chained_forks_is_refused():
    d = copy.deepcopy(DOC)
    d["circuits"]["C-B"].insert(3, {"stop": "ATT"})
    d["circuits"]["C-B"].pop(6)
    m = missions.parse_site(d)
    g = graph(m, skip=("ATT",))
    g.put_station(tt.project_station(g, m, "ATT", (10.0, 10.05, 1.5708)))
    with pytest.raises(tg.RouteError, match="chained to J-N"):
        trr.compile_trip(tripmod.Trip(m, "B", ["B1"]), m, g)


# -- the lap ------------------------------------------------------------------------------------
@pytest.mark.parametrize("bias,sigma", [(0.0, 0.03), (0.3, 0.1), (-0.3, 0.1)])
def test_the_lane_is_kept_through_j_n_j_s_and_x2_with_s_early_exact_or_late(bias, sigma):
    run, seen = drive(bias=bias, sigma=sigma)
    assert run.fault is None, run.fault
    assert seen, "the readings were played"
    for o, tracks, followed, _intent in seen:
        assert followed == lane(o, tracks), f"at {o:+.3f} m {tracks}: followed {followed}"
    at_js = [intent for o, _t, _f, intent in seen if JS[0] <= o <= JS[1]]
    assert at_js[0] == branch.RIGHT, "RIGHT armed before J-S's first two-track reading"
    assert branch.LEFT not in at_js, "LEFT is never standing at J-S: that is the STU tape"
    texts = [t for _S, _s, t in run.decisions]
    assert "order left taken at J-N" in texts and "order right taken at J-S" in texts, texts
    assert any(t.startswith("order RIGHT armed for J-S, J-N taken") for t in texts), texts
    assert [r["verdict"] for r in run.fork_log] == ["ordered", "ordered"], run.fork_log


def test_without_the_chain_the_split_at_j_s_is_a_coin_toss():
    """The trap the chain is for: straight on at the split, the two tracks 6 mm apart around 20 mm."""
    pick = branch.select_track(sensor([17, 23], 6)["tracks"], branch.STRAIGHT, True, 20.0)
    assert pick["pos_mm"] == 17 and abs(17 - 20) == abs(23 - 20), "nearest is a tie"
    assert branch.select_track(sensor([17, 23], 6)["tracks"], branch.STRAIGHT, True, 21.0)["pos_mm"] == 23


def test_one_track_inside_j_s_before_it_opens_stands_the_order_again():
    # J-S opens (6-8 mm apart), then reads as one track for 0.02 m before it opens for good.
    flicker = [(o, n, t) for o, n, t in READINGS if not JS[0] + 0.012 < o < JS[0] + 0.032]
    flicker.insert(next(i for i, r in enumerate(flicker) if r[0] > JS[0] + 0.012), (JS[0] + 0.013, 2, [19]))
    run, seen = drive(readings=flicker)
    assert run.fault is None, run.fault
    texts = [t for _S, _s, t in run.decisions]
    assert any("J-S: one track again before the fork opened" in t for t in texts), texts
    for o, tracks, followed, _intent in seen:
        assert followed == lane(o, tracks), f"at {o:+.3f} m {tracks}: followed {followed}"


def test_no_fork_after_j_n_faults_before_x2():
    plain = [(o, 2, [0]) if JS[0] <= o < X2[0] else (o, n, t) for o, n, t in READINGS]
    plain = [(o, n, t if n == 2 or o < JS[0] else [0]) for o, n, t in plain]
    run, _seen = drive(readings=plain)
    assert run.fault is not None and run.fault.startswith("no fork within 0.5 m after J-N"), run.fault
    assert run._odo_m - run._chain_odo <= site_run.CHAIN_FORK_MAX_M + 2 * STEP_M


def test_j_s_never_closing_faults_before_x2():
    stuck = [(o, n, t) for o, n, t in READINGS if o < JS[0]]
    stuck += [(JS[0] + i * STEP_M, 6, [0, 20]) for i in range(200)]
    run, _seen = drive(readings=stuck)
    assert run.fault is not None and "still standing" in run.fault, run.fault
    assert run._odo_m - run._chain_odo <= site_run.CHAIN_TAKE_MAX_M + 2 * STEP_M


def test_a_fork_at_j_s_with_its_other_tape_on_the_wrong_side_faults():
    mirrored = [(o, {3: 6, 6: 3}.get(n, n), sorted(-p for p in t)) if JS[0] <= o <= JS[1] else (o, n, t)
                for o, n, t in READINGS]
    run, _seen = drive(readings=mirrored)
    assert run.fault is not None and run.fault.startswith("wrong fork at J-S"), run.fault
    assert "should leave on the left" in run.fault
