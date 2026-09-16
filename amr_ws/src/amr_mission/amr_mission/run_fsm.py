"""Route execution state machine (spec §7.1). Pure: transitions and their reasons only.

The node owns goals, poses and timers; this owns what state the run is in,
which run id is current, and whether a Start edge may continue. Every method
returns True if the transition happened, so callers can log refusals.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

IDLE, READY, EXECUTING, PAUSED, BLOCKED, FAULT, DONE = 0, 1, 2, 3, 4, 5, 6
NAMES = {
    IDLE: "IDLE",
    READY: "READY",
    EXECUTING: "EXECUTING",
    PAUSED: "PAUSED",
    BLOCKED: "BLOCKED",
    FAULT: "FAULT",
    DONE: "DONE",
}
ACTIVE = (EXECUTING, PAUSED, BLOCKED)


_counter = itertools.count(1)


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{next(_counter)}"


@dataclass
class RunFsm:
    state: int = IDLE
    reason: str = "no mission loaded"
    mission_id: str = ""
    run_id: str = ""
    n_steps: int = 0
    step_index: int = -1
    resume_prepared: bool = False
    history: list[tuple[int, str]] = field(default_factory=list)

    def _set(self, state: int, reason: str) -> bool:
        self.state, self.reason = state, reason
        self.history.append((state, reason))
        return True

    # ---- loading -------------------------------------------------------------------

    def load(self, mission_id: str, n_steps: int) -> bool:
        """A mission may be (re)loaded when nothing is running: IDLE, READY or DONE."""
        if self.state not in (IDLE, READY, DONE):
            self.reason = f"cannot load while {NAMES[self.state]}"
            return False
        self.mission_id, self.n_steps = mission_id, n_steps
        self.run_id, self.step_index, self.resume_prepared = "", -1, False
        return self._set(READY, f"mission {mission_id} loaded ({n_steps} steps); AUTO + Start to run")

    def unready(self, reason: str) -> bool:
        """A prerequisite lapsed while waiting (nothing was moving): back to IDLE, no acknowledgement."""
        if self.state != READY:
            return False
        return self._set(IDLE, reason)

    # ---- start / resume -------------------------------------------------------------

    def start(self, auto: bool, gate_ok: bool, gate_reason: str = "") -> bool:
        """Physical Start edge. From READY it begins a run; from PAUSED/BLOCKED with a
        prepared resume it continues the remaining step."""
        if self.state == READY:
            if not auto:
                self.reason = "Start ignored: selector is not AUTO"
                return False
            if not gate_ok:
                self.reason = f"Start refused: {gate_reason}"
                return False
            self.run_id, self.step_index = new_run_id(), 0
            return self._set(EXECUTING, f"run {self.run_id} started")
        if self.state in (PAUSED, BLOCKED):
            if not auto:
                self.reason = "Start ignored: selector is not AUTO"
                return False
            if not self.resume_prepared:
                self.reason = f"Start ignored: resume not prepared ({NAMES[self.state]})"
                return False
            self.resume_prepared = False
            return self._set(EXECUTING, f"resumed step {self.step_index}")
        self.reason = f"Start ignored in {NAMES[self.state]}"
        return False

    def prepare_resume(self, ok: bool, why: str) -> bool:
        if self.state not in (PAUSED, BLOCKED):
            self.reason = f"nothing to resume ({NAMES[self.state]})"
            return False
        self.resume_prepared = ok
        self.reason = "resume prepared: press Start to continue" if ok else f"resume refused: {why}"
        return ok

    def invalidate_resume(self, why: str) -> None:
        if self.resume_prepared:
            self.resume_prepared = False
            self.reason = f"prepared resume withdrawn: {why}"

    # ---- interruptions ----------------------------------------------------------------

    def pause(self, reason: str = "paused by operator") -> bool:
        if self.state != EXECUTING:
            self.reason = f"pause ignored in {NAMES[self.state]}"
            return False
        self.resume_prepared = False
        return self._set(PAUSED, reason)

    def block(self, reason: str) -> bool:
        if self.state != EXECUTING:
            return False
        self.resume_prepared = False
        return self._set(BLOCKED, reason)

    def abort(self, reason: str) -> bool:
        """Operator abort or MANUAL takeover: the run is discarded."""
        if self.state not in (READY, *ACTIVE):
            self.reason = f"abort ignored in {NAMES[self.state]}"
            return False
        self.run_id, self.step_index, self.resume_prepared = "", -1, False
        return self._set(IDLE, reason)

    def fault(self, reason: str) -> bool:
        if self.state == FAULT:
            return False
        self.resume_prepared = False
        return self._set(FAULT, reason)

    def ack(self) -> bool:
        """Acknowledgement only clears the latch; a new load + Start is required."""
        if self.state != FAULT:
            self.reason = f"nothing to acknowledge ({NAMES[self.state]})"
            return False
        self.run_id, self.step_index = "", -1
        return self._set(IDLE, "fault acknowledged; load a mission")

    # ---- progress -----------------------------------------------------------------------

    def step_done(self) -> bool:
        if self.state != EXECUTING:
            return False
        self.step_index += 1
        if self.step_index >= self.n_steps:
            return self._set(DONE, f"run {self.run_id} complete")
        self.reason = f"step {self.step_index} of {self.n_steps}"
        return True

    def accepts(self, run_id: str) -> bool:
        """Callbacks from an old run are ignored (spec §7.2)."""
        return bool(run_id) and run_id == self.run_id and self.state in ACTIVE
