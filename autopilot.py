"""Line-following controller. Pure computation - no CAN, no Flask, no file I/O.

Control law (draft_pid_design.md section 2):

    omega_cmd  = -(Kp*e + Ki*integral + Kd*d_filt)      Kp = K_RATIO * v
    v_cmd      = v_base - speed_reduction
    (N_L, N_R) = body_to_wheels(v_cmd, omega_cmd), then joint saturation

Kp scales with v deliberately. For a sensor mounted Ls ahead of the axle the
error dynamics are  e_dot = v*theta + Ls*omega, and substituting Kp = K_RATIO*v
into the closed-loop damping gives

    zeta = (Kd + Ls*K_RATIO) / (2*sqrt(K_RATIO*(1 + Ls*Kd)))

with no v in it. Damping is therefore the same at 800 r/min and at 2546, which
is what makes commissioning by working the speed up valid rather than a re-tune
at every step. KIM2A reached the same relationship empirically ("KP scales
roughly linearly with target speed").

*** The binding limit on K_RATIO is 6083h, not stability of the ideal plant. ***
The wheel difference cannot slew faster than the drivers ramp, which caps yaw
acceleration at 2*ACCEL*RAD_S_PER_RPM_DIFF = 2.59 rad/s^2 at the present 2000
(r/min)/s. An ideal-plant model says K_RATIO = 100 is optimal; with the real
slew limit that diverges at 0.8 m/s. Raising K_RATIO requires raising 6083h with
it - see the plan, and re-check traction before doing so.

Every constant this file reads comes from config (agv-profile.json). Values are
read at call time, not bound at import, so a test can retarget a gain and the
next tick picks it up.
"""
import math

import config
import kinematics


