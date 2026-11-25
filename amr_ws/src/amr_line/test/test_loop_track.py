"""Loop site (schema loop-1, manuals/loop-track-plan.md, 2026-11-25): one closed tape loop, no
junction, no U-turn, no marker. Each Start at HOME drives one lap and stops at HOME.

The loop is a 20 x 8 m rectangle driven anticlockwise, HOME at (5, 0) facing +x:

    (0,8) <------------- (20,8)
      |                    ^
      v                    |
    (0,0) --HOME(5,0)--> (20,0)

Pure, clock-fed, synthetic; the job tests drive the real FollowJob (TripWorld)."""
import copy
import math
import random

import pytest
from agv_core import mission as missions  # noqa: E402
from test_mission_engine import World  # noqa: E402
from test_site_run import TripWorld  # noqa: E402

from amr_line import job as lj  # noqa: E402
from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_locator as tl  # noqa: E402
from amr_line import tape_teach as tt  # noqa: E402
from amr_line import trip as tr  # noqa: E402
from amr_line import trip_route as trr  # noqa: E402

DOC = {"schema": "loop-1", "mission_name": "loop", "home": "HOME", "stop_distance_m": 0.5, "cruise_mps": 0.4}
BINDING = {"map_id": "loop", "map_revision": 1, "map_sha256": "ab" * 32}
LEG = "HOME:loop>HOME"
LAP_M = 56.0
HOME = (5.0, 0.0, 0.0)
# Two laps of the true path from HOME, so a pass can start anywhere and run over its start.
_ONE = [(5, 0), (20, 0), (20, 8), (0, 8), (0, 0), (5, 0)]
TRUE = tg.Polyline(tg.resample(_ONE + _ONE[1:], 0.02))


def mission():
    return missions.parse_site(copy.deepcopy(DOC))


def record(seed=0, start=0.0, length=LAP_M + 1.5, lateral=0.01, reverse=False, corner_forks=True):
    """A synthetic loop pass: from `start` m past HOME along the loop, `length` m of travel."""
    rnd = random.Random(seed)
    rec = tt.PassRecorder(missions.LOOP_CIRCUIT, started=f"p{seed}")
    corners = [15.0, 23.0, 43.0, 51.0]                 # HOME-relative S of the four corners
    s = t = 0.0
    while s <= length:
        u = (start + s) % LAP_M
        if reverse:
            u = (start - s) % LAP_M
        nlcp = 6 if corner_forks and any(c - 0.2 <= u < c for c in corners) else 2
        rec.tick(t, s, nlcp)
        if round(s / 0.02) % 5 == 0:
            x, y, h = TRUE.point(u)
            n = rnd.gauss(0, lateral)
            rec.pose(t, x - n * math.sin(h), y + n * math.cos(h))
        s += 0.02
        t += 0.04
    return rec.to_dict()


def taught(passes=None):
    m = mission()
    g, report = tt.build(passes or [record(seed=i) for i in range(3)], m, BINDING)
    g.put_station(tt.project_station(g, m, "HOME", HOME))
    return m, g, report


# -- mission ----------------------------------------------------------------------------------

def test_a_loop_mission_is_one_circuit_one_leg_home_to_home():
    m = mission()
    assert missions.is_loop(m) and m["ATTACH"] is None and m["GROUPS"] == {} and m["TRIP_CALLS"] == 0
    c = m["CIRCUITS"][missions.LOOP_CIRCUIT]
    assert [leg["id"] for leg in c["legs"]] == [LEG]
    assert c["home_depart"] == ["HOME"] and c["home_arrive"] == ["HOME"]
    assert m["STATIONS"] == {"HOME": LEG}


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.update(attach="ATT"), "unknown key"),
    (lambda d: d.update(junctions={}), "unknown key"),
    (lambda d: d.pop("home"), "missing key"),
    (lambda d: d.update(cruise_mps=9.0), "cruise_mps"),
])
def test_loop_mission_refusals(mutate, needle):
    d = copy.deepcopy(DOC)
    mutate(d)
    with pytest.raises(missions.MissionError, match=needle):
        missions.parse_site(d)


