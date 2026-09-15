"""Differential-drive math for the ROS layer. Pure functions, SI units.

Wheel velocities here are WHEEL rad/s, not motor r/min: this sits above the
hardware boundary. Conversion to the drives' r/min (gear ratio, inversion) is
the drive node's job (spec §0.2), using core/kinematics.py.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Geometry:
    wheel_radius_m: float
    track_width_m: float


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


def wrap_angle(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


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
