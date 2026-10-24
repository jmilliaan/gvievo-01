"""Guided run (mission c-mru-guided, 2026-10-23): the engineer walks C-MRU beside the AGV and
gives each branch order by hand; the follower is capped at 0.3 m/s outside HIGH; ONE marker
code (3) is both the U-turn and the home stop, told apart by wheel travel since the pivot.
The guide page's speed toggle (2026-10-24): NORMAL by default; HIGH lets the corner marker
pair (2 then 1) grant HIGH, as in any zoned mission.
Real FollowJob, synthetic clock, wheel counts and marker stream."""
import os
import sys

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agv_core import config as vehicle  # noqa: E402
from agv_core import mission as missions  # noqa: E402
from amr_line.tape_run import MARKER_JUNCTION_M as MARKER_GUARD  # noqa: E402
from test_marker_run import past_guard, pivot  # noqa: E402
from test_mission_engine import CENTRED, NO_TAPE, PER_REV, World  # noqa: E402

from amr_line import branch, uturn  # noqa: E402
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
    for code in (2, 1):                 # the corner zone strips, toggle at NORMAL: ignored
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


OUTER, INNER = 2, 1


def enter_zone(w):
    w.mark(OUTER)
    w.tick()
    w.drive(0.3)
    w.mark(INNER)
    w.tick()


def high_selected():
    w = started()
    assert w.job.mission_snapshot()["speed_select"] == "normal", "NORMAL at every mission load"
    ok, msg = w.job.select_speed(True)
    assert ok and "next zone entry" in msg, msg
    assert w.job.mission_snapshot()["speed_select"] == "high"
    return w


def test_high_selected_lets_only_the_marker_pair_grant_high():
    cap = 0.3 * vehicle.RPM_PER_MPS
    w = high_selected()
    w.drive(2.0)
    assert not w.job.tape.speed.high, "the toggle alone raises nothing"
    assert abs(w.job.diag["v_base"] - cap) < 1.0
    w.mark(INNER)                       # an inner without its outer: still NORMAL
    w.tick()
    w.drive(3.0)                        # 0.9 m on: beyond the exit-pair window before the entry
    assert not w.job.tape.speed.high
    enter_zone(w)
    assert w.job.tape.speed.high, w.job.tape.speed.reason
    assert w.job.diag["speed_target_rpm"] == vehicle.AUTO_HIGH_RPM, "the guided cap does not hold HIGH down"
    w.drive(5.0)
    assert w.job.diag["v_base"] == vehicle.AUTO_HIGH_RPM
    assert w.job.mission_snapshot()["high_speed"] is True
    w.mark(INNER)                       # the exit marker: NORMAL before the corner, then the cap
    w.tick()
    assert not w.job.tape.speed.high and "leaving the straight" in w.job.tape.speed.reason
    w.drive(5.0)
    assert abs(w.job.diag["v_base"] - cap) < 1.0, w.job.diag["v_base"]


def test_normal_selected_while_high_drops_it_at_once_and_ignores_the_codes():
    cap = 0.3 * vehicle.RPM_PER_MPS
    w = high_selected()
    enter_zone(w)
    w.drive(5.0)
    assert w.job.diag["v_base"] == vehicle.AUTO_HIGH_RPM
    ok, msg = w.job.select_speed(False)
    assert ok and "ignored" in msg
    assert not w.job.tape.speed.high and "guided page" in w.job.tape.speed.reason
    w.drive(5.0)
    assert abs(w.job.diag["v_base"] - cap) < 1.0
    enter_zone(w)
    w.drive(1.0)
    assert not w.job.tape.speed.high and abs(w.job.diag["v_base"] - cap) < 1.0


def test_the_selection_outlives_a_clear_but_not_a_mission_load():
    w = high_selected()
    w.job.clear()
    assert w.job.tape.high_select is True and w.job.mission_snapshot()["speed_select"] == "high"
    ok, _ = w.job.set_mission(missions.load("c-mru-guided"))
    assert ok and w.job.mission_snapshot()["speed_select"] == "normal"