def predicted_zeta(k_ratio=None, kd=None):
    """Closed-loop damping for the current gains. Speed-independent by design."""
    k = config.K_RATIO if k_ratio is None else k_ratio
    d = config.KD if kd is None else kd
    ls = config.SENSOR_LOOKAHEAD_M
    return (d + ls * k) / (2.0 * math.sqrt(k * (1.0 + ls * d)))


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class LineFollower:
    """One instance per vehicle. Not thread-safe; call update() from one thread."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._v_rpm = 0.0            # ramp state: current base speed
        self._a_rpm_s = 0.0          # ramp state: current acceleration
        self._integral = 0.0
        self._d_filt = 0.0
        self._speed_red = 0.0
        self._omega = 0.0            # last commanded yaw, held while coasting
        # None, not 0.0: priming from the first live sample avoids the
        # derivative kick KIM2A documents in its section 9.1, where reset()
        # zeroes last_pv and the next tick differentiates the full standing
        # error over one period.
        self._last_e_m = None
        self._last_valid_mm = None
        self._track_gap_m = 0.0      # distance travelled since the track was seen
        self._track_age_s = 0.0      # standstill backstop for the same
        self._saturated = False
        self.state = "idle"

    def hard_stop(self):
        """Collapse the profile to zero with no ramp - watchdog and fault path.

        Distinct from reset(): the PID history survives, only the motion stops.
        Without this a watchdog that zeroes the setpoint would be undone on the
        very next tick, because the ramp would still be carrying speed.
        """
        self._v_rpm = 0.0
        self._a_rpm_s = 0.0
        self._speed_red = 0.0
        self._omega = 0.0
        self.state = "halted"

    # ---- pieces ----------------------------------------------------------

    def _read_error(self, sensor):
        """Sensor dict -> (error_m, n_tracks, guard) with guard = why it changed.

        Returns error_m None when there is no usable track this tick.
        """
        tracks = (sensor or {}).get("tracks") or []
        if not tracks:
            return None, 0, ""

        # Nearest valid LCP to the sensor centre. Behaves sensibly when a second
        # line enters the field of view at a junction.
        pos_mm = min(tracks, key=lambda t: abs(t.get("pos_mm", 0)))["pos_mm"]
        pos_mm = float(pos_mm)
        guard = ""

        if abs(pos_mm) > config.SENSOR_MAX_MM:
            return None, len(tracks), "discard"      # implausible - drop it

        if self._last_valid_mm is not None:
            step = pos_mm - self._last_valid_mm
            if abs(step) > config.SENSOR_MAX_STEP_MM:
                pos_mm = self._last_valid_mm + math.copysign(
                    config.SENSOR_MAX_STEP_MM, step)
                guard = "slew"

        self._last_valid_mm = pos_mm
        e_mm = -pos_mm if config.INVERT_ERROR else pos_mm
        return e_mm / 1000.0, len(tracks), guard

    def _pid(self, e_m, v_mps, dt):
        kp = config.K_RATIO * v_mps
        p = kp * e_m

        # Conditional integration: only inside the deadband, and never while the
        # wheels are saturated (the extra command would go nowhere but the
        # integrator).
        if abs(e_m) * 1000.0 < config.TI_DEADBAND_MM and not self._saturated:
            self._integral += e_m * dt
        i = _clamp(config.KI * self._integral, -config.I_CLAMP, config.I_CLAMP)

        # Derivative on measurement. Primed on the first tick after a reset so
        # the standing error is not differentiated against a fake zero.
        if self._last_e_m is None:
            d_raw = 0.0
        else:
            d_raw = (e_m - self._last_e_m) / dt
        tau_d = config.TAU_D_S
        alpha = dt / (tau_d + dt) if tau_d > 0 else 1.0
        self._d_filt += alpha * (d_raw - self._d_filt)
        self._last_e_m = e_m
        d = config.KD * self._d_filt

        return -(p + i + d), p, i, d

    def _ramp(self, target_rpm, dt):
        """Jerk-limited approach to target_rpm. This is the whole S-curve."""
        err = target_rpm - self._v_rpm
        a_want = _clamp(err / dt, -config.RAMP_ACCEL_RPM_S,
                        config.RAMP_ACCEL_RPM_S)
        step = config.RAMP_JERK_RPM_S2 * dt
        self._a_rpm_s += _clamp(a_want - self._a_rpm_s, -step, step)
        self._v_rpm += self._a_rpm_s * dt
        # The jerk limit makes the acceleration lag, which would otherwise let
        # the ramp sail past its target.
        if (err > 0 and self._v_rpm > target_rpm) or \
           (err < 0 and self._v_rpm < target_rpm):
            self._v_rpm = target_rpm
            self._a_rpm_s = 0.0
        return self._v_rpm

    def _reduce_speed(self, e_m, dt):
        """Shed speed on error magnitude and rate, as a FRACTION of base speed.

        The coefficients are fractions rather than absolute r/min so authority
        tracks speed automatically - as absolutes they silently fell from 15% to
        6% of base when cruise went 800 -> 2000. Scaling by self._v_rpm rather
        than AUTO_RPM means it also tracks the ramp, and matches the SR_CAP
        ceiling below, which is already a fraction of the same quantity.
        """
        rate_mm_s = abs(self._d_filt) * 1000.0
        raw = (abs(e_m) * 1000.0 * config.SR_POS_FRAC
               + rate_mm_s * config.SR_RATE_FRAC) * self._v_rpm
        raw = min(raw, self._v_rpm * config.SR_CAP)   # cap BEFORE the filter
        tau = config.SR_TAU_S
        alpha = dt / (tau + dt) if tau > 0 else 1.0
        self._speed_red += alpha * (raw - self._speed_red)
        return self._speed_red

    def _to_wheels(self, v_rpm, omega):
        """Wheel commands with the differential floored and the pair scaled.

        Works in vehicle terms throughout, then converts once through
        kinematics.body_to_wheels() so the INVERT_LEFT/RIGHT rule stays in
        exactly one place.
        """
        base = v_rpm
        diff = omega / config.RAD_S_PER_RPM_DIFF

        # Floor the inner wheel by limiting the DIFFERENTIAL, not by clipping one
        # wheel - clipping one alters the effective turn ratio (draft 4.2).
        head = base - config.INNER_WHEEL_MIN_RPM
        if head <= 0:
            diff = 0.0
        elif abs(diff) > 2.0 * head:
            diff = math.copysign(2.0 * head, diff)

        left, right = base - diff / 2.0, base + diff / 2.0

        # Ceiling: scale BOTH by the same factor so the arc is preserved.
        peak = max(abs(left), abs(right))
        scale = 1.0
        if peak > config.MOTOR_MAX_RPM:
            scale = config.MOTOR_MAX_RPM / peak
            left *= scale
            right *= scale
        self._saturated = scale < 1.0

        v_mps = (left + right) / 2.0 * config.MPS_PER_RPM
        omega_out = (right - left) * config.RAD_S_PER_RPM_DIFF
        left_out, right_out = kinematics.body_to_wheels(v_mps, omega_out)
        return left_out, right_out, scale

    # ---- the tick --------------------------------------------------------

    def update(self, sensor, sensor_age_s, dt, running):
        """One control tick.

        sensor       : canworker._sensor_json() dict, or None if none seen yet
        sensor_age_s : seconds since the last TPDO1 frame, None if never
        dt           : measured seconds since the previous update()
        running      : False ramps down but keeps steering while it decelerates

        Returns (left_rpm, right_rpm, diag).
        """
        dt = _clamp(dt if dt and dt > 0 else config.DT_NOMINAL_S,
                    config.DT_MIN_S, config.DT_MAX_S)

        stale = sensor_age_s is None or sensor_age_s > config.SENSOR_TIMEOUT_S
        e_m, n_tracks, guard = (None, 0, "stale") if stale else \
            self._read_error(sensor)

        p = i = d = 0.0
        if stale:
            # Comms failure, not a tape gap. We no longer know where the line
            # is, so hold straight and stop - the least-bad blind action.
            self.state = "sensor_lost"
            self._omega = 0.0
            target = 0.0
        elif e_m is None:
            # Budget the gap in DISTANCE, not time: how far the AGV travels on a
            # stale correction is the thing that matters, and it rescales itself
            # with speed instead of having to be re-tuned at every step. The time
            # ceiling is the standstill case - stopped, no distance accrues and
            # the budget would never deplete.
            self._track_gap_m += kinematics.rpm_to_mps(self._v_rpm) * dt
            self._track_age_s += dt
            within = (self._track_gap_m <= config.LINE_LOSS_GRACE_M
                      and self._track_age_s <= config.LINE_LOSS_GRACE_MAX_S)
            if within and running:
                self.state = "coast"      # bridge a gap on the last correction
                target = config.AUTO_RPM
            else:
                self.state = "line_lost"
                self._omega = 0.0
                target = 0.0
        else:
            self._track_gap_m = 0.0
            self._track_age_s = 0.0
            self.state = "run" if running else "stopping"
            target = config.AUTO_RPM if running else 0.0
            # Steering stays live while stopping so it tracks as it slows.
            v_now = kinematics.rpm_to_mps(max(self._v_rpm, 1.0))
            self._omega, p, i, d = self._pid(e_m, v_now, dt)

        v_base = self._ramp(target, dt)
        red = self._reduce_speed(e_m if e_m is not None else 0.0, dt)
        left, right, scale = self._to_wheels(max(v_base - red, 0.0), self._omega)

        return left, right, {
            "dt": dt,
            "state": self.state,
            "e_mm": None if e_m is None else e_m * 1000.0,
            "e_used": self._last_valid_mm,
            "p": p, "i": i, "d": d,
            "omega_cmd": self._omega,
            "speed_red": red,
            "v_base": v_base,
            "n_l": left, "n_r": right,
            "sat_scale": scale,
            "has_track": e_m is not None,
            "n_tracks": n_tracks,
            "guard": guard,
        }
