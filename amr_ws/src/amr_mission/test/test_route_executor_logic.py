"""R07/R18/R08 wiring in the route executor, without a ROS graph: the node object is
built with __new__ and only the state these methods read is set."""

import math
import threading
from types import SimpleNamespace

import pytest
from amr_navigation.compiler import ROTATE, STRAIGHT, CompiledStep
from test_goal_attempts import Client, Handle, Result

from amr_interfaces.msg import LocalizationState, PanelState, WheelStates
from amr_mission import goal_attempts as ga
from amr_mission import route_executor_node as ren
from amr_mission import run_fsm as fsm


class Logger:
    def info(self, *_a, **_k):
        pass

    warn = info


def make_node(steps, passes=1):
    n = ren.RouteExecutor.__new__(ren.RouteExecutor)
    n._lock = threading.RLock()
    n.clock = [100.0]
    n._now = lambda: n.clock[0]
    n.get_logger = lambda: Logger()
    n._log_state = lambda *_a: None
    n.fsm = fsm.RunFsm()
    assert n.fsm.load("m1", len(steps), passes)
    n.compiled = SimpleNamespace(steps=steps)
    n.route = SimpleNamespace(
        start=SimpleNamespace(x_m=0.0, y_m=0.0, yaw_rad=0.0),
        limits=SimpleNamespace(cross_track_limit_m=0.1, position_tolerance_m=0.05),
    )
    n.goals = ga.GoalAttempts(n._lock, n._now, n._on_goal_error)
    n.start_gate_m, n.start_gate_rad = 0.1, math.radians(5)
    n.w_eps, n.wheels_age, n.panel_age, n.loc_age = 0.02, 0.1, 0.2, 1.5
    n.scan_age, n._scan_t = float("inf"), 100.0  # freshness is exercised where a test sets scan_age
    n.centre_drift_m, n.turn_tol, n.wrong_way = 0.05, math.radians(2), math.radians(5)
    n.entry_corr_max, n.clear_stable_s = math.radians(10), 1.0
    n.goal_accept_timeout, n.goal_cancel_timeout = 5.0, 5.0
    n.converge_m = 1.0
    n.fp = SimpleNamespace(margin_m=0.20)
    n.odom_gap, n.paused_t = False, None
    n._odom_xy, n._odom_yaw_acc = (0.0, 0.0), 0.0
    loc = LocalizationState()
    loc.state = LocalizationState.READY
    n._loc, n._loc_t = loc, n.clock[0]
    panel = PanelState()
    panel.valid, panel.mode_auto = True, True
    n._panel, n._panel_t = panel, n.clock[0]
    n._scan = object()
    n._pose = lambda: (0.0, 0.0, 0.0)
    n._obstruction = lambda st, pose: None
    n._reset_step_state()
    n.clear_since = n.clock[0] - 10.0
    n.wheels(0.0, valid=True)
    return n


def _wheels(self, vel, valid=True):
    m = WheelStates()
    m.left_valid = m.right_valid = valid
    m.left_vel_rad_s = m.right_vel_rad_s = vel
    self._on_wheels(m)


ren.RouteExecutor.wheels = _wheels


def rotate(angle, sid="t1"):
    return CompiledStep(
        id=sid,
        type=ROTATE,
        start=(0.0, 0.0, 0.0),
        end=(0.0, 0.0, angle),
        signed_angle_rad=angle,
        time_allowance_s=10.0,
    )


def test_r07_fresh_but_invalid_wheel_feedback_fails_prerequisites():
    n = make_node([rotate(1.0)])
    assert n._prereqs() is None
    n.wheels(0.0, valid=False)
    assert n._prereqs() == "wheel feedback invalid"
    n.clock[0] += 1.0
    assert n._prereqs() == "wheel feedback stale"


def test_r18_aborted_turn_geometry_does_not_leak_into_the_next_run():
    n = make_node([rotate(math.pi / 2)])
    n.fsm.start(True, True)
    n.turn_centre, n.turn_target, n.turn_acc0 = (1.0, 1.0), math.pi / 2, 0.0
    n._odom_yaw_acc = 0.7
    n.fsm.abort("operator")
    n._interrupt("aborted")
    # a new mission is loaded: the executor's load path resets all per-step state
    assert n.fsm.load("m2", 1)
    n._reset_step_state()
    assert (n.turn_centre, n.turn_target, n.turn_acc0, n.turn_travelled) == (None, None, None, 0.0)
    assert n._remaining_turn(rotate(-1.0)) == -1.0


def test_r18_start_from_ready_resets_turn_state():
    n = make_node([rotate(1.0)])
    n.turn_centre, n.turn_target, n.turn_acc0 = (5.0, 5.0), 3.0, -2.0
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING
    assert (n.turn_centre, n.turn_target, n.turn_acc0) == (None, None, None)


def test_r18_pause_keeps_counting_rotation_until_standstill():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    n.turn_target, n.turn_centre = 1.0, (0.0, 0.0)
    n.turn_acc0, n.phase = 0.0, ren.PHASE_GOAL
    n._odom_yaw_acc = 0.4
    n.fsm.pause()
    n._interrupt("paused by operator")
    n._odom_yaw_acc = 0.5  # still decelerating after the pause
    assert math.isclose(n._remaining_turn(n._step()), 0.5)


