"""amr_line.tape_runtime: teach and shadow inside the LINE layer (tracked plan 3, P1).

Drives the synthetic circuit of test_tape_localization through the runtime the node
uses: select a map, record passes, build, teach stations, publish, activate, then
At home and a shadow lap. Nothing here produces a command.
"""
import math
import random

import pytest
from test_tape_localization import BINDING, STATIONS, TRUE, mission, tour  # noqa: E402

from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_graph_store as store  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import tape_runtime as tr  # noqa: E402

SHA = BINDING["map_sha256"]


def runtime(tmp_path, selection):
    return tr.TapeRuntime(mission(), tl.Params(), maps_dir=str(tmp_path / "maps"),
                          state_dir=str(tmp_path / "state"), selection=selection,
                          resolve_sha=lambda _m, _r: SHA, shadow_circuit="C-M")


def drive_lap(rt, t0=0.0, seed=0, start_travel=0.0, noise=0.01):
    """One lap of the synthetic tour through the runtime: ticks at 50 Hz, a pose every 0.1 s
    with 0.1 s latency, MLS fork episodes before each junction, the U-turn phases."""
    rnd = random.Random(seed)
    line, nodes = tour()
    t, s, pending, next_pose = t0, 0.0, [], t0
    while s < line.length:
        s = min(s + 0.01, line.length)
        t += 0.02
        nlcp = 6 if any(n - 0.4 <= s < n for k, n in enumerate(nodes) if k != 2) else 2
        phase = "approach" if nodes[2] - 1.5 <= s < nodes[2] else ""
        if abs(s - nodes[2]) < 0.006:
            for p in ("stopping", "spin", ""):
                rt.tick(t, start_travel + s, 2, True, p)
        rt.tick(t, start_travel + s, nlcp, False, phase)
        if t >= next_pose:
            x, y, _h = line.point(s)
            pending.append((t + 0.1, t, x + rnd.gauss(0, noise), y + rnd.gauss(0, noise)))
            next_pose += 0.1
        while pending and pending[0][0] <= t:
            _a, stamp, x, y = pending.pop(0)
            rt.amcl(t, stamp, x, y, 0.0, 0.0004, 0.0, 0.0004)
        if round(t * 50) % 25 == 0:
            rt.readiness(t, tr.READY)
    return t, start_travel + s


def stand(rt, t, travel, x, y, yaw, seconds=3.5):
    for _ in range(int(seconds / 0.1)):
        t += 0.1
        rt.tick(t, travel, 2, True)
        rt.amcl(t, t, x, y, yaw, 0.0004, 0.0, 0.0004)
        rt.readiness(t, tr.READY)
    return t


def test_teach_then_shadow(tmp_path):
    sel = {"map_id": "t", "map_revision": 1, "graph_revision": None}
    rt = runtime(tmp_path, sel)
    assert "no graph active" in rt.detail
    ok, msg = rt.teach(0.0, "pass_start", "C-M")
    assert not ok and "READY" in msg
    rt.readiness(0.0, tr.READY)
    t, travel = 0.0, 0.0
    for i in range(3):
        assert rt.teach(t, "pass_start", "C-M")[0]
        t, travel = drive_lap(rt, t, seed=i, start_travel=travel)
        ok, msg = rt.teach(t, "pass_stop")
        assert ok, msg
    ok, msg = rt.teach(t, "build")
    assert ok and "station HOME" in msg          # legs built, stations still missing
    for sid, (lid, s) in STATIONS.items():
        x, y, h = tg.Polyline(TRUE[lid]).point(s)
        t = stand(rt, t, travel, x, y, h)
        ok, msg = rt.teach(t, "station", sid)
        assert ok, msg
    ok, msg = rt.teach(t, "build")
    assert ok and "every circuit compiles" in msg, msg
    ok, msg = rt.teach(t, "publish")
    assert ok and "g1" in msg
    ok, msg = rt.teach(t, "activate", "1")
    assert ok and store.read_active(str(tmp_path / "state"))["graph_revision"] == 1

    # The next layer start: the active graph, At home, a shadow lap.
    rt = runtime(tmp_path, store.read_active(str(tmp_path / "state")))
    assert rt.route is not None and "At home" in rt.detail
    ok, _msg, pose = rt.at_home()
    assert ok and pose[0] == pytest.approx(5.0, abs=0.05)
    assert rt.snapshot()["loc_health"] == "WAITING"
    rt.readiness(t, tr.READY)
    t, travel = drive_lap(rt, t, seed=7, start_travel=travel)
    t = stand(rt, t, travel, 5.0, 0.0, 0.0, seconds=0.5)   # parked at HOME: the lap completes
    snap = rt.snapshot()
    assert snap["loc_health"] in ("HEALTHY", "DEGRADED") and snap["loc_graph"] == "t rev1 g1"
    text = " | ".join(x for _l, x in rt.drain_events())
    for what in ("locator started", "stop ATT", "stop MW-1", "order right at J-B", "U-turn U done",
                 "lap complete"):
        assert what in text, text
    assert "would HOLD" not in text, text


