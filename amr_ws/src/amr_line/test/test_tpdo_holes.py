"""MLS consumer carry-overs (2026-11-16): TPDO1 holes from MarkerEvent.gaps (WP-E8 / H-P1-8), a stale
#LCP aborting an open fork episode (H-P2-3), and the curve guard's max(|gyro|, |wheels|) (H-P1-7).
Pure: MarkerReader, the real FollowJob, TapeRuntime without a map."""

from amr_line.marker_reader import MarkerReader
from test_marker_run import started
from test_mission_engine import World, _at_high

from amr_line import job as lj
from amr_line import tape_locator, tape_runtime


def snap(encounters=(), gaps=None, gen=0, base=0):
    s = {"ok": True, "status": "ok", "generation": gen, "base": base, "encounters": list(encounters)}
    if gaps is not None:
        s["gaps"] = gaps
    return s


def with_gaps(w):
    """A World whose marker snapshot carries drive_node's TPDO1 hole counter (w.gaps)."""
    plain = w.markers
    w.gaps = 0
    w.markers = lambda: {**plain(), "gaps": w.gaps}
    return w


# -- marker_reader ----------------------------------------------------------------------

def test_the_first_counter_is_a_baseline_not_holes():
    r = MarkerReader()
    assert r.scan(snap(gaps=7)) == [] and r.holes == 0


def test_a_growing_counter_is_one_code_0_entry_after_the_markers():
    r = MarkerReader()
    r.scan(snap(gaps=2))
    out = r.scan(snap([(1, 2, 0, 5, True)], gaps=5))
    assert out == [(2, 0, 5, 0, True), (0, 0, 0, 3, False)]
    assert r.holes == 3 and r.count == 1 and r.missed == 0, "a hole is not a marker nor a topic loss"
    assert r.last == {"code": 2, "direction": 0, "lcp2_mm": 5}
    assert r.scan(snap([(1, 2, 0, 5, True)], gaps=5)) == [], "the same counter again is nothing"


def test_a_counter_that_went_down_is_a_restarted_drive_node():
    r = MarkerReader()
    r.scan(snap(gaps=9))
    assert r.scan(snap(gaps=1, gen=1)) == [] and r.holes == 0
    assert r.scan(snap(gaps=2, gen=1)) == [(0, 0, 0, 1, False)]


def test_the_counter_is_followed_across_marker_generations():
    """An MLS reboot while moving starts a new marker generation; the holes still count."""
    r = MarkerReader()
    r.scan(snap([(1, 2, 0, 0, True)], gaps=4, gen=0))
    assert r.scan(snap([(1, 3, 0, 0, True)], gaps=6, gen=1)) == [(3, 0, 0, 0, True), (0, 0, 0, 2, False)]


def test_no_counter_in_the_snapshot_is_no_hole():
    r = MarkerReader()
    assert r.scan(snap([(1, 2, 0, 0, True)])) == [(2, 0, 0, 0, True)] and r.holes == 0


# -- the job and tape_run --------------------------------------------------------------

def test_the_log_names_a_hole_not_marker_0():
    w = with_gaps(World(None))
    w.tick()                              # the baseline
    w.gaps = 2
    w.tick()
    log = w.job.drain_marker_events()
    assert ("warn", "TPDO1 hole (2): markers may have been missed") in log
    assert not any("marker 0" in text for _l, text in log)
    assert w.job.marker_snapshot()["last_marker"] == 0 and w.job.state == lj.IDLE


def test_a_hole_while_driving_a_marker_run_holds_for_a_person():
    w = with_gaps(started())
    w.tick()
    assert w.job.state == lj.RUNNING
    w.gaps += 1
    w.tick()
    assert w.job.state == lj.HOLD and w.job.hold_cause == "markers", w.job.reason
    assert "TPDO1 hole" in w.job.reason


def test_a_hole_at_high_drops_high():
    w = with_gaps(_at_high())
    w.tick()
    assert w.job.tape.speed.high
    w.gaps += 1
    w.tick()
    assert not w.job.tape.speed.high and "TPDO1 hole" in w.job.tape.speed.reason


def test_a_hole_matches_no_zone_code():
    w = with_gaps(_at_high())
    w.gaps = 0
    w.tick()
    state = w.job.tape.speed.state
    t = w.job.tape
    t.markers([(0, 0, 0, 0, False)], True, True, w.job.f)
    assert t.speed.state == state, "code 0 with no gap does nothing"


# -- H-P2-3: a stale #LCP aborts an open fork episode ---------------------------------

def _runtime():
    """No map and no mission: only the shadow fork detector (the teach pass has its own)."""
    return tape_runtime.TapeRuntime(None, tape_locator.Params(), maps_dir=".", state_dir=".",
                                    status="off: test")


def test_a_stale_reading_aborts_an_open_fork_episode_with_a_warn():
    rt = _runtime()
    rt.tick(0.0, 1.00, 2, True)
    rt.tick(0.1, 1.05, 3, False)          # two tracks: an episode opens
    assert rt._forks.open
    rt.tick(0.2, 1.10, None, False)       # the MLS reading went stale
    assert not rt._forks.open
    assert rt.drain_events() == [("warn", "shadow: fork episode aborted, the MLS reading went stale")]
    rt.tick(0.3, 1.20, 2, False)
    rt.tick(0.4, 1.50, 2, False)
    assert rt.drain_events() == [], "no episode is reported where the reading came back"


def test_a_teach_pass_drops_its_open_episode_too():
    from amr_line import tape_teach

    rt = _runtime()
    rt.recorder = tape_teach.PassRecorder("C-MRU")
    rt.tick(0.0, 1.00, 2, True)
    rt.tick(0.1, 1.05, 6, False)
    rt.tick(0.2, 1.10, None, False)
    assert not rt.recorder.forks_seen.open and rt.recorder.forks == []
    assert ("warn", "teach pass: fork episode aborted, the MLS reading went stale") in rt.drain_events()


def test_a_stale_reading_with_no_open_episode_says_nothing():
    rt = _runtime()
    rt.tick(0.0, 1.0, 2, True)
    rt.tick(0.1, 1.1, None, True)
    assert rt.drain_events() == []


# -- H-P1-7: the curve guard reads the larger yaw rate --------------------------------

def test_a_frozen_gyro_cannot_keep_high_through_a_corner():
    w = _at_high()
    w.yaw = 0.0                           # the gyro reads nothing...
    w.drive(0.1, curve_yaw_rate=1.0)      # ...the wheels turn ~1.2 1/m: a corner
    assert not w.job.tape.speed.high and "curve guard" in w.job.tape.speed.reason


def test_without_the_curve_rate_the_guard_reads_yaw_rate_as_before():
    w = _at_high()
    w.yaw = 0.0
    w.drive(0.1)
    assert w.job.tape.speed.high