def test_the_speed_toggle_needs_a_guided_mission_with_a_high_zone():
    cases = (("mru-straight-markers", "guided"), ("line-a", "guided"), ("slow-plain", "no high zone"))
    for name, why in cases:
        w = World(missions.load(name))
        ok, msg = w.job.select_speed(True)
        assert not ok and why in msg, (name, msg)
        assert w.job.mission_snapshot()["speed_select"] == "", name


def test_the_u_turn_marker_still_acts_at_high():
    w = high_selected()
    out_to_the_mru_end(w)
    enter_zone(w)
    w.drive(1.0)
    assert w.job.tape.speed.high
    w.mark(CODE)
    w.tick()
    past_guard(w)
    assert w.job.tape.uturn_req is not None and not w.job.tape.speed.high


def test_a_u_turn_strip_closer_to_the_tape_end_than_the_guard_still_turns():
    # 2026-10-24 10:57: code 3 read 0.12 m before the MRU tape end; the read waited out the
    # 0.3 m junction guard, the tape ran out first and the run ended "track lost"
    w = started()
    out_to_the_mru_end(w)
    w.mark(CODE)
    w.tick()
    t = w.job.tape
    assert t._mrun_pending is not None and t.uturn_req is None
    w.drive(0.3)                        # ~0.09 m on: still inside the guard
    assert t._mrun_pending is not None
    w.tick(sensor=NO_TAPE)              # one tick gone: a flicker, keeps going
    assert t.uturn_req is None and t._mrun_pending is not None
    w.tick(sensor=NO_TAPE)              # second: the tape ended
    assert t.uturn_req is not None and t.uturn_req["phase"] == "stopping", t.events
    assert 0.05 < t.uturn_req["travel_m"] < MARKER_GUARD
    assert w.job.state == lj.RUNNING and w.job.diag["v_base"] == 0.0
    w.still, w.integrate = True, False
    assert w.until(lambda: t.uturn is not None, 3.0, sensor=NO_TAPE), w.job.reason
    base = w.counts
    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (175, CENTRED)):
        c = uturn.counts_for_angle(deg, PER_REV)
        w.counts = (base[0] + int(round(c)), base[1] + int(round(-c)))
        w.tick(sensor=sensor)
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2)
    assert t.uturn_req is None and w.job.state == lj.RUNNING and t.mrun_phase == "back", w.job.reason


def test_the_tape_ending_with_no_read_pending_is_still_the_end_of_the_run():
    w = started()
    w.drive(2.0)
    assert w.until(lambda: w.job.state == lj.DONE, 3.0, sensor=NO_TAPE)
    assert "track lost" in w.job.reason and w.job.tape.uturn_req is None


def test_a_forced_u_turn_turns_at_the_next_tape_end_without_a_strip():
    # the guide page's fallback: the strip was missed, the engineer presses "U-turn at tape end"
    w = started()
    t = w.job.tape
    ok, msg = w.job.force_u_turn(True)
    assert ok and "NEXT tape end" in msg and t.uturn_forced
    w.drive(2.0)                        # it moves nothing by itself: still following at cruise
    assert t.uturn_req is None and w.job.state == lj.RUNNING and w.job.diag["v_base"] > 0
    w.tick(sensor=NO_TAPE)
    w.tick(sensor=NO_TAPE)              # the tape ends, no strip read at all
    assert t.uturn_req is not None and t.uturn_req["phase"] == "stopping" and not t.uturn_forced
    w.still, w.integrate = True, False
    assert w.until(lambda: t.uturn is not None, 3.0, sensor=NO_TAPE), w.job.reason
    base = w.counts
    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (175, CENTRED)):
        c = uturn.counts_for_angle(deg, PER_REV)
        w.counts = (base[0] + int(round(c)), base[1] + int(round(-c)))
        w.tick(sensor=sensor)
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2)
    assert t.uturn_req is None and w.job.state == lj.RUNNING and t.mrun_phase == "back", w.job.reason
    ok, msg = w.job.force_u_turn(True)  # on the way back it is refused
    assert not ok and "way out" in msg and not t.uturn_forced


