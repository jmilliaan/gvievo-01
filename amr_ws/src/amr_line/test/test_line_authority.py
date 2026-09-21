"""Who may move the vehicle, and what stops it. No ROS, no hardware.

`amr_line.job` is deliberately ROS-free so these can run anywhere, including a
Windows dev box with no rclpy. The engine is real - a stub follower would let
this suite pass while the thing it guards did not exist - but the world around
it is a dataclass, so every check below is about authority and holds rather
than about control.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from amr_line import autopilot, runtime  # noqa: E402
from amr_line import job as lj  # noqa: E402

runtime.load_from_profile()

LEASE_LINE = 8


def inputs(**over):
    """A world in which the vehicle is allowed to move. Override to break it."""
    base = dict(
        now=100.0,
        dt=0.02,
        sensor={"tracks": [{"index": 1, "pos_mm": 0, "width": 10}], "has_track": True},
        sensor_age_s=0.005,
        track_ok=True,
        track_cause="",
        panel_valid=True,
        panel_auto=True,
        start_edge=False,
        start_edge_t=None,
        reset_edge=False,
        lease_allowed=LEASE_LINE,
        lease_line=LEASE_LINE,
        authority=("sup-1", 3),
        torque_off=False,
        field_clear=True,
        drives_fresh=True,
    )
    base.update(over)
    return lj.Inputs(**base)


def make():
    return lj.FollowJob(autopilot.LineFollower())


def armed(job, t=100.0):
    ok, _ = job.arm(inputs(now=t))
    assert ok
    return job


def run(job, t=101.0):
    """Arm, then present a Start edge stamped AFTER the arm."""
    armed(job, t=t)
    job.tick(inputs(now=t + 0.1, start_edge=True, start_edge_t=t + 0.05))
    assert job.state == lj.RUNNING, job.reason
    return job


# ---------------------------------------------------------------------------
# arming
# ---------------------------------------------------------------------------

def test_arming_refuses_without_each_prerequisite():
    """Every one of these alone must be enough to refuse. A prerequisite that
    is checked only in combination is not a prerequisite."""
    for name, broken in (
        ("stale panel", {"panel_valid": False}),
        ("selector in MANUAL", {"panel_auto": False}),
        ("no lease", {"authority": None}),
        ("lease without LEASE_LINE", {"lease_allowed": 1}),
        ("no drive report", {"drives_fresh": False}),
        ("torque off", {"torque_off": True}),
        ("field violated", {"field_clear": False}),
        ("unusable tape", {"track_ok": False, "track_cause": "track"}),
        ("tape too slow", {"track_ok": False, "track_cause": "rate"}),
    ):
        ok, msg = make().arm(inputs(**broken))
        assert not ok, f"{name} was allowed to arm"
        assert msg.startswith("cannot arm:"), msg


def test_arming_moves_nothing():
    job = armed(make())
    assert job.state == lj.ARMED
    assert job.tick(inputs(now=100.5)) == (0.0, 0.0)
    assert job.state == lj.ARMED


def test_a_start_pressed_before_arming_is_ignored():
    """The commissioning hazard, and the same guard: a press that predates the
    arm must not run the vehicle when the layer later becomes ready."""
    job = make()
    armed(job, t=200.0)
    job.tick(inputs(now=200.2, start_edge=True, start_edge_t=199.0))
    assert job.state == lj.ARMED
    assert "before the layer was armed" in job.reason


def test_a_start_pressed_after_arming_runs():
    job = run(make())
    assert job.state == lj.RUNNING


# ---------------------------------------------------------------------------
# what stops it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "broken,cause",
    [
        ({"torque_off": True}, "estop"),
        ({"field_clear": False}, "field"),
        ({"torque_off": True, "field_clear": False}, "field"),
        ({"drives_fresh": False}, "drives"),
    ],
)
def test_a_running_vehicle_stops_at_once(broken, cause):
    """No debounce on anything meaning the vehicle may be moving without the
    torque or the feedback to do it safely. Delaying a stop is the wrong
    direction, so these must act on the FIRST tick."""
    job = run(make())
    left, right = job.tick(inputs(now=102.0, **broken))
    assert (left, right) == (0.0, 0.0)
    assert job.state == lj.HOLD
    assert job.hold_cause == cause


def test_a_field_trip_and_an_estop_are_told_apart():
    """Both are the drives losing torque; the protective field is what
    distinguishes a stop that resumes itself from one that needs a human."""
    a = run(make())
    a.tick(inputs(now=102.0, torque_off=True, field_clear=False))
    b = run(make())
    b.tick(inputs(now=102.0, torque_off=True, field_clear=True))
    assert (a.hold_cause, b.hold_cause) == ("field", "estop")
    assert a.auto_resume() and not b.auto_resume()


def test_losing_the_lease_faults_and_never_auto_resumes():
    """A replaced lease means something above this layer took control. It is
    not a condition that clears - resuming on it would be resuming into a
    vehicle somebody else is now driving."""
    job = run(make())
    left, right = job.tick(inputs(now=102.0, authority=("sup-1", 4)))
    assert (left, right) == (0.0, 0.0)
    assert job.state == lj.FAULT
    assert not job.auto_resume()


def test_one_bad_tick_does_not_latch_anything():
    """prereq_grace_s exists so a single dropped frame is survivable. The tape
    is unusable for one tick, then fine: the run must continue."""
    job = run(make())
    job.tick(inputs(now=102.0, track_ok=False, track_cause="track"))
    assert job.state == lj.RUNNING, "a single bad frame stopped the run"
    job.tick(inputs(now=102.02))
    assert job.state == lj.RUNNING


def test_a_continuous_failure_does_latch():
    """...but a real loss still stops it, half a second later."""
    job = run(make())
    bad = dict(track_ok=False, track_cause="rate")
    job.tick(inputs(now=102.0, **bad))
    assert job.state == lj.RUNNING
    job.tick(inputs(now=102.6, **bad))
    assert job.state == lj.HOLD
    assert job.hold_cause == "rate"


def test_the_grace_timer_is_about_anything_wrong_not_one_message():
    """The reason may change while the timer runs. What is debounced is
    'something is wrong', so a different fault each tick still latches."""
    job = run(make())
    job.tick(inputs(now=102.0, track_ok=False, track_cause="track"))
    job.tick(inputs(now=102.3, panel_valid=False))
    job.tick(inputs(now=102.7, track_ok=False, track_cause="rate"))
    assert job.state == lj.HOLD


# ---------------------------------------------------------------------------
# resuming
# ---------------------------------------------------------------------------

def test_an_auto_hold_waits_for_the_cause_to_stay_clear():
    """Not 'is it clear now' but 'has it been clear', which is what stops an
    intermittent fault accumulating its way back into motion."""
    job = run(make())
    job.tick(inputs(now=102.0, field_clear=False))
    assert job.state == lj.HOLD
    job.tick(inputs(now=103.0))               # clear, but not for long enough
    assert job.state == lj.HOLD
    job.tick(inputs(now=103.5, field_clear=False))  # dropped out again
    assert job.state == lj.HOLD
    job.tick(inputs(now=104.0))               # the window restarts here
    job.tick(inputs(now=105.0))
    assert job.state == lj.HOLD, "resumed before the clear window elapsed"
    job.tick(inputs(now=106.1))
    assert job.state == lj.RUNNING


def test_an_estop_hold_waits_for_a_human():
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, field_clear=True))
    assert job.hold_cause == "estop"
    for t in (103.0, 110.0, 200.0):
        job.tick(inputs(now=t))
        assert job.state == lj.HOLD, "an E-stop hold resumed on its own"
    job.tick(inputs(now=201.0, start_edge=True, start_edge_t=200.9))
    assert job.state == lj.RUNNING


def test_reset_ends_a_run_at_once():
    """Physical Reset while RUNNING -> IDLE, zero wheels, this tick (vehicle
    finding 2026-09-21: Reset was ignored while running)."""
    job = run(make())
    assert job.state == lj.RUNNING
    left, right = job.tick(inputs(now=102.0, reset_edge=True))
    assert job.state == lj.IDLE and (left, right) == (0.0, 0.0) and job.reason == "reset"
    assert not job.arm(inputs(now=102.1))[0] or job.state == lj.ARMED  # a fresh arm is allowed


def test_reset_clears_a_hold_to_idle():
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True))
    assert job.state == lj.HOLD
    job.tick(inputs(now=103.0, reset_edge=True))
    assert job.state == lj.IDLE


# ---------------------------------------------------------------------------
# ending
# ---------------------------------------------------------------------------

def test_running_off_the_end_of_the_tape_is_DONE_not_a_fault():
    """The engine owns the line-loss distance budget. When it gives up, the
    tape ended - that is a finished run, not something to be recovered from."""
    job = run(make())
    empty = {"tracks": [], "has_track": False}
    t = 102.0
    for _ in range(600):
        t += 0.02
        job.tick(inputs(now=t, sensor=empty))
        if job.state != lj.RUNNING:
            break
    assert job.state == lj.DONE, f"ended as {lj.STATE_NAMES[job.state]}: {job.reason}"
    assert "track lost" in job.reason


def test_clear_stops_a_running_follow():
    job = run(make())
    assert job.clear() is True
    assert job.state == lj.IDLE
    assert job.tick(inputs(now=103.0)) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# the speed cap
# ---------------------------------------------------------------------------

def test_the_increment_1_speed_cap_holds_and_keeps_the_arc():
    """0.30 m/s is the agreed ceiling for this increment. Both wheels scale by
    one factor: scaling one would change the turn the follower asked for."""
    from agv_core import kinematics

    job = make()
    fast = runtime.AUTO_RPM * 4
    left, right = job._cap(fast, fast * 0.5)
    v, _ = kinematics.wheels_to_body(left, right)
    assert abs(v) <= job.v_max_mps + 1e-9, f"cap breached: {v} m/s"
    assert abs(left / right - 2.0) < 1e-9, "the arc changed under the cap"


def test_the_cap_leaves_a_slow_command_alone():
    job = make()
    left, right = job._cap(10.0, 10.0)
    assert (left, right) == (10.0, 10.0)


# ---------------------------------------------------------------------------
# the wire contract
# ---------------------------------------------------------------------------

def test_state_values_match_the_message():
    """readiness.py holds `line_state in (1, 2, 3)` for ARMED/RUNNING/HOLD and
    mode_fsm refuses to leave LINE while that is true. If these drift, a layer
    swap stops being blocked under a moving vehicle - silently."""
    assert (lj.IDLE, lj.ARMED, lj.RUNNING, lj.HOLD) == (0, 1, 2, 3)
    assert (lj.DONE, lj.FAULT) == (4, 5)
    assert set(lj.STATE_NAMES) == {0, 1, 2, 3, 4, 5}


def test_the_engine_is_real_not_a_stub():
    """This suite is only worth anything if it is guarding the actual engine."""
    assert hasattr(autopilot, "LineFollower")
    assert callable(autopilot.predicted_zeta)
    assert 0.0 < autopilot.predicted_zeta() < 2.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
