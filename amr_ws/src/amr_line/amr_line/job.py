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
              Never auto-resumes: something above this layer took control

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
    field_clear: bool
    drives_fresh: bool


class FollowJob:
    """Arm, run, hold, stop. Owns the engine; the node owns the messages."""

    def __init__(self, follower, *, prereq_grace_s=0.5, auto_resume_clear_s=2.0,
                 auto_resume_estop=False, v_max_mps=0.30):
        self.f = follower
        self.prereq_grace_s = float(prereq_grace_s)
        self.auto_resume_clear_s = float(auto_resume_clear_s)
        self.auto_resume_estop = bool(auto_resume_estop)
        self.v_max_mps = float(v_max_mps)
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
        self.f.reset()

    def arm(self, i: Inputs):
        """Hold the vehicle ready for a Start press. Moves nothing."""
        if self.state in (RUNNING, HOLD):
            return False, "already running: clear it first"
        pre = self._prerequisite(i)
        if pre:
            return False, f"cannot arm: {pre}"
        self.f.reset()
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
        self.followed_m = 0.0
        self.f.hard_stop()
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
        if not i.field_clear:
            return "protective field is violated"
        if not i.track_ok:
            return {"rate": "tape samples too slow for control (see line_min_track_hz)",
                    "track": "no usable tape reading"}.get(i.track_cause, "tape reading unusable")
        return ""

    def _safety_cause(self, i: Inputs):
        """Which safety story a torque loss belongs to."""
        return "field" if not i.field_clear else "estop"

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
        self.f.hard_stop()

    # -- the tick ----------------------------------------------------------
    def tick(self, i: Inputs):
        """Returns (left_rpm, right_rpm). Zero unless actually following."""
        if i.reset_edge and self.state in (DONE, FAULT, HOLD):
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

        pre = self._prerequisite(i)

        # An immediate stop for anything meaning the vehicle may be moving
        # without the feedback or the torque to do it safely.
        if self.state == RUNNING:
            if i.torque_off or not i.field_clear:
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
            return 0.0, 0.0

        if self.state == HOLD:
            return self._hold_tick(i, pre)

        if self.state == RUNNING:
            if self._prereq_held(i.now, pre):
                self._hold(i.track_cause or "pending", pre)
                return 0.0, 0.0
            return self._run(i)

        return 0.0, 0.0

    def _hold_tick(self, i: Inputs, pre):
        """Wait for the cause to clear, then resume - or wait for a human."""
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

    def _run(self, i: Inputs):
        """One engine tick, with the speed cap this increment is limited to."""
        left, right, diag = self.f.update(i.sensor, i.sensor_age_s, i.dt, True)
        self.diag = diag

        from agv_core import kinematics  # noqa: PLC0415  (profile-dependent)
        v_now, _ = kinematics.wheels_to_body(left, right)
        self.followed_m += abs(v_now) * i.dt

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

        return self._cap(left, right)

    def _cap(self, left, right):
        """Hold the body speed at v_max_mps, scaling BOTH wheels together.

        Scaling one wheel changes the arc; scaling both preserves it. The mux
        applies the same ceiling independently - this increment is a bench and
        first-floor-run increment and 0.30 m/s is the agreed limit for it.
        """
        from agv_core import kinematics  # noqa: PLC0415  (profile-dependent)

        v, _omega = kinematics.wheels_to_body(left, right)
        if abs(v) > self.v_max_mps > 0:
            scale = self.v_max_mps / abs(v)
            left, right = left * scale, right * scale
        return left, right

    # -- reporting ---------------------------------------------------------
    def auto_resume(self):
        return self.state == HOLD and self.hold_cause in self._auto_causes()