def test_a_graph_for_another_map_revision_is_refused(tmp_path):
    rt = runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    rt.teach(0.0, "pass_start", "C-M")
    t, _ = drive_lap(rt)
    rt.teach(t, "pass_stop")
    rt.teach(t, "build")
    rt.teach(t, "publish")
    rt2 = tr.TapeRuntime(mission(), tl.Params(), maps_dir=str(tmp_path / "maps"),
                         state_dir=str(tmp_path / "state"),
                         selection={"map_id": "t", "map_revision": 1, "graph_revision": 1},
                         resolve_sha=lambda _m, _r: "cd" * 32, shadow_circuit="C-M")
    assert rt2.route is None and "hash changed" in rt2.detail
    assert not rt2.at_home()[0]


def test_teach_refusals(tmp_path):
    rt = runtime(tmp_path, None)
    assert "no map selected" in rt.teach(0.0, "pass_start", "C-M")[1]
    assert not rt.teach(0.0, "fly")[0]
    rt = runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    assert "circuit" in rt.teach(0.0, "pass_start", "C-X")[1]
    ok, msg = rt.teach(0.0, "station", "ATT")
    assert not ok and "still" in msg
    t = stand(rt, 0.0, 0.0, 10.0, 3.0, math.pi / 2)
    assert "no legs yet" in rt.teach(t, "station", "ATT")[1]
    assert rt.teach(t, "map", "t 2")[0] and store.read_active(str(tmp_path / "state"))["map_revision"] == 2


# -- the straight-section test (plan 3 section 7) ------------------------------------------
# 10 m of tape, x = 0 (west tape end, U-MRU pivot) to x = 10. T-HOME at x = 9.5 facing west;
# there the operator turns the AGV by hand (MANUAL spin, no tape end in the east).

HOME_X = 9.5
# T-ATT at least 2 m from T-HOME: its braking point must lie beyond the start, where AMCL
# has corrected the At-home sigma (runbook section 2S).
# Only MRU4 lies inside the section (operator, 2026-10-18).
WEST = {"T-HOME": 9.5, "T-ATT": 7.0, "MW-4": 1.8}
EAST = {"ME-4": 1.8}


def straight_runtime(tmp_path, selection):
    from agv_core import mission as missions
    return tr.TapeRuntime(missions.load_site("test-mru-straight"), tl.Params(),
                          maps_dir=str(tmp_path / "maps"), state_dir=str(tmp_path / "state"),
                          selection=selection, resolve_sha=lambda _m, _r: SHA, shadow_circuit="C-STRAIGHT")