def test_a_forced_u_turn_can_be_cancelled_and_needs_a_guided_mission():
    w = started()
    assert w.job.force_u_turn(True)[0]
    ok, msg = w.job.force_u_turn(False)
    assert ok and "cancelled" in msg and not w.job.tape.uturn_forced
    w.drive(1.0)
    assert w.until(lambda: w.job.state == lj.DONE, 3.0, sensor=NO_TAPE)
    assert "track lost" in w.job.reason
    plain = World(missions.load("line-a"))
    ok, msg = plain.job.force_u_turn(True)
    assert not ok and "guided" in msg


def test_a_forced_u_turn_still_takes_a_corner_as_a_kink():
    w = started()
    w.job.force_u_turn(True)
    edge = {"tracks": [{"index": 2, "pos_mm": -95, "width": 10}], "has_track": True, "nlcp": 2,
            "track_level": 5}
    w.drive(0.1, sensor=edge)
    w.tick(sensor=NO_TAPE)
    w.tick(sensor=NO_TAPE)
    assert w.job.kink is not None and w.job.tape.uturn_req is None and w.job.tape.uturn_forced


def spin_back(w):
    """From a U-turn already stopping at the tape end: spin cw onto the tape, resume, way back."""
    t = w.job.tape
    w.still, w.integrate = True, False
    assert w.until(lambda: t.uturn is not None, 3.0, sensor=NO_TAPE), w.job.reason
    base = w.counts
    for deg, sensor in ((40, NO_TAPE), (120, NO_TAPE), (175, CENTRED)):
        c = uturn.counts_for_angle(deg, PER_REV)
        w.counts = (base[0] + int(round(c)), base[1] + int(round(-c)))
        w.tick(sensor=sensor)
    w.drive(vehicle.U_TURN_RESUME_DELAY_S + 0.2)
    assert t.uturn_req is None and w.job.state == lj.RUNNING and t.mrun_phase == "back", w.job.reason
    w.still, w.integrate = False, True


def test_two_tapes_at_the_strip_then_the_tape_end_still_turns():
    # 2026-10-24 11:26: code 3 at the MRU end, two tracks 0.02 m on ("ignored: a junction"),
    # the tape ended 0.4 s later and the run ended "track lost"
    w = started()
    out_to_the_mru_end(w)
    w.mark(CODE)
    w.tick()
    w.drive(0.1, sensor=TWO)
    t = w.job.tape
    assert t._mrun_pending is not None, t.events
    w.tick(sensor=NO_TAPE)
    w.tick(sensor=NO_TAPE)
    assert t.uturn_req is not None and t.uturn_req["phase"] == "stopping", t.events
    spin_back(w)


def test_a_run_that_ended_at_the_tape_end_u_turns_on_the_next_start():
    w = started()
    out_to_the_mru_end(w)
    assert w.until(lambda: w.job.state == lj.DONE, 3.0, sensor=NO_TAPE)   # strip missed
    assert w.job.ended_at_end
    ok, msg = w.job.force_u_turn(True)
    assert ok and "press the physical Start" in msg, msg
    w.drive(1.0, sensor=NO_TAPE)
    assert w.job.state == lj.DONE                       # the web order moves nothing
    w.press_start()
    assert w.job.state == lj.ARMED, w.job.reason        # the pre-move warning, as any Start
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0, sensor=NO_TAPE), w.job.reason
    t = w.job.tape
    assert t.uturn_req is not None and t.mrun_phase == "out" and t._mrun_out_m > 40.0
    spin_back(w)


def test_without_the_order_a_start_at_the_tape_end_is_a_new_run_and_idle_refuses_it():
    w = started()
    out_to_the_mru_end(w)
    assert w.until(lambda: w.job.state == lj.DONE, 3.0, sensor=NO_TAPE)
    w.start()
    assert w.job.tape.uturn_req is None and w.job.tape._mrun_out_m < 1.0
    fresh = World(missions.load("c-mru-guided"))
    ok, msg = fresh.job.force_u_turn(True)
    assert not ok and "no run" in msg
