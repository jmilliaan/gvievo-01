"""/odom_raw computed in drive_node (unified plan WP-C10, cpu-load-plan C#18) and the 6064h-vs-606Ch
plausibility check (H-P2-2, WP-P8). Pure: no rclpy, so the dev box tests it.

WheelOdom replaces diff_drive_odom_node's /wheel_states callback. It integrates the per-sample
increments that canopen.WheelPosition reports (`step`, `step_dt`, `joined`), only when both wheels
are reported valid and both joined: the first sample after a rebaseline starts the chain without
moving it (as diff_drive_odom did), and a bridged staleness gap is integrated whole. Time is the
bus thread's monotonic clock, so a ROS clock step cannot make a dt.

Twist (S-`odom-twist-from-606c`, WP-T4): from the 6064h count deltas over their dt by default
("counts"), as before. "606c" takes it from the drives' 606Ch velocity instead (no dt jitter); the
pose always comes from the counts. Default stays "counts" until the 606Ch lag has been measured
against the 6064h derivative on a logged run (survey verifier).

FeedbackCheck: over windows of `window_s` of measured, joined steps while the drive is ARMED, the
wheel travel from the counts is compared with the travel the 606Ch velocity integrates to:

    |counts - 606Ch| > tol_abs_rad_s * window + tol_rel * max(|counts|, |606Ch|)  -> a bad window

`bad_windows` in a row make the wheel implausible (drive_node reports it invalid and raises
DRIVE_FEEDBACK_IMPLAUSIBLE); `good_windows` agreeing in a row clear it. Comparing travel over a
window, not instantaneous speeds, keeps 606Ch's own lag on a ramp inside the tolerance. Outside
ARMED nothing is judged and the verdict is dropped: with the power stage off 606Ch is not known to
follow a pushed wheel (an on-vehicle check). Commanded-vs-actual is deliberately not checked
(H-P2-2: false trips on ramps).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from amr_base.diff_drive import Geometry, OdomState, forward, integrate

BIG = 1e6
TWIST_SOURCES = ("counts", "606c")


def diag6(*vals: float) -> list[float]:
    cov = [0.0] * 36
    for i, v in enumerate(vals):
        cov[i * 7] = v
    return cov


@dataclass
class WheelOdom:
    geom: Geometry
    twist_source: str = "counts"
    state: OdomState = field(default_factory=OdomState)
    steps: int = 0  # increments integrated
    skipped: int = 0  # valid samples not integrated (a chain start, a bad dt or a non-finite step)

    def __post_init__(self) -> None:
        if self.twist_source not in TWIST_SOURCES:
            raise ValueError(f"odom twist source {self.twist_source!r} not in {TWIST_SOURCES}")

    def update(self, ok: bool, d_l: float, d_r: float, dt: float | None,
               vel_l: float, vel_r: float) -> tuple[float, float] | None:
        """One published wheel sample. ok: both wheels valid and joined. d_*: wheel rad added,
        dt: over how long, vel_*: the 606Ch wheel rad/s. -> (v, wz) to publish, or None."""
        if not ok:
            return None
        if dt is None or not dt > 0.0 or not (math.isfinite(d_l) and math.isfinite(d_r)):
            self.skipped += 1
            return None
        self.state = integrate(self.state, self.geom, d_l, d_r)
        self.steps += 1
        if self.twist_source == "606c":
            return forward(self.geom, vel_l, vel_r)
        return forward(self.geom, d_l / dt, d_r / dt)


@dataclass
class FeedbackCheck:
    max_wheel_rad_s: float  # the motor's rating at the wheel (MOTOR_MAX_RPM, geared)
    window_s: float = 0.5
    tol_abs: float = 0.05  # of max_wheel_rad_s, per second of window
    tol_rel: float = 0.3
    bad_windows: int = 2
    good_windows: int = 2
    implausible: bool = False
    reason: str = ""
    trips: int = 0
    windows: int = 0
    _counts: float = 0.0
    _vel: float = 0.0
    _dt: float = 0.0
    _bad: int = 0
    _good: int = 0

    def _restart(self) -> None:
        self._counts = self._vel = self._dt = 0.0

    def reset(self) -> None:
        self._restart()
        self._bad = self._good = 0
        self.implausible, self.reason = False, ""

    def update(self, t: float, step: float | None, dt: float | None, vel: float, armed: bool) -> bool:
        """One wheel sample: `step` the wheel rad the counts added (None: not a measured
        continuation), over `dt`; `vel` the 606Ch wheel rad/s. Returns `implausible`."""
        if not armed:
            self.reset()
            return False
        if step is None or dt is None or not dt > 0.0 or not (math.isfinite(step) and math.isfinite(vel)):
            self._restart()  # no evidence in this sample; the next window starts clean
            return self.implausible
        self._counts += step
        self._vel += vel * dt
        self._dt += dt
        if self._dt < self.window_s:
            return self.implausible
        c, v, w = self._counts, self._vel, self._dt
        self._restart()
        self.windows += 1
        tol = self.tol_abs * self.max_wheel_rad_s * w + self.tol_rel * max(abs(c), abs(v))
        if abs(c - v) > tol:
            self._bad, self._good = self._bad + 1, 0
            if not self.implausible and self._bad >= self.bad_windows:
                self.implausible, self.trips = True, self.trips + 1
                self.reason = f"counts {c / w:+.2f} rad/s against 606Ch {v / w:+.2f} rad/s over {w:.2f} s"
        else:
            self._good, self._bad = self._good + 1, 0
            if self.implausible and self._good >= self.good_windows:
                self.implausible, self.reason = False, ""
        return self.implausible
