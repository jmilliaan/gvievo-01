"""Guided run (mission c-mru-guided, 2026-10-23): the engineer walks C-MRU beside the AGV and
gives each branch order by hand; the follower is capped at 0.3 m/s with no HIGH; ONE marker
code (3) is both the U-turn and the home stop, told apart by wheel travel since the pivot.
Real FollowJob, synthetic clock, wheel counts and marker stream."""
import os
import sys

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agv_core import config as vehicle  # noqa: E402
from agv_core import mission as missions  # noqa: E402
from test_marker_run import past_guard, pivot  # noqa: E402
from test_mission_engine import CENTRED, World  # noqa: E402

from amr_line import branch  # noqa: E402
from amr_line import job as lj  # noqa: E402

CODE = 3
FORK = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}, {"index": 3, "pos_mm": 45, "width": 10}],
        "has_track": True, "nlcp": 6, "track_level": 5}


def started():
    w = World(missions.load("c-mru-guided"))
    w.comms = False                     # no RFID at all
    w.start()
    w.drive(1.0)
    assert w.job.state == lj.RUNNING, w.job.reason
    return w


def test_cruise_is_capped_at_0_3_mps_and_corner_markers_do_nothing():
    w = started()
    cap = 0.3 * vehicle.RPM_PER_MPS
    w.drive(4.0)
    assert abs(w.job.diag["v_base"] - cap) < 1.0, w.job.diag["v_base"]
    for code in (1, 2):                 # the corner high-zone strips stay down: ignored
        w.mark(code)
        w.tick()
    w.drive(1.0)
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None and w.job.tape.uturn_req is None
    assert not w.job.tape.speed.high and w.job.diag["v_base"] <= cap + 1.0


def out_to_the_mru_end(w):
    w.drive(140.0)                      # > 40 m out at 0.3 m/s: the U-turn is armed
    assert w.job.tape._mrun_out_m > 40.0


def test_the_home_strip_crossed_after_start_is_not_the_u_turn():
    # 2026-10-23 16:13: code 3 read 1 s after Start -> U-turn approach -> the bay corner
    # 1.09 m on was taken for the tape end and it pivoted in the bay
    w = started()
    w.mark(CODE)
    w.tick()
    assert w.job.tape.uturn_req is None and w.job.tape.stop is None
    assert w.job.state == lj.RUNNING and w.job.tape.mrun_phase == "out"
    out_to_the_mru_end(w)
    w.mark(CODE)
    w.tick()
    past_guard(w)
    assert w.job.tape.uturn_req is not None, "past home_arm_m the code is the U-turn"


def test_one_code_turns_at_the_end_and_stops_at_home_only_after_home_arm_m():
    w = started()
    out_to_the_mru_end(w)
    w.mark(CODE)                        # out: the U-turn strip
    w.tick()
    past_guard(w)
    pivot(w)
    w.mark(CODE)                        # its own strip re-passed after the pivot: skipped
    w.tick()
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None
    w.drive(20.0)                       # ~6 m back at 0.3 m/s: still before home_arm_m (40 m)
    w.mark(CODE)
    w.tick()
    assert w.job.state == lj.RUNNING and w.job.tape.stop is None, "a stray code 3 is not home"
    w.drive(130.0)                      # well past 40 m since the pivot
    assert w.job.tape._mrun_back_m > 40.0
    w.mark(CODE)
    w.tick()
    past_guard(w)
    assert w.job.tape.stop is not None and w.job.tape.stop["where"] == "HOME-N"
    assert w.until(lambda: w.job.state == lj.DONE, 8.0), w.job.reason
    assert "HOME-N" in w.job.reason


def test_a_hand_order_is_one_shot_consumed_by_the_next_fork():
    w = started()
    ok, msg = w.job.order_branch("right")
    assert ok and "NEXT fork" in msg
    assert w.job.tape.branch.ladder.intent() == branch.RIGHT
    assert w.job.mission_snapshot()["branch_intent"] == "right"
    w.drive(0.3, sensor=FORK)           # the diverter under the sensor
    w.drive(0.3, sensor=CENTRED)        # out the other side: the order is spent
    assert w.job.tape.branch.ladder.intent() == branch.STRAIGHT and w.job.tape.branch.forks == 1
    ok, _ = w.job.order_branch("left")
    ok2, msg = w.job.order_branch("straight")
    assert ok and ok2 and "cleared" in msg and w.job.tape.branch.ladder.intent() == branch.STRAIGHT
    assert w.job.order_branch("up") == (False, "unknown branch order 'up': left, straight or right")


def test_an_order_standing_at_the_pivot_is_cleared():
    w = started()
    out_to_the_mru_end(w)
    w.job.order_branch("left")
    w.mark(CODE)
    w.tick()
    past_guard(w)
    pivot(w)
    assert w.job.tape.branch.ladder.intent() == branch.STRAIGHT


def test_hand_orders_are_refused_outside_a_guided_mission():
    w = World(missions.load("mru-straight-markers"))
    ok, msg = w.job.order_branch("left")
    assert not ok and "guided" in msg
    assert w.job.tape.branch.ladder.intent() == branch.STRAIGHT


TWO = {"tracks": [{"index": 2, "pos_mm": 0, "width": 10}, {"index": 3, "pos_mm": -60, "width": 10}],
       "has_track": True, "nlcp": 6, "track_level": 5}


def test_a_code_read_at_a_junction_is_ignored():
    # 2026-10-23 16:41: code 3 decoded at the X1 crossing started a U-turn approach, and
    # bursts of code 3 came in along the J-ML merge. A strip never shows two tracks.
    w = started()
    out_to_the_mru_end(w)
    w.drive(0.1, sensor=TWO)            # two tapes under the sensor, then the "marker"
    w.mark(CODE)
    w.tick()
    w.drive(2.0)
    assert w.job.tape.uturn_req is None and w.job.tape._mrun_pending is None
    w.mark(CODE)                        # the read first, the second tape right after it
    w.tick()
    w.drive(0.2, sensor=TWO)
    w.drive(2.0)
    assert w.job.tape.uturn_req is None and w.job.state == lj.RUNNING


def test_the_home_stop_still_counts_from_the_strip():
    w = started()
    out_to_the_mru_end(w)
    w.mark(CODE)
    w.tick()
    past_guard(w)
    pivot(w)
    w.drive(140.0)
    t = w.job.tape
    w.mark(CODE)
    w.tick()
    at = t._mrun_pending["at"]
    past_guard(w)
    assert abs(t.stop["distance_m"] + (t._odo_m - at) - 0.5) < 0.02, t.stop
