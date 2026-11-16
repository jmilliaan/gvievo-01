"""WP-C6 (cpu-load plan C#12, C#13): line_follow ticks at 10 Hz while idle and still, and an edge
gets its tick within one fast period. Pure: amr_line.tick_rate with fake rclpy timers on a fake
steady clock, around the real FollowJob."""

import pathlib

import pytest
from calling_world import settled
from test_mission_engine import World

from amr_line import job as lj
from amr_line import tick_rate as tr

FAST = 0.02
NODE = pathlib.Path(__file__).parent.parent / "amr_line" / "line_follow_node.py"


class Clock:
    def __init__(self, t):
        self.t = t


class FakeTimer:
    """rclpy.Timer as the node uses it: due one period after creation or reset(), then every
    period; cancel() stops it, reset() restarts it from now."""

    def __init__(self, clock, period):
        self.clock, self.period = clock, period
        self.due, self.on = clock.t + period, True

    def cancel(self):
        self.on = False

    def reset(self):
        self.on, self.due = True, self.clock.t + self.period


class Node:
    """The wrapper's scheduling, as line_follow_node wires it: two timers, edges call edge(), every
    tick ends with after_tick(quiet(...))."""

    def __init__(self, world, t0):
        self.w = world
        self.clock = Clock(t0)
        self.rate = tr.TickRate(FAST)
        self.fast, self.idle = FakeTimer(self.clock, FAST), FakeTimer(self.clock, tr.IDLE_DT)
        self.rate.bind(self.fast, self.idle)
        self.ticks = []
        self.start_edge_t = None
        self.last = t0

    def step(self):
        """Run the next due timer's tick."""
        on = [x for x in (self.fast, self.idle) if x.on]
        assert len(on) == 1, "exactly one tick timer runs"
        timer = on[0]
        now = self.clock.t = timer.due
        timer.due += timer.period
        dt, self.last = now - self.last, now
        start, self.start_edge_t = self.start_edge_t, None
        w = self.w
        w.t = now - 0.02                    # World.tick adds its 0.02
        w.tick(dt=min(dt, 5 * FAST), start_edge=start is not None, start_edge_t=start)
        self.ticks.append(now)
        self.rate.after_tick(now, tr.quiet(w.job.state, w.still, False))
        return now

    def run_until(self, t):
        while min(x.due for x in (self.fast, self.idle) if x.on) <= t:
            self.step()
        self.clock.t = t

    def press_start(self, t):
        self.run_until(t)
        self.start_edge_t = t               # _on_panel: latched, then _wake()
        self.rate.edge()

    def order(self, t):
        self.run_until(t)
        assert self.w.job.order_request("O1", "M1")[0]   # _srv_order: taken, then _wake()
        self.rate.edge()


def until_state(n, state, limit=1.0):
    t_end = n.clock.t + limit
    while n.clock.t < t_end:
        now = n.step()
        if n.w.job.state == state:
            return now
    raise AssertionError(f"never {lj.STATE_NAMES[state]}: {n.w.job.reason}")


# -- the pure parts ------------------------------------------------------------------

def test_idle_is_idle_done_fault_with_the_wheels_still_and_no_teach_pass():
    # At HOME waiting for an order the job is IDLE (start-up, Reset, a cleared run) or DONE
    # (_arrive_home after a trip): both are idle.
    for s in (lj.IDLE, lj.DONE, lj.FAULT):
        assert tr.quiet(s, True, False)
        assert not tr.quiet(s, False, False), "moving, or wheels unknown"
        assert not tr.quiet(s, True, True), "a teach pass records"
    for s in (lj.ARMED, lj.RUNNING, lj.HOLD):
        assert not tr.quiet(s, True, False)


def test_the_imu_is_read_only_where_the_job_may_drive():
    assert [s for s in range(6) if tr.imu_wanted(s)] == [lj.ARMED, lj.RUNNING, lj.HOLD]


def test_it_goes_idle_after_a_second_of_quiet_and_back_on_motion_at_once():
    c = Clock(0.0)
    r = tr.TickRate(FAST)
    f, i = FakeTimer(c, FAST), FakeTimer(c, tr.IDLE_DT)
    r.bind(f, i)
    assert f.on and not i.on
    for k in range(50):
        c.t = k * FAST
        r.after_tick(c.t, True)
        assert not r.idle
    c.t = 1.0
    assert r.after_tick(c.t, True) and r.idle and i.on and not f.on and i.due == pytest.approx(1.1)
    c.t = 1.1
    assert r.after_tick(c.t, False) and not r.idle and f.on and not i.on
    assert f.due == pytest.approx(1.12), "the fast timer was reset: the next tick 20 ms on"


def test_an_edge_at_the_fast_rate_does_not_delay_the_next_tick():
    c = Clock(0.0)
    r = tr.TickRate(FAST)
    f, i = FakeTimer(c, FAST), FakeTimer(c, tr.IDLE_DT)
    r.bind(f, i)
    c.t = 0.015
    assert not r.edge() and f.due == pytest.approx(0.02)


def test_periods_are_checked():
    with pytest.raises(ValueError):
        tr.TickRate(0.2, 0.1)


def test_the_node_wires_both_timers_and_wakes_on_every_edge():
    src = NODE.read_text(encoding="utf-8")
    assert "self._ticks.bind(self.create_steady_timer(self.dt, self._tick)," in src
    assert src.count("self._wake()") == 2, "Start/Reset edge (_on_panel) and an order taken (_srv_order)"
    assert '"/odom_raw"' not in src and src.count('"/imu/data"') == 1


# -- latency against the real job ------------------------------------------------------

@pytest.mark.parametrize("phase", [0.0, 0.013, 0.051, 0.0999])
def test_a_start_edge_at_the_idle_rate_arms_within_20_ms(phase):
    w = World(None)
    w.still = True
    n = Node(w, w.t)
    n.run_until(w.t + 2.0)
    assert n.rate.idle and w.job.state == lj.IDLE
    t0 = n.ticks[-1]
    assert n.ticks[-1] - n.ticks[-2] == pytest.approx(tr.IDLE_DT), "10 Hz while idle"
    t_edge = t0 + phase
    n.press_start(t_edge)
    t_armed = until_state(n, lj.ARMED)
    assert t_armed - t_edge <= FAST + 1e-9, (t_edge, t_armed)


@pytest.mark.parametrize("phase", [0.0, 0.037, 0.0999])
def test_an_order_taken_at_the_idle_rate_departs_within_20_ms(phase):
    w = settled()
    n = Node(w, w.t)
    n.run_until(w.t + 3.0)
    assert n.rate.idle and w.job.state == lj.IDLE and w.not_ready() == [], w.not_ready()
    t_edge = n.ticks[-1] + phase
    n.order(t_edge)
    t_armed = until_state(n, lj.ARMED)
    assert t_armed - t_edge <= FAST + 1e-9, (t_edge, t_armed)
    assert w.job.wants_power() and w.job.order_snapshot()["active"]
    assert not n.rate.idle
    assert until_state(n, lj.RUNNING, 3.0), "and on through the warning at 50 Hz"


def test_an_order_is_settled_and_taken_at_the_idle_rate():
    """Start-up SETTLING is time-based: it ends at 10 Hz as at 50 Hz."""
    from calling_world import SETTLE, calling

    w = calling()
    n = Node(w, w.t)
    n.run_until(w.t + SETTLE + 1.5)
    assert n.rate.idle and w.not_ready() == [], w.not_ready()
    t_edge = n.clock.t + 0.03
    n.order(t_edge)
    assert until_state(n, lj.ARMED) - t_edge <= FAST + 1e-9