def test_the_repo_loop_files_load_and_site_103_is_unchanged():
    m = missions.load_site("loop-site")
    assert missions.is_loop(m) and m["HOME"] == "HOME"
    g = missions.load("c-loop-guided")
    assert g["GUIDED"]["end_stop_m"] == 0.5
    site = missions.load_site("site-103")
    assert not missions.is_loop(site) and len(site["CIRCUITS"]["C-MRU"]["legs"]) > 1
    assert "loop-site" in missions.list_site_missions() and "loop-site" not in missions.list_missions()


# -- teaching ---------------------------------------------------------------------------------

def test_a_pass_that_runs_over_its_start_is_cut_into_one_lap():
    lap = tt.close_loop(record(length=LAP_M + 1.5, lateral=0.0))     # noise lengthens a raw path
    assert tg.Polyline(lap).length == pytest.approx(LAP_M, abs=0.15)
    assert math.dist(lap[0], lap[-1]) < 0.10


def test_a_pass_that_ends_a_little_short_closes_and_one_too_short_is_refused():
    lap = tt.close_loop(record(length=LAP_M - 0.3, lateral=0.0))
    assert tg.Polyline(lap).length == pytest.approx(LAP_M - 0.3, abs=0.15)
    with pytest.raises(tt.TeachError, match="ended 0.[89]"):
        tt.close_loop(record(length=LAP_M - 0.8))
    with pytest.raises(tt.TeachError, match="before it went round|never left|ended"):
        tt.close_loop(record(length=3.0))


def test_passes_started_apart_are_rotated_to_one_point_and_average_into_one_leg():
    passes = [record(seed=0), record(seed=1, start=1.5), record(seed=2, start=LAP_M - 1.5)]
    m, g, report = taught(passes)
    assert list(g.legs) == [LEG], report
    leg = g.legs[LEG]
    assert leg.end_kind == "loop" and leg.passes == 3
    assert leg.length == pytest.approx(LAP_M, abs=0.2), report
    assert leg.spread_m < tt.MAX_SPREAD_M, report
    assert math.dist(leg.line.pts[0], HOME[:2]) < 0.1, "every pass starts at the first pass's start"
    assert not any("REFUSED" in r for r in report), report
    assert any("MLS fork episode(s) ignored" in r for r in report), report


def test_a_pass_driven_the_other_way_round_is_refused():
    passes = [record(seed=0), record(seed=1, reverse=True)]
    _m, _g, report = taught(passes)
    assert any("REFUSED" in r and "other way round" in r for r in report), report


def test_with_home_taught_every_pass_is_rotated_to_home():
    m = mission()
    ref = tt.loop_ref([record(seed=0, start=3.0)], m, [{"id": "HOME", "pose": list(HOME)}])
    assert ref == HOME
    parts = tt.split_pass(record(seed=0, start=3.0), m, [], ref=ref)
    assert math.dist(parts[LEG]["pts"][0], HOME[:2]) < 0.05


def test_a_loop_leg_survives_publish_and_load():
    _m, g, _r = taught()
    back = tg.Graph.from_dict(copy.deepcopy(g.to_dict()))
    assert back.legs[LEG].end_kind == "loop"
    assert back.stations["HOME"].s == pytest.approx(g.stations["HOME"].s, abs=1e-3)


def test_home_at_the_seam_is_the_start_of_the_leg():
    _m, g, _r = taught()
    assert g.stations["HOME"].s < 0.1


# -- route and trip ---------------------------------------------------------------------------

def test_the_loop_route_is_one_lap_with_a_seam_and_nothing_to_act_on_but_home():
    m, g, _r = taught()
    route = tg.compile_route(missions.LOOP_CIRCUIT, m["CIRCUITS"][missions.LOOP_CIRCUIT], g)
    assert route.S_end - route.S_start == pytest.approx(g.legs[LEG].length, abs=1e-6)
    assert [n["kind"] for n in route.nodes] == ["seam"] and not route.nodes[0]["fork"]
    trip = tr.LoopQueue(m).take()
    tri = trr.compile_trip(trip, m, g)
    assert tri.uturn is None
    assert [(e["kind"], e["id"]) for e in tri.events] == [("stop", "HOME")]
    assert tri.events[0]["S"] == pytest.approx(tri.S_end)


