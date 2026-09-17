"""Route -> expected poses, sampled paths and signed turns (spec §5.2, §5.3, §6.4).

A straight starts at the preceding endpoint and must lie forward along the
current heading; a rotate keeps position and advances heading by its signed
FULL angle (cw 270 stays -3pi/2). Anything else raises RouteError with the
step id: the compiler never rounds a bend into a turn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from amr_navigation.route import (
    ALLOWED_ANGLES_DEG,
    DIRECTIONS,
    ROTATE,
    STRAIGHT,
    Route,
    RouteError,
)

COLLINEAR_TOL_M = 0.001  # lateral offset of `to` from the heading line
MIN_LENGTH_M = 0.05
SAMPLE_SPACING_M = 0.05
MAX_SAMPLES = 200_000  # 10 km at 0.05 m: bounds the work a malformed route can cause


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass
class CompiledStep:
    id: str
    type: str
    start: tuple[float, float, float]  # x, y, yaw (rad) before the step
    end: tuple[float, float, float]  # after the step
    length_m: float = 0.0  # straight
    samples: list[tuple[float, float, float]] = field(default_factory=list)  # straight, every 0.05 m
    signed_angle_rad: float = 0.0  # rotate, full magnitude, +ccw
    time_allowance_s: float = 0.0  # rotate
    duration_est_s: float = 0.0


@dataclass
class CompiledRoute:
    steps: list[CompiledStep]
    total_length_m: float
    total_turn_rad: float
    end: tuple[float, float, float]
    closes: bool  # end pose within tolerance of the start (needed for repeat_count > 1)


def compile_route(route: Route, spacing: float = SAMPLE_SPACING_M) -> CompiledRoute:
    lim = route.limits
    for name in ("linear_mps", "angular_rad_s", "position_tolerance_m", "heading_tolerance_deg"):
        v = getattr(lim, name)
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0.0):
            raise RouteError(f"limits.{name} must be a finite positive number, got {v!r}")
    x, y, yaw = route.start.x_m, route.start.y_m, route.start.yaw_rad
    if not all(math.isfinite(v) for v in (x, y, yaw)):
        raise RouteError("start pose must be finite")
    n_samples = 0
    steps: list[CompiledStep] = []
    total_len, total_turn = 0.0, 0.0
    seen: set[str] = set()
    for i, s in enumerate(route.steps):
        sid = s.id or f"s{i + 1}"
        if sid in seen:
            raise RouteError(f"duplicate step id {sid!r}", sid)
        seen.add(sid)
        if s.type == STRAIGHT:
            if s.to is None:
                raise RouteError("straight needs 'to'", sid)
            if not (math.isfinite(s.to[0]) and math.isfinite(s.to[1])):
                raise RouteError("'to' must be finite", sid)
            dx, dy = s.to[0] - x, s.to[1] - y
            c, sn = math.cos(yaw), math.sin(yaw)
            along = dx * c + dy * sn
            lateral = -dx * sn + dy * c
            if abs(lateral) > COLLINEAR_TOL_M:
                raise RouteError(
                    f"'to' is {lateral:+.3f} m off the current heading line: "
                    "insert a turn, bends are not allowed",
                    sid,
                )
            if along < MIN_LENGTH_M:
                raise RouteError(
                    f"straight must go forward at least {MIN_LENGTH_M} m along the heading "
                    f"(got {along:+.3f} m)",
                    sid,
                )
            n = max(1, int(math.ceil(along / spacing)))
            n_samples += n + 1
            if n_samples > MAX_SAMPLES:
                raise RouteError(f"route too long: more than {MAX_SAMPLES} path samples", sid)
            samples = [(x + c * along * k / n, y + sn * along * k / n, yaw) for k in range(n + 1)]
            end = (x + c * along, y + sn * along, yaw)
            steps.append(
                CompiledStep(
                    sid,
                    STRAIGHT,
                    (x, y, yaw),
                    end,
                    length_m=along,
                    samples=samples,
                    duration_est_s=along / route.limits.linear_mps,
                )
            )
            total_len += along
            x, y = end[0], end[1]
        elif s.type == ROTATE:
            if s.direction not in DIRECTIONS:
                raise RouteError(f"direction must be one of {DIRECTIONS}", sid)
            if (
                s.angle_deg is None
                or not math.isfinite(s.angle_deg)
                or int(s.angle_deg) != s.angle_deg
                or int(s.angle_deg) not in ALLOWED_ANGLES_DEG
            ):
                raise RouteError(f"angle_deg must be one of {ALLOWED_ANGLES_DEG}", sid)
            signed = math.radians(s.angle_deg) * (1.0 if s.direction == "ccw" else -1.0)
            w = route.limits.angular_rad_s
            # ramp both ends at the profile's yaw-accel limit is the executor's business;
            # the allowance here is generous: 1.5x the constant-rate time plus 2 s.
            allowance = 1.5 * abs(signed) / w + 2.0
            new_yaw = wrap(yaw + signed)
            steps.append(
                CompiledStep(
                    sid,
                    ROTATE,
                    (x, y, yaw),
                    (x, y, new_yaw),
                    signed_angle_rad=signed,
                    time_allowance_s=allowance,
                    duration_est_s=abs(signed) / w,
                )
            )
            total_turn += abs(signed)
            yaw = new_yaw
        else:
            raise RouteError(f"unknown step type {s.type!r}", sid)
    if not steps:
        raise RouteError("route has no steps")
    end = (x, y, yaw)
    closes = math.hypot(
        end[0] - route.start.x_m, end[1] - route.start.y_m
    ) <= route.limits.position_tolerance_m and abs(wrap(end[2] - route.start.yaw_rad)) <= math.radians(
        route.limits.heading_tolerance_deg
    )
    return CompiledRoute(steps, total_len, total_turn, end, closes)
