"""CPU (2026-10-24): commissioning's tick timer runs at rate_hz only while a job exists.

Idle it ticks at idle_period through the timer's own period; a 50 Hz tick that
returned early still cost an executor wakeup each. A plan must switch to rate_hz
at once (the Start press is read on the fast tick), and the end of a job must
switch back. The last test checks the rclpy behaviour the switch relies on.
"""

from __future__ import annotations

import time

import pytest

from amr_base import commissioning as cj
from amr_base import commissioning_node as cn


class FakeTimer:
    def __init__(self, period_ns: int) -> None:
        self.timer_period_ns, self.resets = period_ns, 0

    def reset(self) -> None:
        self.resets += 1


class FakeJob:
    def __init__(self, phase: int) -> None:
        self.phase = phase


def node(phase=cj.IDLE):
    n = cn.CommissioningNode.__new__(cn.CommissioningNode)
    n.dt, n.idle_period = 0.02, 0.5
    n._tick_timer, n._tick_fast = FakeTimer(int(0.5e9)), False
    n.job = FakeJob(phase)
    return n


def test_switches_only_on_a_change_and_resets_the_schedule():
    n = node()
    n._set_tick_rate(False)
    assert n._tick_timer.resets == 0, "idle -> idle: untouched"
    n._set_tick_rate(True)
    assert n._tick_timer.timer_period_ns == int(0.02e9) and n._tick_timer.resets == 1
    n._set_tick_rate(True)
    assert n._tick_timer.resets == 1, "fast -> fast: no reset on every tick"
    n._set_tick_rate(False)
    assert n._tick_timer.timer_period_ns == int(0.5e9) and n._tick_timer.resets == 2


def test_job_phases_are_exactly_the_non_idle_ones():
    assert set(cn.JOB_PHASES) == {cj.PREPARED, cj.RUNNING, cj.SETTLING}
    assert set(cn.JOB_PHASES).isdisjoint({cj.IDLE, cj.DONE, cj.ABORTED})


def test_no_timer_is_harmless():
    n = node()
    n._tick_timer = None  # nodes built with __new__ in other tests
    n._set_tick_rate(True)
    assert n._tick_fast is False


def test_a_held_plan_switches_to_rate_hz_before_the_reply():
    n = node()
    n.job = type("J", (), {"phase": cj.IDLE, "plan_id": "p1"})()

    def plan(*_a, **_k):
        n.job.phase = cj.PREPARED
        return "{}"

    n.job.plan = plan
    n._feedback = lambda now: (None, 1000.0, True)
    n._authority = lambda now: (None, 0)
    n._mode_snapshot = lambda now: None
    n._pp_view = None
    n._publish_state = lambda: None
    n.get_logger = lambda: type("L", (), {"info": staticmethod(lambda _m: None)})()
    req = type("Q", (), {"plan_json": "{}"})()
    res = cn.CommissioningNode._srv_plan(n, req, type("R", (), {})())
    assert res.ok and n._tick_fast and n._tick_timer.timer_period_ns == int(0.02e9)


def test_a_refused_plan_stays_idle():
    n = node()

    def plan(*_a, **_k):
        raise ValueError("no fresh wheel feedback")

    n.job = type("J", (), {"phase": cj.IDLE, "plan": staticmethod(plan)})()
    n._feedback = lambda now: (None, 0.0, None)
    n._authority = lambda now: (None, 0)
    n._mode_snapshot = lambda now: None
    n._pp_view = None
    res = cn.CommissioningNode._srv_plan(n, type("Q", (), {"plan_json": "{}"})(), type("R", (), {})())
    assert not res.ok and not n._tick_fast and n._tick_timer.resets == 0


def test_rclpy_period_change_needs_the_reset():
    """rcl keeps the next-call time on a period change; reset() moves it to now + period."""
    rclpy = pytest.importorskip("rclpy")
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node

    ctx = rclpy.Context()
    rclpy.init(context=ctx, domain_id=70)
    try:
        nd = Node("tick_rate_probe", context=ctx)
        ex = SingleThreadedExecutor(context=ctx)
        ex.add_node(nd)
        fired = []
        t = nd.create_timer(0.5, lambda: fired.append(time.monotonic()))
        t.timer_period_ns = int(0.02e9)
        t.reset()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.3:
            ex.spin_once(timeout_sec=0.05)
        assert len(fired) >= 5, f"fast ticks within 0.3 s of the switch: {len(fired)}"
        assert fired[0] - t0 < 0.1, "first fast tick must not wait out the old idle period"
        nd.destroy_node()
    finally:
        rclpy.try_shutdown(context=ctx)
