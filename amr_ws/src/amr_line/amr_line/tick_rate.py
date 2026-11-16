"""line_follow's tick rate and its /imu/data subscription (cpu-load plan C#12, C#13; unified plan
WP-C6, 2026-11-16). Pure and clock-fed: the node owns the two timers and the subscription.

50 Hz whenever anything may move or is about to. 10 Hz while the job sits in IDLE, DONE or FAULT
with the wheels proven still (fresh /wheel_states) and no teach pass recording. At HOME waiting for
a station order the job is IDLE (after start-up, a Reset, a cleared run) or DONE (after a trip's
_arrive_home), so both count as idle.

An edge a tick must act on - a Start or Reset press, a station order or its cancel taken by
_srv_order - goes back to 50 Hz and RESETS the fast timer, so the tick that acts on it comes one
fast period after it: <= 20 ms. Nothing an edge sets is lost at 10 Hz meanwhile: the node latches
the press, the job latches the order, the marker and RFID streams are queues. A tick that sees
motion goes back to 50 Hz at once. Going idle waits IDLE_AFTER_S of quiet ticks, so the gap
between two jogs or a refused order does not flap the rate.

Each tick also builds trip-log rows (only ARMED/RUNNING/HOLD: never at the idle rate), publishes
OrderState on change (at most one idle period late, and the tick that takes an order or a cancel
runs fast) and runs _position_tick (time-based; its Reset edge is one of the edges above).
"""

from __future__ import annotations

from amr_line import job as lj

IDLE_DT = 0.1        # 10 Hz
IDLE_AFTER_S = 1.0   # quiet this long at the fast rate before dropping to IDLE_DT

_IDLE_STATES = (lj.IDLE, lj.DONE, lj.FAULT)
_IMU_STATES = (lj.ARMED, lj.RUNNING, lj.HOLD)


def quiet(state: int, wheels_still: bool, teaching: bool) -> bool:
    """May this tick's successor come at the idle rate? Unknown wheels are not still."""
    return state in _IDLE_STATES and bool(wheels_still) and not teaching


def imu_wanted(state: int) -> bool:
    """/imu/data feeds the curve guard and the U-turn: only a job that may drive reads it. ARMED
    subscribes, so the pre-move warning (auto_start_delay_s) gives it samples before RUNNING."""
    return state in _IMU_STATES


class TickRate:
    """Which of the node's two tick timers runs (`idle` False = the fast one). The timers are
    anything with rclpy's cancel() and reset(): reset() restarts a timer one period from now,
    and un-cancels it."""

    def __init__(self, fast_dt: float, idle_dt: float = IDLE_DT, idle_after_s: float = IDLE_AFTER_S):
        if not 0.0 < fast_dt <= idle_dt:
            raise ValueError(f"tick periods: fast {fast_dt} must be > 0 and <= idle {idle_dt}")
        self.fast_dt, self.idle_dt, self.idle_after_s = float(fast_dt), float(idle_dt), float(idle_after_s)
        self.idle = False
        self.switches = 0
        self._quiet_since: float | None = None
        self._fast = self._idle = None

    def bind(self, fast_timer, idle_timer) -> None:
        """The two timers, both just created (running): the fast one runs first."""
        self._fast, self._idle = fast_timer, idle_timer
        idle_timer.cancel()

    def _switch(self, idle: bool) -> None:
        self.idle = idle
        self.switches += 1
        on, off = (self._idle, self._fast) if idle else (self._fast, self._idle)
        off.cancel()
        on.reset()

    def edge(self) -> bool:
        """An edge arrived between ticks. At the idle rate: the fast timer, reset, so the tick that
        acts on it comes one fast period from now (True). At the fast rate nothing: resetting a
        running fast timer would only delay its next tick."""
        self._quiet_since = None
        if not self.idle:
            return False
        self._switch(False)
        return True

    def after_tick(self, now: float, is_quiet: bool) -> bool:
        """At the end of every tick (`quiet()` of it). True when the timer changed."""
        if not is_quiet:
            self._quiet_since = None
            if self.idle:
                self._switch(False)
                return True
            return False
        if self._quiet_since is None:
            self._quiet_since = now
        if not self.idle and now - self._quiet_since >= self.idle_after_s:
            self._switch(True)
            return True
        return False
