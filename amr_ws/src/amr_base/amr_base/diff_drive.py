"""Differential-drive math for the ROS layer. Pure functions, SI units.

Wheel velocities here are WHEEL rad/s, not motor r/min: this sits above the
hardware boundary. Conversion to the drives' r/min (gear ratio, inversion) is
WheelScale, applied exactly once by whoever talks to a drive (drive_node, and the
sim and commissioning that stand in for it).
"""

import math
from dataclasses import dataclass

from agv_core import se2


@dataclass(frozen=True)
class Geometry:
    wheel_radius_m: float
    track_width_m: float


def profile_geometry() -> Geometry:
    """The vehicle profile's wheel radius and track: the default every node's
    wheel_radius_m / track_width_m params start from."""
    from agv_core import config  # noqa: PLC0415 - read at call time, after the profile loads

    return Geometry(config.WHEEL_DIA_M / 2.0, config.TRACK_M)


# Motor r/min -> rad/s, before the gearhead.
RAD_S_PER_RPM = 2.0 * math.pi / 60.0


@dataclass(frozen=True)
class WheelScale:
    """Motor-side units -> wheel-side SI, per wheel. Applied exactly once."""

    gear_ratio: float
    invert_left: bool
    invert_right: bool
    counts_per_wheel_rev: float | None = None  # 608Fh/6091h at arm time; None = positions unknown

    def _sign(self, left: bool) -> float:
        return -1.0 if (self.invert_left if left else self.invert_right) else 1.0

    def motor_rpm(self, wheel_rad_s: float, left: bool) -> float:
        return wheel_rad_s / RAD_S_PER_RPM * self.gear_ratio * self._sign(left)

    def wheel_rad_s(self, motor_rpm: float, left: bool) -> float:
        return motor_rpm * RAD_S_PER_RPM / self.gear_ratio * self._sign(left)

    def wheel_rad(self, counts: int, left: bool) -> float | None:
        if not self.counts_per_wheel_rev:
            return None
        return counts / self.counts_per_wheel_rev * 2.0 * math.pi * self._sign(left)


def inverse(geom: Geometry, v_mps: float, wz_rad_s: float) -> tuple[float, float]:
    """Body (v, ω) -> (left, right) wheel rad/s. No clamping (spec §3.7)."""
    half = wz_rad_s * geom.track_width_m / 2.0
    return (v_mps - half) / geom.wheel_radius_m, (v_mps + half) / geom.wheel_radius_m


def forward(geom: Geometry, wl_rad_s: float, wr_rad_s: float) -> tuple[float, float]:
    """(left, right) wheel rad/s -> body (v, ω). Exact inverse of inverse()."""
    r = geom.wheel_radius_m
    return r * (wr_rad_s + wl_rad_s) / 2.0, r * (wr_rad_s - wl_rad_s) / geom.track_width_m


def clamp_wheels(wl: float, wr: float, w_max: float) -> tuple[float, float]:
    """Scale both wheels by the same factor so |w| <= w_max: curvature is kept."""
    peak = max(abs(wl), abs(wr))
    if peak <= w_max or peak == 0.0:
        return wl, wr
    k = w_max / peak
    return wl * k, wr * k


def slew(current: float, target: float, max_rate: float, dt: float) -> float:
    """Move current toward target by at most max_rate * dt."""
    step = max_rate * dt
    delta = target - current
    if delta > step:
        return current + step
    if delta < -step:
        return current - step
    return target


def slew_asym(current: float, target: float, accel: float, decel: float, dt: float) -> float:
    """slew() with separate rates: `accel` while |speed| grows, `decel` while it shrinks
    (toward zero or through it). A heavy vehicle may start gently and still stop fast."""
    same_sign = target == 0.0 or current == 0.0 or (target > 0) == (current > 0)
    growing = abs(target) > abs(current) and same_sign
    return slew(current, target, accel if growing else decel, dt)


def scurve(
    v: float, a: float, target: float, accel: float, decel: float, jerk: float, dt: float
) -> tuple[float, float]:
    """One tick of a jerk-limited (S-curve) speed profile: returns (v, a).

    The acceleration itself is slewed at `jerk` toward the value that, ramped back down
    at `jerk`, meets `target` exactly (sqrt(2 j |dv|)), and is bounded by `accel` while
    |speed| grows and `decel` while it shrinks (same rule as slew_asym). The speed
    therefore follows a trapezoidal acceleration profile: no step in torque demand at
    the start of a pendant press, and no overshoot past the target. Reaching the
    target zeroes the acceleration state. Manual sources on the mux use it (2026-09-18,
    0.3 m/s^2 with 1.0 m/s^3); the autonomous sources keep slew_asym.
    """
    dv = target - v
    if dv == 0.0:
        return target, 0.0
    same_sign = target == 0.0 or v == 0.0 or (target > 0) == (v > 0)
    growing = abs(target) > abs(v) and same_sign
    a_lim = accel if growing else decel
    a_des = math.copysign(min(a_lim, math.sqrt(2.0 * jerk * abs(dv))), dv)
    a = slew(a, a_des, jerk, dt)
    v_new = v + a * dt
    if (dv > 0 and v_new >= target) or (dv < 0 and v_new <= target):
        return target, 0.0
    return v_new, a


wrap_angle = se2.wrap


@dataclass
class OdomState:
    x: float = 0.0
    y: float = 0.0
    th: float = 0.0
    distance: float = 0.0  # |path length|, for covariance growth


def integrate(state: OdomState, geom: Geometry, d_left_rad: float, d_right_rad: float) -> OdomState:
    """Midpoint integration of one wheel-position increment (spec §3.6)."""
    r = geom.wheel_radius_m
    ds = r * (d_right_rad + d_left_rad) / 2.0
    dth = r * (d_right_rad - d_left_rad) / geom.track_width_m
    th_mid = state.th + dth / 2.0
    return OdomState(
        x=state.x + ds * math.cos(th_mid),
        y=state.y + ds * math.sin(th_mid),
        th=wrap_angle(state.th + dth),
        distance=state.distance + abs(ds),
    )