def test_r18_start_edge_rechecks_a_prepared_resume():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    n.turn_centre = (0.0, 0.0)
    n.fsm.pause()
    n._interrupt("paused")
    ok, why = n._resume_checks()
    assert ok, why
    assert n.fsm.prepare_resume(ok, why)
    n._odom_xy = (0.2, 0.0)  # pushed off the turn centre after Prepare resume
    n._start_edge()
    assert n.fsm.state == fsm.PAUSED and "turn centre" in n.fsm.reason
    n._odom_xy = (0.0, 0.0)
    n.odom_gap = True
    assert n.fsm.prepare_resume(True, "")  # (as if prepared before the gap)
    n._start_edge()
    assert n.fsm.state == fsm.PAUSED and "odometry continuity" in n.fsm.reason


def test_r08_resume_waits_for_the_interrupted_goal_then_faults_after_the_bound():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    c = Client()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    n.phase = ren.PHASE_GOAL
    n.clock[0] += 30.0  # a long step: the bound runs from the pause, not from the send
    n._loc_t = n._panel_t = n.clock[0]
    n.wheels(0.0)
    n.fsm.pause()
    n._interrupt("paused")
    n.fsm.prepare_resume(True, "")
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING
    n._execute(n.clock[0])
    assert n.phase == ren.PHASE_INIT and len(c.sent) == 1  # no replacement goal yet
    h = Handle()
    c.sent[0][1].set_result(h)  # late acceptance of the paused goal
    assert h.cancels == 1
    n.clock[0] += 6.0
    n._execute(n.clock[0])
    assert n.fsm.state == fsm.FAULT and "not terminated" in n.fsm.reason
    assert not n.goals.outstanding


def test_r08_old_result_cannot_fault_the_resumed_attempt():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    c = Client()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    old = Handle()
    c.sent[0][1].set_result(old)
    n.fsm.pause()
    n._interrupt("paused")
    old.result_fut.set_result(Result(5))
    n.fsm.prepare_resume(True, "")
    n._start_edge()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    new = Handle()
    c.sent[1][1].set_result(new)
    assert n.goals.result is None and n.goals.handle is new and n.fsm.state == fsm.EXECUTING


def test_r20_step_done_advances_passes_through_the_node_reset():
    n = make_node([rotate(1.0, "a"), rotate(-1.0, "b")], passes=2)
    n.fsm.start(True, True)
    seen = []
    while n.fsm.state == fsm.EXECUTING:
        seen.append((n.fsm.pass_index, n._step().id))
        n.turn_target = 9.0
        n.fsm.step_done()
        n._reset_step_state()
        assert n.turn_target is None
    assert seen == [(0, "a"), (0, "b"), (1, "a"), (1, "b")] and n.fsm.state == fsm.DONE


def test_straight_stops_itself_at_the_endpoint_when_the_goal_checker_misses():
    st = CompiledStep("s1", STRAIGHT, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), length_m=2.0)
    n = make_node([st])
    n.fsm.start(True, True)
    c = Client()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    h = Handle()
    c.sent[0][1].set_result(h)
    n.phase = ren.PHASE_GOAL
    n._pose = lambda: (1.95, 0.04, 0.0)  # still short: keep following
    n._execute(n.clock[0])
    assert n.phase == ren.PHASE_GOAL and h.cancels == 0
    n._pose = lambda: (2.03, 0.04, 0.0)  # past the endpoint, 4 cm beside it: the checker's 2.5 cm miss
    n._execute(n.clock[0])
    assert n.phase == ren.PHASE_SETTLE and h.cancels == 1 and n.fsm.state == fsm.EXECUTING
    n._pose = lambda: (2.13, 0.04, 0.0)  # but well past it is still a fault
    n.phase = ren.PHASE_GOAL
    n._execute(n.clock[0])
    assert n.fsm.state == fsm.FAULT and "passed the endpoint" in n.fsm.reason


def test_cross_track_grace_is_independent_of_the_validated_margin():
    """Q05's clamp was dropped 2026-09-17 with the footprint margin at one cell (0.05 m)."""
    st = CompiledStep("s1", STRAIGHT, (0.0, 0.0, 0.0), (3.0, 0.0, 0.0), length_m=3.0)
    n = make_node([st])
    n.fp = SimpleNamespace(margin_m=0.05)
    n.fsm.start(True, True)
    c = Client()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    c.sent[0][1].set_result(Handle())
    n.phase = ren.PHASE_GOAL
    assert n._cross_track_allowed(0.5) == 0.20 and n._cross_track_allowed(2.0) == 0.10
    n._pose = lambda: (0.5, 0.15, 0.0)  # inside the grace band although beyond the validated clearance
    n._execute(n.clock[0])
    assert n.fsm.state != fsm.FAULT
    n._pose = lambda: (2.0, 0.15, 0.0)  # past the grace distance: the route's own limit applies
    n._execute(n.clock[0])
    assert n.fsm.state == fsm.FAULT and "cross-track" in n.fsm.reason