def straight_lap(rt, t, travel, seed=0, manual_pivot=False):
    """HOME westbound to the tape end, the pivot, eastbound back to HOME; optionally the
    operator's MANUAL spin at HOME first (AMCL keeps updating, the wheels add ~0 travel)."""
    rnd = random.Random(seed)
    if manual_pivot:
        for k in range(40):
            t += 0.1
            rt.tick(t, travel, 2, False)
            rt.amcl(t, t - 0.05, HOME_X + rnd.gauss(0, 0.01), rnd.gauss(0, 0.01), math.pi * k / 40,
                    4e-4, 0, 4e-4)
            rt.readiness(t, tr.READY)
    pending, next_pose = [], t

    def step(x, phase=""):
        nonlocal t, travel, next_pose
        t += 0.02
        travel += 0.01
        rt.tick(t, travel, 2, False, phase)
        if t >= next_pose:
            pending.append((t + 0.1, t, x + rnd.gauss(0, 0.01), rnd.gauss(0, 0.01)))
            next_pose += 0.1
        while pending and pending[0][0] <= t:
            _a, stamp, px, py = pending.pop(0)
            rt.amcl(t, stamp, px, py, 0.0, 4e-4, 0.0, 4e-4)
        if round(t * 50) % 25 == 0:
            rt.readiness(t, tr.READY)

    x = HOME_X
    while x > 0.0:
        x = max(0.0, x - 0.01)
        step(x, "approach" if x < 1.5 else "")
    for p in ("stopping", "spin", ""):
        rt.tick(t, travel, 2, True, p)
    while x < HOME_X:
        x = min(HOME_X, x + 0.01)
        step(x)
    for _ in range(10):                       # standing at HOME
        t += 0.1
        rt.tick(t, travel, 2, True)
        rt.readiness(t, tr.READY)
    return t, travel


def test_the_straight_section_teach_and_shadow(tmp_path):
    rt = straight_runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    t, travel = 0.0, 0.0
    for i in range(3):
        assert rt.teach(t, "pass_start", "C-STRAIGHT")[0]
        t, travel = straight_lap(rt, t, travel, seed=i, manual_pivot=i > 0)
        ok, msg = rt.teach(t, "pass_stop")
        assert ok, msg
    assert rt.teach(t, "build")[0]
    for stations, yaw in ((WEST, math.pi), (EAST, 0.0)):
        for sid, x in stations.items():
            t = stand(rt, t, travel, x, 0.0, yaw)
            ok, msg = rt.teach(t, "station", sid)
            assert ok, (sid, msg)
    ok, msg = rt.teach(t, "build")
    assert ok and "every circuit compiles" in msg, msg
    leg = rt.staged.legs["U-MRU:pivot>U-MRU"]
    assert leg.length == pytest.approx(2 * HOME_X, abs=0.1) and leg.end_kind == "uturn"
    assert rt.teach(t, "publish")[0] and rt.teach(t, "activate", "1")[0]

    rt = straight_runtime(tmp_path, store.read_active(str(tmp_path / "state")))
    ok, _m, pose = rt.at_home()
    assert ok and pose[0] == pytest.approx(HOME_X, abs=0.05) and abs(abs(pose[2]) - math.pi) < 0.1
    rt.readiness(t, tr.READY)
    for lap in range(2):
        t, travel = straight_lap(rt, t, travel, seed=10 + lap, manual_pivot=lap > 0)
    text = " | ".join(x for _l, x in rt.drain_events())
    assert text.count("lap complete") == 2, text
    for what in ("stop T-ATT", "stop MW-4", "U-turn approach U-MRU", "U-turn U-MRU done",
                 "stop ME-4", "stop T-HOME"):
        assert text.count(what) == 2, (what, text)
    assert "would HOLD" not in text and "LOST" not in text, text


def test_a_pass_that_does_not_match_is_still_saved(tmp_path):
    rt = runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    assert rt.teach(0.0, "pass_start", "C-M")[0]
    t = 0.0
    for i in range(200):                    # 20 m, no fork, no U-turn: not C-M
        t += 0.1
        rt.tick(t, i * 0.1, 2, False)
        rt.amcl(t, t, i * 0.1, 0.0, 0.0, 0.0004, 0.0, 0.0004)
    ok, msg = rt.teach(t, "pass_stop")
    assert not ok and "saved but it does NOT match" in msg, msg
    assert rt.teach(t, "passes")[1].startswith("C-M-")
    ok, msg = rt.teach(t, "build")
    assert "REFUSED" in msg, msg


