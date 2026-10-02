"""Line-follow authority and state machine. No ROS, no clock, no I/O.

The same split `amr_base/commissioning.py` uses, and for the same reason: the
decisions here are the ones worth testing, and a test that needs a ROS graph
does not get run. The node marshals messages, stamps freshness and owns the
clock; this file decides whether the vehicle may move and hands back a wheel
command. Everything it knows arrives in a frozen `Inputs`.

STATE VALUES ARE ON THE WIRE. They are LineState.msg's constants, and
readiness.py holds `_line_active_locked` as `line_state in (1, 2, 3)` - ARMED,
RUNNING, HOLD. mode_fsm refuses to leave LINE while that is true. Renumbering
these silently breaks the guard that stops a layer swap under a moving
vehicle, so the constants are asserted against the message in the node.

WHAT HOLDS THE VEHICLE, and how each resumes:

  field       protective field violated (/output_paths): resumes by itself
  estop       drive torque gone with the field clear: needs a physical Start,
              unless auto_resume_estop
  drives      wheel feedback or drive report went stale while running: stops
              at once, resumes by itself once feedback is back
  track       no usable tape reading: the ENGINE owns the grace distance, so
              this hold is only for a reading that never arrives at all
  rate        samples are fresh but too slow, or the MLS fell back to SDO.
              sensor_timeout_s cannot see this - see track.TrackReader
  authority   lease, generation or panel selector changed under the run.
              Never auto-resumes: something above this layer took control.
              An explicit act - the selector leaving AUTO on a valid panel,
              LEASE_LINE withdrawn from a fresh lease, the lease replaced -
              ends the run at once (FAULT, Reset to clear), as the executor's
              manual takeover does. A MISSING signal (stale panel, stale
              lease) is a comms question and goes through the debounce

The asymmetry between debounced and immediate is deliberate and copied from
the executor: a prerequisite must fail CONTINUOUSLY for prereq_grace_s before
it faults, so one dropped frame never latches, but anything that means the
vehicle is moving without proper feedback stops on the first tick. Delaying a
stop is the wrong direction.
"""
import dataclasses

# LineState.msg, and not free to change - see the module docstring.
IDLE, ARMED, RUNNING, HOLD, DONE, FAULT = 0, 1, 2, 3, 4, 5

STATE_NAMES = {
    IDLE: "IDLE", ARMED: "ARMED", RUNNING: "RUNNING",
    HOLD: "HOLD", DONE: "DONE", FAULT: "FAULT",
}

# Holds that clear themselves once the cause does. "estop" joins this set only
# when auto_resume_estop is set, matching the executor's operator decision of
# 2026-09-19 that an E-stop recovery is a deliberate human act.
_AUTO_CAUSES = ("field", "drives", "rate", "track")


@dataclasses.dataclass(frozen=True)
class Inputs:
    """One tick's worth of the world. Booleans are already ANDed with
    freshness by the node, so nothing here has to know what time it is."""

    now: float
    dt: float

    # sensor
    sensor: dict                     # the engine's track dict
    sensor_age_s: float              # decode-to-now, not publish-to-now
    track_ok: bool                   # usable: fresh, fast enough, tpdo
    track_cause: str                 # "" when track_ok

    # authority
    panel_valid: bool
    panel_auto: bool                 # LINE lives on the AUTO side of gating
    start_edge: bool
    start_edge_t: float | None
    reset_edge: bool
    lease_allowed: int               # ControlLease.allowed bitmask
    lease_line: int                  # ControlLease.LINE bit
    authority: tuple[str, int] | None  # (instance, generation)

    # safety chain
    torque_off: bool
    field_clear: bool | None       # None = no fresh /output_paths: UNKNOWN, not clear
    drives_fresh: bool

    # mission engine (2026-10-02). Defaults keep plain line following, and every
    # caller that predates the engine, unchanged.
    rfid: dict | None = None         # agv_core.drivers.rfid snapshot(encounters=True)
    counts: tuple | None = None      # (left, right) 6064h from /wheel_states, driver terms
    counts_per_rev: float = 0.0      # /wheel_states counts_per_wheel_rev; 0 = unknown
    wheels_still: bool = False       # both wheels below the stillness threshold, fresh