def test_q06_acknowledged_fault_keeps_the_unresolved_goal_barrier_across_a_new_run():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    c = Client()
    n.goals.send(c, "g", n.fsm.run_id, 0, 0)
    n.phase = ren.PHASE_GOAL
    n.fsm.pause()
    n._interrupt("paused")
    n.fsm.prepare_resume(True, "")
    n._start_edge()
    n.clock[0] += 6.0  # the cancellation bound passes with the goal's acceptance still pending
    n._loc_t = n._panel_t = n.clock[0]
    n._execute(n.clock[0])
    assert n.fsm.state == fsm.FAULT and "not terminated" in n.fsm.reason
    assert n.fsm.ack() if hasattr(n.fsm, "ack") else n.fsm.acknowledge()
    assert n.fsm.load("m2", 1, 1)
    assert "never reported terminal" in (n._prereqs() or "")  # READY cannot become a run
    h = Handle()
    c.sent[0][1].set_result(h)  # the old server finally answers: cancelled, then terminal
    h.result_fut.set_result(Result(5))
    n.wheels(0.0)  # fresh feedback again: only the barrier was in the way
    assert n._prereqs() is None


def test_q19_physical_reset_acknowledges_a_fault_at_rest_and_nothing_else():
    n = make_node([rotate(1.0)])
    n.fsm.start(True, True)
    n._fault("test fault")
    assert n.fsm.state == fsm.FAULT
    n.goals.unresolved.add(ga.Attempt("old", 0, 0, 1))  # a Q06 barrier Reset must not clear
    n.wheels(0.5)  # rolling: ignored
    n._reset_edge()
    assert n.fsm.state == fsm.FAULT
    n.wheels(0.0)
    n._reset_edge()
    assert n.fsm.state == fsm.IDLE and n.goals.barrier()  # acknowledged; barrier intact
    n._reset_edge()  # a repeated edge outside FAULT does nothing
    assert n.fsm.state == fsm.IDLE


# ---- Part B2: the FollowPath goal sits goal_overshoot_m past the endpoint ----


def _clock_stub(n):
    class T:
        def to_msg(self):
            from builtin_interfaces.msg import Time

            return Time()

    class C:
        def now(self):
            return T()

    n.get_clock = lambda: C()


def test_b2_follow_path_ends_goal_overshoot_past_the_endpoint_clamped_to_tolerance():
    samples = [(x / 10, 0.0, 0.0) for x in range(0, 21)]  # 0..2.0 m every 0.1 m
    st = CompiledStep("s1", STRAIGHT, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), length_m=2.0, samples=samples)
    n = make_node([st])
    _clock_stub(n)
    n.goal_overshoot_m = 0.045
    path = n._follow_path(st, 0.0)
    last = path.poses[-1].pose.position
    assert (round(last.x, 3), round(last.y, 3)) == (2.045, 0.0)
    assert round(path.poses[-2].pose.position.x, 3) == 2.0  # the true endpoint is still on the path
    n.goal_overshoot_m = 0.0  # rollback: the endpoint is the goal
    assert round(n._follow_path(st, 0.0).poses[-1].pose.position.x, 3) == 2.0
    n.goal_overshoot_m = 0.3  # clamped to position_tolerance_m (0.05)
    assert round(n._follow_path(st, 0.0).poses[-1].pose.position.x, 3) == 2.05
    # a resume from 1.0 m along keeps the same goal
    n.goal_overshoot_m = 0.045
    p = n._follow_path(st, 1.0)
    assert round(p.poses[0].pose.position.x, 1) == 0.9 and round(p.poses[-1].pose.position.x, 3) == 2.045
    # heading is honoured: a step along +y overshoots in +y
    st2 = CompiledStep(
        "s2",
        STRAIGHT,
        (0.0, 0.0, math.pi / 2),
        (0.0, 1.0, math.pi / 2),
        length_m=1.0,
        samples=[(0.0, y / 10, math.pi / 2) for y in range(0, 11)],
    )
    last = n._follow_path(st2, 0.0).poses[-1].pose.position
    assert (round(last.x, 3), round(last.y, 3)) == (0.0, 1.045)


def test_permit_carries_the_loaded_route_limits():
    st = CompiledStep("s1", STRAIGHT, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), length_m=2.0)
    n = make_node([st])
    _clock_stub(n)
    n.route.limits.linear_mps, n.route.limits.angular_rad_s = 0.40, 0.24
    n.generation, n._lease_instance, n._permit_seq = 3, "sup", 0
    published = []
    n._permit_pub = SimpleNamespace(publish=published.append)
    n.fsm.start(True, True)
    n.phase = ren.PHASE_GOAL
    n._publish_permit()
    m = published[-1]
    assert m.enabled and (m.v_max, m.w_max) == (pytest.approx(0.40), pytest.approx(0.24))
    n.route.limits.linear_mps = 0.15
    n._publish_permit()
    assert published[-1].v_max == pytest.approx(0.15)