def test_the_locator_and_shadow_go_round_five_laps_across_the_seam():
    m, g, _r = taught()
    route = tg.compile_route(missions.LOOP_CIRCUIT, m["CIRCUITS"][missions.LOOP_CIRCUIT], g)
    lap = route.S_end - route.S_start
    loc = tl.TapeLocator(route, tl.Params(), g)
    loc.readiness(True)
    rnd = random.Random(3)
    scale, tick, v = 1.01, 0.02, 0.5
    loc.start(route.S_start, 0.02, 0.0, 0.0)
    D = t = 0.0
    k, sigmas, errs = 0, [], []
    pending, next_pose = [], 0.0
    while k < 5:
        D += v * tick
        t += tick
        loc.predict(t, D * scale)
        truth = route.S_start + D - k * lap
        if t >= next_pose:
            x, y, _ = route.point(truth)
            pending.append((t + 0.1, t, x + rnd.gauss(0, 0.02), y + rnd.gauss(0, 0.02)))
            next_pose += 0.1
        while pending and pending[0][0] <= t:
            _a, stamp, x, y = pending.pop(0)
            loc.correct(t, stamp, x, y, 0.0)
            errs.append(loc.S - truth)
        if loc.S >= route.S_end:          # tape_runtime._shadow_tick: the next lap
            loc.S -= lap
            k += 1
            sigmas.append(loc.sigma)
    assert loc.health == tl.HEALTHY and not loc.lost
    assert max(abs(e) for e in errs[50:]) < 0.08
    assert sigmas[-1] < 2 * max(sigmas[0], 0.03), sigmas


# -- the job: Start at HOME = one lap -----------------------------------------------------------

def test_each_start_at_home_drives_one_lap_and_stops_at_home():
    m, g = taught()[:2]
    w = TripWorld(m, g)                 # at HOME, before any lap
    assert w.job.trip_call("M1", w.t)[0] is False, "a loop takes no calls"
    for lap in (1, 2):
        w.start()
        assert w.job.trip is not None and w.job.trip.describe().startswith("lap"), w.job.reason
        assert w.until(lambda: w.job.state == lj.DONE, 400.0), (lap, w.job.reason, w.S)
        assert abs(w.S - w.route.S_end) < 0.05, (lap, w.S, w.route.S_end)
        assert w.job.trip is None and w.job.payload.may_leave()[0]


def test_a_lap_start_away_from_home_is_refused():
    m, g = taught()[:2]
    w = TripWorld(m, g)
    w.S = 9.0
    w.press_start()
    assert w.job.state == lj.IDLE and "not at HOME" in w.job.reason, w.job.reason


def test_a_loop_site_is_refused_with_station_calling():
    m, g = taught()[:2]
    w = World(None)
    w.job.calling = True
    w.job.configure_site(tl.Params(), lambda trip: trr.compile_trip(trip, m, g))
    ok, msg = w.job.set_mission(m)
    assert not ok and "station calling" in msg


# -- End lap (the teach lap) ------------------------------------------------------------------

def guided():
    w = World(missions.load("c-loop-guided"))
    w.comms = False
    w.start()
    w.drive(2.0)
    assert w.job.state == lj.RUNNING, w.job.reason
    return w


def test_end_lap_stops_measured_and_the_run_is_complete():
    w = guided()
    ok, msg = w.job.end_lap()
    assert ok and "End lap" in msg
    assert w.until(lambda: w.job.state == lj.DONE, 10.0), w.job.reason
    assert not w.job.tape.end_requested


def test_end_lap_is_refused_outside_a_running_guided_run():
    w = World(missions.load("c-loop-guided"))
    assert not w.job.end_lap()[0], "idle: nothing to end"
    w = World(missions.load("basic-right"))       # no guided block
    w.comms = False
    w.start()
    w.drive(1.0)
    ok, msg = w.job.end_lap()
    assert not ok and "guided" in msg


