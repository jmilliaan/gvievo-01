"""Commissioning job state machine (unified plan §7.2). Pure, clock-fed.

Wraps the repo's blind-run library (core/blindrun.py: plan + BlindRun, the
straight/arc/pivot/pulses semantics, bounds, settling, per-segment records)
in the ROS-side authority rules:

    IDLE  --plan()-->  PREPARED  --Start edge under MANUAL, lease COMMISSIONING,
                                   fresh counts, still-->  RUNNING/SETTLING
          --clear()-->  IDLE          --library done-->  DONE
                                       --any loss-->     ABORTED

  * A plan upload moves nothing. Only a FRESH physical Start edge (this tick,
    from a valid MANUAL panel) starts a job, and it starts exactly one: the
    edge is consumed, a held button does not restart, and DONE/ABORTED need a
    new plan before another Start can do anything.
  * Every tick of a running job re-checks the authority it started with:
    panel valid + MANUAL, supervisor lease with the COMMISSIONING class,
    fresh raw counts. Loss of any -> ABORTED with the reason, output zero.
  * Output is per-wheel motor rpm in driver terms from the library, converted
    here to VEHICLE-terms wheel rad/s (undoing the invert flags the drive
    owner will apply again).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from amr_base.agv_repo import config

import blindrun  # repo module: core/blindrun.py

IDLE, PREPARED, RUNNING, SETTLING, DONE, ABORTED = range(6)
PHASE_NAMES = {
    IDLE: "IDLE",
    PREPARED: "PREPARED",
    RUNNING: "RUNNING",
    SETTLING: "SETTLING",
    DONE: "DONE",
    ABORTED: "ABORTED",
}
LEASE_COMMISSIONING = 4
WHEEL_RAD_S_PER_MOTOR_RPM = 2.0 * math.pi / 60.0 / config.GEAR_RATIO


@dataclass
class Inputs:
    """What the node sees this tick."""

    now: float
    dt: float
    counts: tuple[int, int] | None  # raw driver-terms 6064h, None if invalid/stale
    counts_per_rev: float
    stopped: bool | None  # both wheels at rest per the owner (None: unknown)
    panel_valid: bool
    panel_manual: bool
    start_edge: bool
    lease_allowed: int  # ControlLease.allowed bits, 0 if stale/none
    gyro_yaw_rad_s: float | None = None  # corrected yaw rate, for evidence


@dataclass
class Job:
    plan_id: str = ""
    planned: dict | None = None
    run: blindrun.BlindRun | None = None
    phase: int = IDLE
    reason: str = ""
    gyro_heading: float = 0.0
    results: list = field(default_factory=list)
    started_counts: tuple[int, int] | None = None

    # -- operator actions (never move anything) --

    def plan(self, plan_json: str, counts_per_rev: float) -> str:
        if self.phase in (RUNNING, SETTLING):
            raise ValueError("a job is running; abort it first")
        try:
            spec = json.loads(plan_json)
            planned = blindrun.plan(spec.get("segments"), spec.get("speed"), counts_per_rev)
        except (ValueError, TypeError, AttributeError) as e:
            raise ValueError(str(e)) from None
        self.planned, self.run = planned, None
        self.plan_id = spec.get("id") or f"plan{len(planned['segments'])}"
        self.phase, self.reason, self.results, self.gyro_heading = PREPARED, "", [], 0.0
        return json.dumps(planned)

    def clear(self) -> None:
        """Drop the plan; a running job is aborted (output zero next tick)."""
        if self.run is not None and self.phase in (RUNNING, SETTLING):
            self.run.abort("cleared by operator")
            self.phase, self.reason = ABORTED, "cleared by operator"
        else:
            self.phase, self.reason = IDLE, ""
        self.planned = None
        self.run = None

    # -- the tick --

    def _authority(self, i: Inputs) -> str | None:
        if not (i.panel_valid and i.panel_manual):
            return "panel not valid MANUAL"
        if not (i.lease_allowed & LEASE_COMMISSIONING):
            return "supervisor does not allow commissioning"
        if i.counts is None:
            return "raw wheel counts stale or invalid"
        return None

    def tick(self, i: Inputs) -> tuple[float, float]:
        """-> (left, right) wheel rad/s in vehicle terms; (0, 0) unless RUNNING/SETTLING."""
        if self.phase == PREPARED:
            if not i.start_edge:
                return 0.0, 0.0
            why = self._authority(i)
            if why:
                self.reason = f"Start ignored: {why}"
                return 0.0, 0.0
            if i.stopped is False:
                self.reason = "Start ignored: wheels not at rest"
                return 0.0, 0.0
            self.run = blindrun.BlindRun(self.planned, i.counts)
            self.started_counts = tuple(i.counts)
            self.phase, self.reason = RUNNING, ""
            return 0.0, 0.0  # first motion on the next tick, from a known baseline
        if self.phase not in (RUNNING, SETTLING):
            return 0.0, 0.0
        why = self._authority(i)
        if why:
            self.run.abort(why)
            self.phase, self.reason = ABORTED, why
            self.results = list(self.run.results)
            return 0.0, 0.0
        if i.gyro_yaw_rad_s is not None:
            self.gyro_heading += i.gyro_yaw_rad_s * i.dt
        left_rpm, right_rpm = self.run.update(i.counts, i.dt, i.stopped)
        lib = self.run.phase
        if lib == blindrun.DONE:
            self.phase, self.reason = DONE, ""
        elif lib == blindrun.ABORTED:
            self.phase, self.reason = ABORTED, self.run.reason or "aborted"
        elif lib == blindrun.SETTLING:
            self.phase = SETTLING
        else:
            self.phase = RUNNING
        self.results = list(self.run.results)
        if self.phase in (DONE, ABORTED):
            return 0.0, 0.0
        sl = -1.0 if config.INVERT_LEFT else 1.0
        sr = -1.0 if config.INVERT_RIGHT else 1.0
        return sl * left_rpm * WHEEL_RAD_S_PER_MOTOR_RPM, sr * right_rpm * WHEEL_RAD_S_PER_MOTOR_RPM

    def snapshot(self) -> dict:
        d = {}
        if self.run is not None:
            d.update(self.run.snapshot())  # library detail (its own lower-case phase is overridden below)
        elif self.planned is not None:
            d.update({"segment": 0, "segments": len(self.planned["segments"]), "completed": 0})
        d.update(
            {
                "phase": PHASE_NAMES[self.phase],
                "plan_id": self.plan_id,
                "reason": self.reason,
                "gyro_heading_deg": math.degrees(self.gyro_heading),
                "results": self.results,
            }
        )
        return d

    def evidence(self, extra: dict | None = None) -> dict:
        return {
            "plan_id": self.plan_id,
            "phase": PHASE_NAMES[self.phase],
            "reason": self.reason,
            "plan": self.planned,
            "started_counts": list(self.started_counts) if self.started_counts else None,
            "results": self.results,
            "gyro_heading_deg": math.degrees(self.gyro_heading),
            "profile": config.PROFILE_NAME,
            "invert": [config.INVERT_LEFT, config.INVERT_RIGHT],
            "track_m": config.TRACK_M,
            "wheel_dia_m": config.WHEEL_DIA_M,
            **(extra or {}),
        }