def test_a_u_turn_straight_from_following_is_recorded(tmp_path):
    rt = runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    rt.teach(0.0, "pass_start", "C-M")
    rt.tick(0.1, 1.0, 2, False, "")
    rt.tick(0.2, 1.1, 0, False, "stopping", True)     # no approach phase: the tape-end U-turn
    rt.tick(0.3, 1.1, 0, True, "spin", True)
    rt.tick(0.4, 1.1, 2, True, "")
    assert rt.recorder.uturns == [1.1] and rt.recorder.pivots == [1.1]


def test_marks_from_the_moving_vehicle_land_on_the_leg_it_faces(tmp_path):
    # 2026-10-24: positions marked while driving; their role (station, zone edge) comes later
    rt = runtime(tmp_path, {"map_id": "t", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, tr.READY)
    assert rt.teach(0.0, "mark")[1].startswith("no legs")
    rt.teach(0.0, "pass_start", "C-M")
    t, travel = drive_lap(rt)
    rt.teach(t, "pass_stop")
    assert rt.teach(t, "build")[0]
    # driving east along J-B:right>U (10,10)->(30,10): the last pose 0.5 m of travel ago
    t1 = t + 1.0
    rt.tick(t1, travel, 2, False)
    rt.amcl(t1, t1, 20.0, 10.0, 0.0, 0.0004, 0.0, 0.0004)
    rt.tick(t1 + 0.5, travel + 0.5, 2, False)
    rt.readiness(t1 + 0.5, tr.READY)
    ok, msg = rt.teach(t1 + 0.5, "mark", "release MW-x")
    assert ok and msg.startswith("M1 (release MW-x) on J-B:right>U at 10.5"), msg
    # the same spot facing west is the other leg of the same tape
    t2 = t1 + 1.0
    rt.tick(t2, travel + 0.5, 2, False)
    rt.amcl(t2, t2, 20.0, 10.0, math.pi, 0.0004, 0.0, 0.0004)
    ok, msg = rt.teach(t2, "mark")
    assert ok and msg.startswith("M2 on U:pivot>J-C at 10."), msg
    assert rt.teach(t2 + 5.0, "mark")[1].startswith("no AMCL pose")      # stale pose
    rt.readiness(t2, tr.LOST_STATES[1], "localisation corrected by 0.15 m")  # LOST: marked, flagged
    rt.amcl(t2, t2, 21.0, 10.0, 0.0, 0.0004, 0.0, 0.0004)
    ok, msg = rt.teach(t2, "mark")
    assert ok and "marked while localisation corrected by 0.15 m" in msg, msg
    assert rt.teach(t2, "mark_delete", "M3")[0]
    assert "M1 (release MW-x) J-B:right>U 10.5" in rt.teach(t2, "marks")[1]
    assert rt.teach(t2, "mark_delete", "M2")[0] and not rt.teach(t2, "mark_delete", "M2")[0]
    marks = store.load_marks(str(tmp_path / "state"), "t", 1)
    assert list(marks) == ["M1"] and marks["M1"]["lag_m"] == pytest.approx(0.5, abs=0.01)
    ok, msg = rt.teach(t2, "build")                  # re-averaged legs: marks follow
    assert ok and "no longer on a leg" not in msg


# -- tracked plan 4: roles for marks, the trip locator --------------------------------------

def _site_runtime(tmp_path, graph_revision=None):
    from site_fixture import site  # noqa: PLC0415
    return tr.TapeRuntime(site(), tl.Params(), maps_dir=str(tmp_path / "maps"),
                          state_dir=str(tmp_path / "state"),
                          selection={"map_id": "t", "map_revision": 1, "graph_revision": graph_revision},
                          resolve_sha=lambda _m, _r: SHA, shadow_circuit="C-M")


def test_a_mark_becomes_a_station_or_point_by_its_role(tmp_path):
    from site_fixture import graph, site  # noqa: PLC0415
    rt = _site_runtime(tmp_path)
    m = site()
    rt.staged = graph(m, skip=tuple(m["STATIONS"]) + ("HOME", "UT-M1", "UT-M2"))
    line = rt.staged.legs["J-B:right>U"].line
    marks = {f"M{k}": {"label": "", "leg": "J-B:right>U", "s": s, "pose": list(line.point(s))}
             for k, s in ((1, 8.0), (2, 11.0), (3, 1.0))}
    marks["M4"] = {"label": "", "leg": "U:pivot>J-C", "s": 12.0,
                   "pose": list(rt.staged.legs["U:pivot>J-C"].line.point(12.0))}
    store.save_marks(str(tmp_path / "state"), "t", 1, marks)
    ok, msg = rt.teach(0.0, "mark_role", "M1 MW-1")
    assert ok and msg.startswith("M1 is MW-1 on J-B:right>U at s 8.00 m"), msg
    assert rt.teach(0.0, "mark_role", "M2 UT-M1")[0], "a U-turn point lands on its machine's release leg"
    ok, msg = rt.teach(0.0, "mark_role", "M3 ATT")      # M3 is on the machine line, ATT on J-A's leg
    assert not ok and "wrong direction for J-A:merge>J-B" in msg and "ATT" not in rt.staged.stations, msg
    ok, msg = rt.teach(0.0, "mark_role", "M4 MW-2")
    assert not ok and "wrong direction" in msg, "MW-2 is on the way out; M4 faces back"
    assert not rt.teach(0.0, "mark_role", "M1 NOPE")[0]
    ok, msg = rt.teach(0.0, "mark_role", "M4 ME-1")
    assert ok
    stations = store.load_stations(str(tmp_path / "state"), "t", 1)
    assert stations["MW-1"]["mark"] == "M1"
    assert stations["UT-M1"]["pose"] == pytest.approx(marks["M2"]["pose"])
    ok, msg = rt.teach(0.0, "roles")
    assert "MW-1=M1" in msg and "not taught: HOME, ATT, MW-2" in msg, msg
    # moving a role to another mark takes it off the first; "-" removes it
    ok, msg = rt.teach(0.0, "mark_role", "M2 MW-1")
    assert ok and "M1 no longer MW-1" in msg and "UT-M1 untaught" in msg, msg
    assert rt.teach(0.0, "mark_role", "M2 -")[1] == "M2: role MW-1 removed"
    assert "MW-1" not in store.load_stations(str(tmp_path / "state"), "t", 1)
    assert "= ME-1" in rt.teach(0.0, "marks")[1]


def test_the_locator_moves_onto_a_trips_route_where_it_stands(tmp_path):
    from site_fixture import graph, site  # noqa: PLC0415

    from amr_line import trip as trip_mod  # noqa: PLC0415
    m = site(trip_calls=1)
    n = store.publish(str(tmp_path / "maps"), graph(m))
    rt = _site_runtime(tmp_path, graph_revision=n)
    assert rt.route is not None, rt.detail
    assert rt.at_home()[0]
    rt.readiness(0.0, tr.READY)
    rt.tick(0.1, 0.0, 2, True)
    assert rt.loc is not None and rt.loc_state()["home_offset"] == pytest.approx(0.0)
    rt.tick(0.2, 0.12, 2, False)                            # 12 cm out of the bay
    route = rt.compile_trip(trip_mod.Trip(rt.m, "M", ["M1"]))
    ok, _msg = rt.begin_trip(route)
    st = rt.loc_state()
    assert ok and st["route"] == route.ident and st["S"] == pytest.approx(route.S_start + 0.12)
    assert st["home_offset"] == pytest.approx(0.12) and rt.shadow is None
    rt.tick(0.3, 0.32, 2, False)
    assert rt.loc_state()["S"] == pytest.approx(route.S_start + 0.32)


def test_the_shadow_lap_logs_the_u_turn_points_and_the_high_speed_areas(tmp_path):
    from site_fixture import AREAS, graph, site  # noqa: PLC0415
    n = store.publish(str(tmp_path / "maps"), graph(site()))
    store.save_areas(str(tmp_path / "state"), "t", 1, AREAS)
    rt = _site_runtime(tmp_path, graph_revision=n)
    rt.at_home()
    rt.readiness(0.0, tr.READY)
    t, travel = 0.0, 0.0
    while travel < 30.0:
        t, travel = t + 0.02, travel + 0.01
        rt.tick(t, travel, 2, False)
    text = " | ".join(x for _l, x in rt.drain_events())
    assert "high-speed area: HIGH from Z-LINE at S 21.00" in text, text
    assert "high-speed area: NORMAL by Z-LINE at S 27.00" in text
    assert "U-turn point of M1 UT-M1 at S 30.50" in text
    assert "would HOLD" in text, "odometry only: sigma grows past the station limit"



def test_an_inbound_mark_is_placed_by_a_floor_offset_from_an_outbound_one(tmp_path):
    from site_fixture import graph, site  # noqa: PLC0415
    rt = _site_runtime(tmp_path)
    rt.staged = graph(site())
    line = rt.staged.legs["J-B:right>U"].line
    store.save_marks(str(tmp_path / "state"), "t", 1,
                     {"M8": {"label": "", "leg": "J-B:right>U", "s": 8.0, "pose": list(line.point(8.0))}})
    # MW-1 is at x 18 going east; the inbound tape runs west over it: +1.2 m along it is x 16.8
    ok, msg = rt.teach(0.0, "mark_offset", "M8 1.2 M12")
    assert ok and msg.startswith("M12 on U:pivot>J-C at 13.20 m (+1.20 m from M8), (16.80, 10.00)"), msg
    marks = store.load_marks(str(tmp_path / "state"), "t", 1)
    assert marks["M12"]["from"] == "M8" and marks["M12"]["offset_m"] == 1.2
    ok, msg = rt.teach(0.0, "mark_role", "M12 ME-1")
    assert ok and "U:pivot>J-C at s 13.20" in msg, msg
    assert not rt.teach(0.0, "mark_offset", "M8 1.0 M12")[0], "an id in use is refused"
    assert "runs off" in rt.teach(0.0, "mark_offset", "M8 -20")[1]
    assert rt.teach(0.0, "mark_offset", "M8 -0.5")[1].startswith("M13 on U:pivot>J-C at 11.50")



def test_a_u_turn_point_is_placed_along_the_release_marks_own_tape(tmp_path):
    from site_fixture import graph, site  # noqa: PLC0415
    rt = _site_runtime(tmp_path)
    rt.staged = graph(site())
    line = rt.staged.legs["J-B:right>U"].line
    store.save_marks(str(tmp_path / "state"), "t", 1,
                     {"M8": {"label": "", "leg": "J-B:right>U", "s": 8.0, "pose": list(line.point(8.0))}})
    ok, msg = rt.teach(0.0, "mark_along", "M8 1.4 M16")         # MW-1 + 1.4 m toward the line's end
    assert ok and msg.startswith("M16 on J-B:right>U at 9.40 m (+1.40 m from M8), (19.40, 10.00)"), msg
    assert rt.teach(0.0, "mark_role", "M16 UT-M1")[0]
    assert "runs off" in rt.teach(0.0, "mark_along", "M8 15")[1]



def test_a_mark_off_every_built_leg_is_kept_and_placed_at_build(tmp_path):
    # 2026-10-25: the first C-BTU lap marks its stops before row 2 is in any graph
    from site_fixture import graph, site  # noqa: PLC0415
    rt = _site_runtime(tmp_path)
    rt.staged = graph(site())
    rt.readiness(0.0, tr.READY)
    rt.tick(0.0, 0.0, 2, False)
    rt.amcl(0.0, 0.0, 50.0, 50.0, 0.0, 0.0004, 0.0, 0.0004)       # far from every leg
    rt.tick(0.5, 0.5, 2, False)
    ok, msg = rt.teach(0.5, "mark", "R2-1")
    assert ok and msg.startswith("M1 (R2-1) at (50.50, 50.00), not on a built leg yet"), msg
    marks = store.load_marks(str(tmp_path / "state"), "t", 1)
    assert marks["M1"]["leg"] == "" and marks["M1"]["lag_m"] == 0.5
    assert "M1 (R2-1)" in rt.teach(0.5, "marks")[1]