# -- the runtime: Stop pass, Build, Teach here, Publish, load, shadow laps ----------------------
# (store-backed: on the Windows dev box the fcntl shim breaks the store's file writes, so this one
# runs on the vehicle)

def loop_runtime(tmp_path, selection):
    from amr_line import tape_graph_store as store  # noqa: F401, PLC0415
    from amr_line import tape_runtime as rtm  # noqa: PLC0415
    return rtm.TapeRuntime(mission(), tl.Params(), maps_dir=str(tmp_path / "maps"),
                           state_dir=str(tmp_path / "state"), selection=selection,
                           resolve_sha=lambda _m, _r: BINDING["map_sha256"],
                           shadow_circuit=missions.LOOP_CIRCUIT)


def runtime_lap(rt, t, travel, start=0.0, length=LAP_M + 1.0, seed=0):
    """Drive `length` m round the loop from `start` m past HOME: 50 Hz ticks, a pose every 0.1 s."""
    from amr_line import tape_runtime as rtm  # noqa: PLC0415
    rnd = random.Random(seed)
    pending, next_pose, s = [], t, 0.0
    while s < length:
        s += 0.01
        t += 0.02
        rt.tick(t, travel + s, 2, False)
        if t >= next_pose:
            x, y, _h = TRUE.point((start + s) % LAP_M)
            pending.append((t + 0.1, t, x + rnd.gauss(0, 0.01), y + rnd.gauss(0, 0.01)))
            next_pose += 0.1
        while pending and pending[0][0] <= t:
            _a, stamp, x, y = pending.pop(0)
            rt.amcl(t, stamp, x, y, 0.0, 4e-4, 0.0, 4e-4)
        if round(t * 50) % 25 == 0:
            rt.readiness(t, rtm.READY)
    return t, travel + s


def test_the_runtime_teaches_a_loop_and_shadows_it_lap_after_lap(tmp_path):
    from amr_line import tape_graph_store as store  # noqa: PLC0415
    from amr_line import tape_runtime as rtm  # noqa: PLC0415
    rt = loop_runtime(tmp_path, {"map_id": "loop", "map_revision": 1, "graph_revision": None})
    rt.readiness(0.0, rtm.READY)
    t, travel, start = 0.0, 0.0, 0.0
    for i in range(3):                      # each pass starts where the last one stopped
        assert rt.teach(t, "pass_start", missions.LOOP_CIRCUIT)[0]
        t, travel = runtime_lap(rt, t, travel, start=start, seed=i)
        ok, msg = rt.teach(t, "pass_stop")
        assert ok and "loop closed" in msg, msg
        start = (start + LAP_M + 1.0) % LAP_M
    ok, msg = rt.teach(t, "build")
    assert ok and "REFUSED" not in msg, msg
    # HOME taught on the arrow, standing
    for _ in range(35):
        t += 0.1
        rt.tick(t, travel, 2, True)
        rt.amcl(t, t, HOME[0], HOME[1], HOME[2], 4e-4, 0.0, 4e-4)
        rt.readiness(t, rtm.READY)
    ok, msg = rt.teach(t, "station", "HOME")
    assert ok, msg
    ok, msg = rt.teach(t, "build")
    assert ok and "every circuit compiles" in msg, msg
    assert rt.staged.legs[LEG].end_kind == "loop"
    assert rt.teach(t, "publish")[0] and rt.teach(t, "activate", "1")[0]

    rt = loop_runtime(tmp_path, store.read_active(str(tmp_path / "state")))
    ok, _m, pose = rt.at_home()
    assert ok and math.dist(pose[:2], HOME[:2]) < 0.05
    rt.readiness(t, rtm.READY)
    t, travel = runtime_lap(rt, t, travel, start=0.0, length=3 * LAP_M + 0.5, seed=7)
    text = " | ".join(x for _l, x in rt.drain_events())
    assert text.count("lap complete") == 3, text
    assert "would HOLD" not in text and "LOST" not in text and "fork with no taught junction" not in text, text
