"""Rolling corner: take a sharp corner without stopping, before the tape leaves the sensor.

Pure and clock-fed; job.py owns it and writes the wheels it asks for. No authority here:
the mux, the lease and the fields treat this command as any other follower command.

Why the follower cannot do it alone: its P curvature is K*e whatever the speed, so slowing
down does not tighten the arc, and at e = 100 mm it is about 1.1 1/m. Field traces of
2026-11-06: a ~50 deg corner took the tape from -4 to -87 mm in 0.3 s at 0.4 m/s, then the
kink pivot cost ~4 s (stop 0.45, spin 2.0, settle 0.3, ramp from rest 1.3).

So: predict the exit, shed speed and hold a set yaw rate toward the tape
until the tape is back inside corner_exit_mm, then hand the follower a moving vehicle. A
short stretch with the tape past the window does not stop the turn, which is already heading
for it. Bound: kink_max_deg of yaw with no tape is a FAULT, as the pivot's search. A hold
mid-turn resumes as that search, from rest (job._hold).

Trigger, replayed on the 2026-11-06 traces (33000 ticks): moving outward, |e| >= MIN_E_MM and
|e| + |rate| * corner_lead_s >= sensor_max_mm caught 13 of 13 kinks, 0.26-0.74 s ahead, with 2
false trips. A false trip is a short slowdown. Error alone cannot work: following sits at
40-80 mm for seconds on ordinary curves.
"""
import math

from agv_core import config

# Below this the prediction is only a rate spike on a centred tape.
MIN_E_MM = 30.0
# The error rate's filter, the follower's own tau_d order: long enough to ride the MLS's
# 1 mm steps, short enough to leave most of the 0.3 s a corner gives.
RATE_TAU_S = 0.05
# Real fork readings (a diverter, a crossing): the corner waits for this many single-track
# ticks, so the fork detector has the episode's end before job.pivoting masks #LCP.
FORK_NLCP = (6, 7)
AFTER_FORK_TICKS = 2


class CornerTurn:
    def __init__(self):
        self.direction = None       # "cw"/"ccw" while turning
        self.deg = 0.0              # yaw commanded this turn
        self.s = 0.0                # time in this turn
        self.result = None          # after finishing: "tape back" / "angle limit"
        self.at_mm = None           # the error that tripped it
        self._last_e = None
        self._rate = 0.0
        self._single = AFTER_FORK_TICKS

    @property
    def active(self):
        return self.direction is not None

    def cancel(self):
        """A hold, a stop, a kink pivot: drop the turn. The next watch starts clean."""
        self.direction = None
        self._last_e = None
        self._rate = 0.0

    def watch(self, e_mm, guard, nlcp, v_base_rpm, dt):
        """Not turning: one reading. Returns True when a turn begins.

        e_mm: the follower's error (None without a usable reading), guard: its "slew" mark,
        which is a reading jump and not motion, so it restarts the rate like a gap does.
        """
        self._single = 0 if nlcp in FORK_NLCP else self._single + 1
        if e_mm is None or guard == "slew" or self._last_e is None:
            self._last_e, self._rate = e_mm, 0.0
            return False
        alpha = dt / (RATE_TAU_S + dt)
        self._rate += alpha * ((e_mm - self._last_e) / dt - self._rate)
        self._last_e = e_mm
        if (config.CORNER_YAW_DEG_S <= 0
                or self._single < AFTER_FORK_TICKS
                or v_base_rpm <= config.CORNER_RPM
                or e_mm * self._rate <= 0.0
                or abs(e_mm) < MIN_E_MM
                or abs(e_mm) + abs(self._rate) * config.CORNER_LEAD_S < config.SENSOR_MAX_MM):
            return False
        self.direction = "cw" if e_mm > 0 else "ccw"        # as job._kink_begin
        self.at_mm = e_mm
        self.deg = self.s = 0.0
        self.result = None
        return True

    def turn(self, e_mm, dt, scale=1.0):
        """Turning: one reading. Returns False when the turn is over (see self.result).

        scale: the warning field's factor; the mux scales this command, so the yaw is too.
        """
        self.s += dt
        if e_mm is not None and abs(e_mm) <= config.CORNER_EXIT_MM:
            self.result = "tape back"
        elif self.deg >= config.KINK_MAX_DEG:
            self.result = "angle limit"
        else:
            self.deg += config.CORNER_YAW_DEG_S * dt * scale
            return True
        self.cancel()
        return False

    def speed_rpm(self, v_base_rpm):
        """The body speed to command: never lets the outer wheel above the follower's ramp."""
        half_diff = self.yaw_rad_s() / (2.0 * config.RAD_S_PER_RPM_DIFF)
        return max(0.0, min(config.CORNER_RPM, v_base_rpm), v_base_rpm - abs(half_diff))

    def yaw_rad_s(self):
        """Signed yaw rate, omega > 0 is CCW."""
        sign = -1.0 if self.direction == "cw" else 1.0
        return sign * math.radians(config.CORNER_YAW_DEG_S)
