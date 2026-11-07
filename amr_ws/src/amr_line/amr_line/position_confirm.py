"""Automatic confirm of the position at HOME (manuals/home-auto-confirm-plan.md). Pure and clock-fed.

Two triggers, one check:
    press()    an At home press, once. A person is at the vehicle.
    recovery   parked at HOME with the monitor LOST: a finished loop, or a LOST while parked. It asks the
               node to re-seed AMCL at HOME, and retries while parked.

tick() returns what the node must do now: SEED (publish HOME on /initialpose), CONFIRM (call the monitor's
confirm service, then reply()), or "". The monitor checks again on confirm, so nothing here loosens what
READY needs. Nothing here commands motion, and a recovery touches neither the locator nor the wheel
baseline: those are the evidence that the AGV is home, and they record a person's At home.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from agv_core import position_status as status

from amr_line import order

UNLOCALIZED, CHECKING, READY, LOST = 0, 1, 2, 3  # LocalizationState.state
SEED, CONFIRM = "seed", "confirm"
PRESS, RECOVERY = "press", "recovery"
MAX_YAW_RAD = math.radians(15.0)


@dataclass(frozen=True)
class Params:
    at_home: bool
    recover: bool
    hold_s: float
    timeout_s: float
    max_offset_m: float
    settle_s: float
    retry_s: float
    wheel_dia_m: float

    @classmethod
    def from_profile(cls, v, calling):
        # Recovery only with calling on: only station orders read READY, and the job only keeps the
        # wheel baseline then. A Start from the panel needs neither.
        return cls(at_home=bool(v.TAPE_LOC_AUTO_CONFIRM_HOME),
                   recover=bool(v.TAPE_LOC_AUTO_RECOVER_HOME) and bool(calling),
                   hold_s=float(v.TAPE_LOC_CONFIRM_HOLD_S), timeout_s=float(v.TAPE_LOC_CONFIRM_TIMEOUT_S),
                   max_offset_m=float(v.TAPE_LOC_CONFIRM_MAX_OFFSET_M),
                   settle_s=float(v.TAPE_LOC_RECOVER_SETTLE_S), retry_s=float(v.TAPE_LOC_RECOVER_RETRY_S),
                   wheel_dia_m=float(v.WHEEL_DIA_M))


@dataclass
class Facts:
    now: float
    monitor_state: int | None = None    # the latest LocalizationState
    monitor_t: float | None = None      # when it arrived, on this clock
    can_confirm: bool = False
    scan_match: float = -1.0
    scan_long: float = -1.0
    job_idle: bool = False              # IDLE or DONE, no trip, no active order
    reset_edge: bool = False
    tape_seen: bool = False
    pose: tuple | None = None           # the latest AMCL (x, y, yaw)
    pose_t: float | None = None         # when it arrived, on this clock
    home: tuple | None = None           # the taught HOME (x, y, yaw)
    counts: tuple | None = None
    counts_per_rev: float = 0.0
    parked_at_home: bool = False        # locator healthy at HOME, wheel baseline still good
    wheels_still: bool = False


def _wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class PositionConfirm:
    def __init__(self, params: Params) -> None:
        self.p = params
        self.events: list[tuple[str, str]] = []  # ("info" | "warn", text), drained by the node
        self.detail = ""            # LineState.home_detail while it has something to say
        self._kind = None           # PRESS or RECOVERY while a check runs
        self._waiting_reply = False
        self._seed_t = 0.0
        self._base = None           # wheel counts at the seed
        self._hold_since = None
        self._settle_since = None
        self._retry_at = 0.0
        self._attempted = False     # a recovery ran since the monitor was last READY
        self._numbers = ""
        self._blocker = ""

    @property
    def checking(self) -> bool:
        return self._kind is not None

    def press(self, now: float, counts) -> None:
        """A person pressed At home, and its pose has been published."""
        self._kind = None
        self._attempted = False
        self.detail = ""
        if self.p.at_home:
            self._begin(PRESS, now, counts)

    def reply(self, now: float, ok: bool, message: str = "") -> None:
        """The monitor's answer to CONFIRM. A late one, after the check ended, changes nothing."""
        if self._kind is None or not self._waiting_reply:
            return
        if ok:
            self._succeed(self._numbers)
        else:
            self._end_badly(now, f"the monitor refused: {message}")

    def tick(self, f: Facts) -> str:
        if f.monitor_state == UNLOCALIZED:
            self._attempted = False
        if self._kind is not None:
            return self._check(f)
        if f.monitor_state == READY:
            self._attempted, self.detail = False, ""
            self._settle_since = None
            return ""
        if not f.job_idle:
            self.detail = ""        # a trip has moved on from whatever this said
        return self._maybe_recover(f)

    # -- recovery -----------------------------------------------------------------------------
    def _maybe_recover(self, f: Facts) -> str:
        if not self.p.recover:
            return ""
        lost = f.monitor_state == LOST or (f.monitor_state == CHECKING and self._attempted)
        if not (lost and f.job_idle and f.parked_at_home and f.wheels_still and f.tape_seen):
            self._settle_since = None
            if self.detail.startswith(status.RECHECKING):
                self.detail = ""
            return ""
        if self._settle_since is None:
            self._settle_since = f.now
        if not self.detail.startswith(status.RECHECKING):
            self.detail = status.RECHECKING
        if f.now - self._settle_since < self.p.settle_s or f.now < self._retry_at:
            return ""
        self._attempted = True
        self._begin(RECOVERY, f.now, f.counts)
        self.events.append(("info", "position lost at home: re-seeding AMCL at HOME and checking again"))
        return SEED

    # -- the check ----------------------------------------------------------------------------
    def _begin(self, kind, now, counts) -> None:
        self._kind, self._waiting_reply = kind, False
        self._seed_t, self._base = now, counts
        self._hold_since, self._settle_since = None, None
        self._numbers, self._blocker = "", "waiting for the monitor"
        self.detail = self._running_text()

    def _running_text(self) -> str:
        head = status.CHECKING if self._kind == PRESS else status.RECHECKING
        return f"{head}: {self._blocker}"

    def _check(self, f: Facts) -> str:
        fresh = f.monitor_t is not None and f.monitor_t > self._seed_t
        if fresh and f.monitor_state == READY:
            if self._waiting_reply:
                self._succeed(self._numbers)
            else:                   # a person pressed Confirm on Mapping or Teach
                self.events.append(("info", "position confirmed by hand during the automatic check"))
                self._finish()
            return ""
        why = self._cancel_reason(f)
        if why:
            self._end_badly(f.now, why)
            return ""
        if f.now - self._seed_t >= self.p.timeout_s:
            self._end_badly(f.now, self._blocker)
            return ""
        if self._waiting_reply:
            return ""
        self._blocker = self._blocking(f, fresh)
        self.detail = self._running_text()
        if self._blocker:
            self._hold_since = None
            return ""
        if self._hold_since is None:
            self._hold_since = f.now
        if f.now - self._hold_since < self.p.hold_s:
            return ""
        self._waiting_reply = True
        self._numbers = (f"match {100 * f.scan_match:.0f} %, through {100 * f.scan_long:.0f} %, "
                         f"pose {math.hypot(f.pose[0] - f.home[0], f.pose[1] - f.home[1]):.2f} m from HOME")
        return CONFIRM

    def _cancel_reason(self, f: Facts) -> str:
        if f.reset_edge:
            return "Reset was pressed"
        if not f.job_idle:
            return "a trip or a fault took over"
        if self._kind == RECOVERY and not f.parked_at_home:
            return "no longer parked at HOME"
        if f.counts is not None and f.counts_per_rev:
            if self._base is None:
                self._base = f.counts
            elif order.wheels_moved(f.counts, self._base, f.counts_per_rev, self.p.wheel_dia_m):
                return "the wheels moved"
        return ""

    def _blocking(self, f: Facts, fresh: bool) -> str:
        """The first condition not met, in the words the operator reads; "" when all are."""
        if not fresh:
            return "waiting for the monitor"
        if f.monitor_state != CHECKING:
            return "the monitor says position lost"
        if not f.can_confirm:
            if f.scan_match < 0.0:
                return "waiting for the scans"
            return f"scans not settled: match {100 * f.scan_match:.0f} %, through {100 * f.scan_long:.0f} %"
        if not f.tape_seen:
            return "tape not seen"
        if f.counts is None or not f.counts_per_rev:
            return "wheel counts unavailable"
        if f.pose is None or f.pose_t is None or f.pose_t <= self._seed_t:
            return "waiting for AMCL"
        if f.home is None:
            return "no taught HOME"
        off = math.hypot(f.pose[0] - f.home[0], f.pose[1] - f.home[1])
        if off > self.p.max_offset_m:
            return f"AMCL pose {off:.1f} m from HOME"
        yaw = abs(_wrap(f.pose[2] - f.home[2]))
        if yaw > MAX_YAW_RAD:
            return f"AMCL heading {math.degrees(yaw):.0f} deg from HOME"
        return ""

    # -- endings ------------------------------------------------------------------------------
    def _finish(self) -> None:
        self._kind, self._waiting_reply, self._attempted = None, False, False
        self.detail = ""

    def _succeed(self, numbers: str) -> None:
        head = "position confirmed at home" if self._kind == PRESS else "position recovered at home"
        self.events.append(("info", f"{head}: {numbers}"))
        self._finish()

    def _end_badly(self, now: float, why: str) -> None:
        kind, self._kind, self._waiting_reply = self._kind, None, False
        self._settle_since = None
        if kind == RECOVERY:
            self._retry_at = now + self.p.retry_s
            self.detail = f"{status.RECHECKING}: {why}"
        else:
            self.detail = f"{status.FAILED}: {why}"
        self.events.append(("warn", self.detail))
