"""The MLS gyro's yaw rate, made fusable: bias removal and a plausibility check. Pure, clock-fed.

Moved here from amr_localization (unified plan WP-C5, cpu-load-plan C#11, 2026-11-16): drive_node
now does what imu_bias_node did, and amr_base importing amr_localization would be a package cycle.
amr_localization/gyro_bias.py and gyro_check.py re-export these names.

    BiasEstimator   the stationary-window bias (spec §4.3)
    GyroCheck       gyro against the wheels' yaw rate (H-P1-7, WP-E7)
    GyroFilter      the two together, as imu_bias_node chained them; drive_node feeds it
    curve_yaw_rate  LINE's curve-guard input (amr_line job `Inputs.curve_yaw_rate`, wired)

---- BiasEstimator ----

The MLS gyro has a +0.0574 deg/s bias (reconciliation D-3): 3.4 deg/min of
heading drift if fused uncorrected, and the EKF fuses yaw RATE, so it cannot
estimate the bias itself. Spec §4.3: average stationary samples, subtract,
refuse to publish until calibrated.

Stationary is decided by the caller (wheel velocities, not the gyro itself -
a gyro cannot tell a slow turn from its own bias). The estimate is refreshed
whenever the vehicle has been still for window_s, so temperature drift is
tracked between moves without any service call.

A window whose mean exceeds `max_bias` is motion the wheels did not report, not
bias, and is rejected (the previous bias stays). 2026-10-23 10:16:25: while the
drives cycled between powered and unpowered, the wheels read "still" while the
vehicle turned ~1.8 deg in 2 s, and a +0.9052 deg/s window became the bias. Applied
during a move, that is ~50 deg/min of false heading. The real bias is ~0.06 deg/s.

---- GyroCheck ----

The EKF fuses the MLS gyro's yaw RATE and nothing checks it: a frozen gyro (a stuck SDO
value, a duplicate stamp), a sign error or a wrong axis turns straight into heading error.
The wheels are an independent yaw rate. While they turn faster than `turn_rad_s` for at
least `turn_s`, the two are compared over that window:

  * opposite signs                                   -> suspect
  * |mean gyro - mean wheel| > tol_abs + tol_rel * |mean wheel|  -> suspect
    (gyro 0 against a wheel turn of 0.3 rad/s is 0.3 > 0.05 + 0.15)

A window that agrees clears it. The check never runs with the wheels still or slow: the
gyro is quantisation-limited at 0.061 deg/s, so a constant reading at rest is normal, and
the bias estimator owns that regime. A non-finite gyro reading is skipped (the bias
estimator drops it too, H-P1-5): one bad sample is not a verdict. While suspect, /imu/data
is withheld (when the withholding is on): the EKF then runs on wheel odometry, NAV readiness
sees a stale IMU, and LINE's curve guard falls back to the wheels.

The `gyro_sign` VERIFY (a witnessed CCW spin) stays open (decision 19). If the sign were
wrong this check would mark every turn suspect, which is the point: a wrong-sign yaw rate
must not be fused. That is also why the withholding is OFF by default (lead, 2026-11-16):
a wrong sign would withhold /imu/data on every turn and drop LINE localization to wheels only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DEG = 57.2958  # rad -> deg, for log texts


@dataclass
class BiasEstimator:
    window_s: float = 2.0
    settle_s: float = 0.3  # ignore the first samples after stopping (ramp-down)
    max_bias: float = math.radians(0.3)  # rad/s; ~5x the measured MLS bias
    bias: float | None = None
    rejected: int = 0  # windows refused as motion
    nonfinite: int = 0  # NaN/inf samples dropped (H-P1-5, 2026-11-16)
    last_rejected: float | None = None  # the mean of the last refused window, rad/s
    _still_since: float | None = None
    _sum: float = 0.0
    _n: int = 0
    _n_windows: int = field(default=0)

    @property
    def calibrated(self) -> bool:
        return self.bias is not None

    @property
    def windows(self) -> int:
        return self._n_windows

    def reset(self) -> None:
        self.bias = None
        self._still_since = None
        self._sum, self._n = 0.0, 0

    def update(self, t: float, gyro_z: float, stationary: bool) -> float | None:
        """Feed one raw sample. Returns the corrected rate, or None if uncalibrated.

        A NaN or inf reading is dropped whole (None, counted in `nonfinite`): it would
        poison the window's mean, and the bias with it, for good. The window and the
        stillness clock are left as they were."""
        if not math.isfinite(gyro_z):
            self.nonfinite += 1
            return None
        if not stationary:
            self._still_since = None
            self._sum, self._n = 0.0, 0
        else:
            if self._still_since is None:
                self._still_since = t
            elif t - self._still_since >= self.settle_s:
                self._sum += gyro_z
                self._n += 1
                if t - self._still_since >= self.settle_s + self.window_s and self._n > 0:
                    mean = self._sum / self._n
                    if abs(mean) > self.max_bias:
                        self.rejected += 1
                        self.last_rejected = mean
                    else:
                        self.bias = mean
                        self._n_windows += 1
                    self._still_since = t  # start the next window
                    self._sum, self._n = 0.0, 0
        if self.bias is None:
            return None
        return gyro_z - self.bias


@dataclass
class GyroCheck:
    turn_rad_s: float = 0.1  # the check runs only while |wheel yaw rate| is above this...
    turn_s: float = 1.0  # ...continuously for this long (one comparison window)
    tol_abs: float = 0.05  # rad/s
    tol_rel: float = 0.5  # of |wheel yaw rate|: slip, track-width error, timing
    suspect: bool = False
    reason: str = ""
    windows: int = 0  # comparisons made
    _since: float | None = None
    _sum_g: float = 0.0
    _sum_w: float = 0.0
    _n: int = 0

    def _restart(self, t: float | None) -> None:
        self._since, self._sum_g, self._sum_w, self._n = t, 0.0, 0.0, 0

    def update(self, t: float, gyro_z: float, wheel_wz: float | None) -> bool:
        """One gyro sample with the wheels' yaw rate at that time (None: no fresh wheel
        feedback). Returns `suspect`."""
        if not math.isfinite(gyro_z):
            return self.suspect  # dropped, as the bias estimator drops it
        if wheel_wz is None or not math.isfinite(wheel_wz) or abs(wheel_wz) <= self.turn_rad_s:
            self._restart(None)  # not turning (or blind): no evidence either way
            return self.suspect
        reversed_ = self._n and math.copysign(1.0, wheel_wz) != math.copysign(1.0, self._sum_w)
        if self._since is None or reversed_:
            self._restart(t)  # a new turn, or the turn reversed: compare like with like
        self._sum_g += gyro_z
        self._sum_w += wheel_wz
        self._n += 1
        if t - self._since < self.turn_s:
            return self.suspect
        g, w = self._sum_g / self._n, self._sum_w / self._n
        self.windows += 1
        self._restart(t)
        if g * w < 0.0:
            self.suspect, self.reason = True, f"gyro {g:+.3f} rad/s turns against the wheels {w:+.3f}"
        elif abs(g - w) > self.tol_abs + self.tol_rel * abs(w):
            self.suspect, self.reason = True, f"gyro {g:+.3f} rad/s disagrees with the wheels {w:+.3f}"
        else:
            self.suspect, self.reason = False, ""
        return self.suspect


def curve_yaw_rate(gyro_z: float | None, odom_wz: float | None) -> float | None:
    """H-P1-7's LINE curve guard input: the larger-magnitude of the two yaw rates, so a
    frozen or low-reading gyro can only take HIGH away earlier, never keep it. None when
    neither is available. Wired (2026-11-16): line_follow_node passes it to the amr_line job as
    `Inputs.curve_yaw_rate`, which the curve guard uses in place of `yaw_rate`."""
    rates = [r for r in (gyro_z, odom_wz) if r is not None and math.isfinite(r)]
    return max(rates, key=abs) if rates else None


class GyroFilter:
    """imu_bias_node's chain, for drive_node's `_publish_imu` (WP-C5): every raw sample goes
    through the plausibility check and the bias estimator; sample() returns the rate to publish
    on /imu/data, or None (not calibrated yet, a non-finite reading, or withheld while suspect).
    "Nothing until calibrated" is the estimator's own rule.

    wheels() is fed from each wheel sample: `still` (both wheels valid and below the stillness
    threshold) and the body yaw rate (None when the wheels do not vouch for it). Wheel feedback
    older than `wheel_timeout_s` is neither still nor a yaw rate. One clock for both calls.
    Log lines are queued in `logs` as (level, text) for the node to write; `drain()` empties it.
    """

    def __init__(self, window_s: float = 2.0, settle_s: float = 0.3, wheel_timeout_s: float = 0.2,
                 withhold: bool = False, max_bias: float | None = None) -> None:
        # max_bias (rad/s): the profile's imu.max_bias_deg_s; None keeps BiasEstimator's default
        self.est = BiasEstimator(window_s=window_s, settle_s=settle_s)
        if max_bias is not None:
            self.est.max_bias = float(max_bias)
        self.check = GyroCheck()
        self.withhold = bool(withhold)  # `gyro_check` param: off until the gyro_sign VERIFY
        self.wheel_timeout = wheel_timeout_s
        self.suspect = False
        self.withheld = 0  # samples not published because suspect (withholding on)
        self.logs: list[tuple[str, str]] = []
        self._wheels_t: float | None = None
        self._still = False
        self._wz: float | None = None
        self._nonfinite = self._rejected = self._windows = 0

    def wheels(self, t: float, still: bool, wz: float | None) -> None:
        self._wheels_t, self._still, self._wz = t, bool(still), wz

    def _fresh(self, t: float) -> bool:
        return self._wheels_t is not None and t - self._wheels_t < self.wheel_timeout

    def recalibrate(self) -> str:
        """/imu/recalibrate: the estimate is discarded; nothing is published until still again."""
        self.est.reset()
        self.logs.append(("info", "recalibration requested: /imu/data paused until still"))
        return f"bias discarded; keep the vehicle still for {self.est.settle_s + self.est.window_s:.1f} s"

    def sample(self, t: float, gz: float) -> float | None:
        fresh = self._fresh(t)
        suspect = self.check.update(t, gz, self._wz if fresh else None)
        if suspect != self.suspect:
            self.suspect = suspect
            if suspect:
                held = "/imu/data withheld" if self.withhold else "gyro_check off: still published"
                self.logs.append(("error", f"gyro implausible: {self.check.reason}; {held}"))
            else:
                self.logs.append(("info", "gyro agrees with the wheels again: /imu/data resumed"))
        corrected = self.est.update(t, gz, fresh and self._still)  # no wheel feedback: not still
        est = self.est
        if est.nonfinite != self._nonfinite:
            if self._nonfinite == 0 or est.nonfinite % 100 == 0:  # the first, then every 100th
                self.logs.append(("warn", f"non-finite gyro z dropped ({est.nonfinite} so far)"))
            self._nonfinite = est.nonfinite
        if est.rejected != self._rejected:
            self._rejected = est.rejected
            self.logs.append(("warn", f"gyro window {est.last_rejected * DEG:+.4f} deg/s rejected as "
                              f"motion the wheels did not report (limit {est.max_bias * DEG:.2f} deg/s); "
                              "bias kept"))
        if est.windows != self._windows:
            self._windows = est.windows
            self.logs.append(("info", f"gyro z bias {est.bias * DEG:+.4f} deg/s (window {self._windows})"))
        if corrected is None:
            return None
        if suspect and self.withhold:
            self.withheld += 1
            return None
        return corrected

    def drain(self) -> list[tuple[str, str]]:
        out, self.logs = self.logs, []
        return out