class FollowJob:
    """Arm, run, hold, stop. Owns the engine; the node owns the messages."""

    def __init__(self, follower, *, prereq_grace_s=0.5, auto_resume_clear_s=2.0,
                 auto_resume_estop=False, auto_start_delay_s=0.6):
        self.f = follower
        self.prereq_grace_s = float(prereq_grace_s)
        self.auto_resume_clear_s = float(auto_resume_clear_s)
        self.auto_resume_estop = bool(auto_resume_estop)
        self.auto_start_delay_s = max(0.0, float(auto_start_delay_s))
        # The mission the next run uses (agv_core.mission.load output), or None for
        # plain line following. Set only while IDLE - see set_mission().
        self.mission = None
        self.tape = None
        self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self):
        self.state = IDLE
        self.hold_cause = ""
        self.reason = ""
        self.accepted_t = None      # when arm() was accepted
        self._binding = None        # (instance, generation) the run belongs to
        self._prereq_since = None
        self._auto_since = None
        self._resume_pending = False
        # The engine has no run odometer - _track_gap_m is distance since the
        # tape was last seen, which is a different question. Integrated here.
        self.followed_m = 0.0
        self._resume_at = None
        self.diag = {}
        self.tape = self._new_tape()
        self.f.reset()

    def _new_tape(self):
        """A fresh mission state for one run: stage, latches and cursor start over."""
        from amr_line.tape_run import TapeRun  # noqa: PLC0415  (profile-dependent)

        return TapeRun(self.mission)

    def set_mission(self, mission):
        """Choose the mission for the next run. Refused unless IDLE: a run's route
        stage and latches belong to the mission it started with."""
        if self.state != IDLE:
            return False, f"cannot change the mission while {STATE_NAMES[self.state]}: clear first"
        self.mission = mission
        self.tape = self._new_tape()
        name = mission["MISSION_NAME"] if mission else "none"
        return True, f"mission {name}" + ("" if mission else " (plain line following)")

    def arm(self, i: Inputs):
        """Hold the vehicle ready for a Start press. Moves nothing."""
        if self.state in (RUNNING, HOLD):
            return False, "already running: clear it first"
        pre = self._prerequisite(i)
        if pre:
            return False, f"cannot arm: {pre}"
        self.f.reset()
        self.tape = self._new_tape()
        self.state = ARMED
        self.accepted_t = i.now
        self._binding = i.authority
        self.hold_cause = ""
        self.reason = "armed: press physical Start under AUTO to run"
        return True, self.reason

    def clear(self):
        """Disarm. The node zeroes the command immediately on this."""
        moving = self.state in (RUNNING, HOLD)
        self.state = IDLE
        self.hold_cause = ""
        self.accepted_t = None
        self._binding = None
        self._prereq_since = self._auto_since = None
        self._resume_pending = False
        self._resume_at = None
        self.followed_m = 0.0
        self.f.hard_stop()
        self.tape = self._new_tape()
        self.reason = "cleared"
        return moving

    # -- the checks --------------------------------------------------------
    def _prerequisite(self, i: Inputs):
        """Why the vehicle may not move right now, or "" if it may."""
        if not i.panel_valid:
            return "panel state is stale"
        if not i.panel_auto:
            return "selector is not in AUTO"
        if i.authority is None:
            return "no fresh control lease"
        if not (i.lease_allowed & i.lease_line):
            return "LEASE_LINE not granted by the supervisor"
        if not i.drives_fresh:
            return "no fresh drive report"
        if i.torque_off:
            return "drive torque is off"
        if i.field_clear is None:
            return "protective field state unknown (no fresh /output_paths)"
        if not i.field_clear:
            return "protective field is violated"
        if not i.track_ok:
            return {"rate": "tape samples too slow for control (see line_min_track_hz)",
                    "track": "no usable tape reading"}.get(i.track_cause, "tape reading unusable")
        return ""

    def _safety_cause(self, i: Inputs):
        """Which safety story a torque loss belongs to. Unknown field evidence
        cannot prove a stop was only the field, so it is an E-stop: the hold
        that waits for a human."""
        return "field" if i.field_clear is False else "estop"

    def _taken_over(self, i: Inputs):
        """An explicit withdrawal of authority, or "". Not debounced: a
        selector flick to MANUAL and back inside the grace window must not
        leave the run entitled to resume the moment the mux re-opens."""
        if i.panel_valid and not i.panel_auto:
            return "manual takeover: selector left AUTO"
        if i.authority is not None and not (i.lease_allowed & i.lease_line):
            return "LEASE_LINE withdrawn by the supervisor"
        return ""

    def _auto_causes(self):
        return _AUTO_CAUSES + (("estop",) if self.auto_resume_estop else ())

    def _prereq_held(self, now, pre):
        """True once a prerequisite has failed CONTINUOUSLY for the grace.

        Any passing tick clears the timer, so one dropped frame never latches.
        What is debounced is "something is wrong", not one message: the reason
        may change while the timer runs.
        """
        if not pre:
            self._prereq_since = None
            return False
        if self._prereq_since is None:
            self._prereq_since = now
        return now - self._prereq_since >= self.prereq_grace_s

    def _hold(self, cause, why):
        self.state = HOLD
        self.hold_cause = cause
        self.reason = {
            "field": f"safety stop (protective field): {why}",
            "estop": f"safety stop (E-stop / safety chain): {why}",
            "authority": f"authority lost: {why}",
        }.get(cause, why)
        self._auto_since = None
        self._resume_at = None
        self.f.hard_stop()
        # A pivot cannot be resumed part-way (gy-demo rule): its start counts and
        # tape history describe a vehicle that has since been stopped by hand.
        if cause != "station" and self.tape is not None and self.tape.uturn_req is not None:
            self.tape.abort_u_turn()
            self.state = FAULT
            self.reason = f"U-turn interrupted ({why}); align the AGV on the tape and re-arm"

    # -- the tick ----------------------------------------------------------
    def tick(self, i: Inputs):
        """Returns (left_rpm, right_rpm). Zero unless actually following."""
        # Reset ends a run too: on the jacked-up vehicle (2026-09-21) Reset
        # did nothing while RUNNING and the wheels kept turning until the
        # follower was cleared by service. The node zeroes the command on
        # the falling edge out of RUNNING.
        # ARMED too: an armed layer that Reset cannot cancel would run on
        # the next Start with nobody having asked for it. Reset wins over a
        # Start seen in the same tick.
        if i.reset_edge and self.state != IDLE:
            self.reset()
            self.reason = "reset"
            return 0.0, 0.0

        if self.state in (IDLE, DONE, FAULT):
            return 0.0, 0.0

        # Authority is re-checked every tick and never debounced: if the lease
        # or the generation moved, something above this layer took control and
        # this run is not entitled to the wheels any more.
        if self._binding is not None and i.authority != self._binding:
            self._hold("authority", "the control lease was replaced")
            self.state = FAULT
            return 0.0, 0.0
        taken = self._taken_over(i)
        if taken:
            self._hold("authority", taken)
            self.state = FAULT
            return 0.0, 0.0

        pre = self._prerequisite(i)

        # An immediate stop for anything meaning the vehicle may be moving
        # without the feedback or the torque to do it safely.
        if self.state == RUNNING:
            if i.torque_off or i.field_clear is False:
                self._hold(self._safety_cause(i), "drive torque removed")
                return 0.0, 0.0
            if not i.drives_fresh:
                self._hold("drives", "wheel feedback stopped while running")
                return 0.0, 0.0

        if self.state == ARMED:
            if pre:
                self.reason = f"not ready: {pre}"
                if self._prereq_held(i.now, pre):
                    self.state = FAULT
                    self.reason = f"faulted while armed: {pre}"
                return 0.0, 0.0
            self._prereq_since = None
            # A press made BEFORE the arm was accepted must not run the
            # vehicle - the same hazard commissioning guards against.
            if i.start_edge:
                if i.start_edge_t is None or self.accepted_t is None \
                        or i.start_edge_t <= self.accepted_t:
                    self.reason = "Start ignored: pressed before the layer was armed"
                    return 0.0, 0.0
                self.state = RUNNING
                self.reason = "running"
                self.tape.depart(i.now, i.rfid)
                if self.tape.fault:
                    return self._tape_fault()
            else:
                self.tape.sync(i.rfid)
            return 0.0, 0.0

        if self.state == HOLD:
            # Tags read while held are still delivered exactly once - a branch or
            # slow-zone exit passed during a hold must still clear its latch - but
            # they cannot advance the route (TapeRun.scan, driving=False).
            tags = self.tape.scan(i.now, i.rfid, False, self.f)
            if self.tape.fault:
                return self._tape_fault()
            self.tape.steer(i.sensor, tags, self.f.followed_mm)
            return self._hold_tick(i, pre)

        if self.state == RUNNING:
            if self._prereq_held(i.now, pre):
                self._hold(i.track_cause or "pending", pre)
                return 0.0, 0.0
            return self._run(i)

        return 0.0, 0.0

    def _hold_tick(self, i: Inputs, pre):
        """Wait for the cause to clear, then resume - or wait for a human."""
        # A torque loss arriving DURING a hold for some other reason takes the
        # safety cause (executor rule): a hold for stale feedback must not
        # auto-resume through an E-stop that happened while it waited. A hold
        # already on the field's or the E-stop's terms keeps them.
        if self.hold_cause not in ("field", "estop") and (i.torque_off or i.field_clear is False):
            self._hold(self._safety_cause(i), "drive torque removed while held")
            return 0.0, 0.0

        if self.hold_cause == "station":
            return self._station_tick(i, pre)

        if self.hold_cause not in self._auto_causes():
            # estop (by default) and authority: a physical Start, not a timer.
            if i.start_edge and not pre:
                self.state = RUNNING
                self.hold_cause = ""
                self.reason = "resumed on Start"
            else:
                self.reason = f"held ({self.hold_cause}): press Start when clear"
            return 0.0, 0.0

        if pre:
            self._auto_since = None
            self.reason = f"held ({self.hold_cause}): {pre}"
            return 0.0, 0.0
        if self._auto_since is None:
            self._auto_since = i.now
        if i.now - self._auto_since >= self.auto_resume_clear_s:
            self.state = RUNNING
            self.hold_cause = ""
            self._auto_since = None
            self.reason = "resumed: the cause cleared and stayed clear"
        else:
            self.reason = f"held ({self.hold_cause}): clear, resuming shortly"
        return 0.0, 0.0

    def _station_tick(self, i: Inputs, pre):
        """Parked at a station: Start, then auto_start_delay_s, then go on.

        The delay is the same one every start takes, because a station is exactly
        where somebody is likely to be standing. A prerequisite failing during the
        delay cancels it rather than starting into it.
        """
        where = (self.tape.stop or {}).get("where", "station")
        if self._resume_at is None:
            if i.start_edge and not pre:
                self._resume_at = i.now + self.auto_start_delay_s
                self.reason = f"{where}: Start pressed, moving in {self.auto_start_delay_s:.1f} s"
            else:
                self.reason = f"at {where}: press Start to go on" + (f" ({pre})" if pre else "")
            return 0.0, 0.0
        if pre:
            self._resume_at = None
            self.reason = f"{where}: start cancelled ({pre})"
            return 0.0, 0.0
        if i.now < self._resume_at:
            return 0.0, 0.0
        self._resume_at = None
        tag = (self.tape.stop or {}).get("tag")
        self.tape.depart(i.now, i.rfid, resumed_tag=tag)
        if self.tape.fault:
            return self._tape_fault()
        self.state = RUNNING
        self.hold_cause = ""
        self.reason = f"departed {where}"
        return 0.0, 0.0

    def _tape_fault(self):
        self.state = FAULT
        self.hold_cause = ""
        self.reason = self.tape.fault
        self.f.hard_stop()
        return 0.0, 0.0

    def _uturn_fault(self, why):
        self.tape.abort_u_turn()
        self.state = FAULT
        self.hold_cause = ""
        self.reason = f"U-turn: {why}; align the AGV on the tape and re-arm"
        self.f.hard_stop()
        return 0.0, 0.0

    def _uturn_tick(self, i: Inputs, tags):
        """Stop over the tag, pivot by encoder, centre on the tape, settle."""
        from agv_core import config as vehicle  # noqa: PLC0415

        from amr_line import uturn  # noqa: PLC0415
        from amr_line.tape_run import u_turn_error  # noqa: PLC0415

        t = self.tape
        if i.sensor_age_s is None or i.sensor_age_s > vehicle.SENSOR_TIMEOUT_S:
            return self._uturn_fault("sensor silent during the U-turn")
        if t.uturn is None:
            # Stopping over the tag: the follower steers all the way down.
            choice, slow = t.steer(i.sensor, tags, self.f.followed_mm)
            left, right, diag = self.f.update(i.sensor, i.sensor_age_s, i.dt, False, choice, slow)
            self.diag = diag
            if diag["state"] == "line_lost":
                return self._uturn_fault("line lost while stopping for the U-turn")
            if diag["v_base"] == 0 and i.wheels_still:
                why = t.begin_spin(i.sensor, i.counts, i.counts_per_rev)
                if why:
                    return self._uturn_fault(why)
            return left, right
        if i.counts is None:
            return self._uturn_fault("encoder counts unavailable")
        e_mm, level = u_turn_error(i.sensor)
        left, right = t.uturn.update(i.counts, e_mm, level, i.dt)
        if t.uturn.phase == uturn.FAILED:
            return self._uturn_fault(t.uturn.reason)
        if t.uturn.phase == uturn.DONE:
            t.finish_u_turn()
            # The PID history describes the tape as it was before the pivot.
            self.f.reset()
            return 0.0, 0.0
        return left, right

    def _run(self, i: Inputs):
        """One engine tick: mission tags, branch order, speed zone, stops, U-turn."""
        t = self.tape
        tags = t.scan(i.now, i.rfid, True, self.f)
        if t.fault:
            return self._tape_fault()
        if t.uturn_req is not None:
            return self._uturn_tick(i, tags)
        choice, slow = t.steer(i.sensor, tags, self.f.followed_mm)
        stopping = t.stop is not None
        left, right, diag = self.f.update(i.sensor, i.sensor_age_s, i.dt, not stopping, choice, slow)
        self.diag = diag

        from agv_core import kinematics  # noqa: PLC0415  (profile-dependent)
        v_now, _ = kinematics.wheels_to_body(left, right)
        self.followed_m += abs(v_now) * i.dt
        t.advance(abs(v_now) * i.dt)
        if t.fault:
            return self._tape_fault()

        # A measured station stop that has come to rest: park, wait for Start.
        if stopping and diag["v_base"] == 0:
            self._hold("station", f"at {t.stop['where']}: press Start to go on")
            return 0.0, 0.0

        # The engine stops itself when the tape has been gone for
        # LINE_LOSS_GRACE_M of travel. That is a completed run, not a fault:
        # the vehicle reached the end of the tape, or the tape ended.
        if diag["state"] in ("line_lost", "sensor_lost"):
            self.state = DONE
            self.hold_cause = ""
            self.reason = ("track lost: the tape has been out of view for the "
                           "whole line-loss distance budget")
            self.f.hard_stop()
            return 0.0, 0.0

        return left, right

    # -- reporting ---------------------------------------------------------
    def mission_snapshot(self):
        """What the mission engine is doing, for LineState and the web."""
        t = self.tape
        r = t.route.snapshot()
        u = t.uturn_snapshot() or {}
        return {
            "mission": t.name if self.mission else "",
            "station": r.get("station") or "",
            "next_station": r.get("next_station") or "",
            "branch_intent": t.branch.ladder.intent(),
            "slow_zone": bool(t.branch.slow),
            "uturn_phase": (u.get("phase") or "") if u.get("active") else "",
            "last_tag": (t.last_encounter or {}).get("tag") or "",
            "last_tag_action": (t.last_encounter or {}).get("action") or "",
            "stop_where": (t.stop or {}).get("where", ""),
        }

    def auto_resume(self):
        return self.state == HOLD and self.hold_cause in self._auto_causes()
