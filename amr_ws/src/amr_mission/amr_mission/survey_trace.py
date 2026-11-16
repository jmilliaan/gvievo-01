"""IMU gaps during a survey leave a trace (sensor-dropout plan H-P1-16, unified plan WP-E9). Pure.

slam_toolbox builds the map from the EKF's odom, and the EKF's yaw rate is the IMU. A
survey that ran through an IMU dropout can look fine on screen and still be bent
(boiacca-map-1 rev1 was corrupt). mapping_session feeds every /imu/data arrival here
while SLAM is taking scans; the total of the gaps longer than the age limit goes into
MappingState.message, one event on the first gap, and the revision manifest's review,
so the map can be rejected later. Advisory only: nothing here moves or stops the vehicle.
"""

from __future__ import annotations


class ImuGaps:
    """Sum of /imu/data gaps longer than `limit_s` since start(). A gap still open counts
    up to `now` (a dead IMU never sends the sample that would close it)."""

    def __init__(self, limit_s: float = 0.20) -> None:
        self.limit_s = float(limit_s)
        self.active = False
        self.count = 0  # closed gaps
        self._closed_s = 0.0
        self._last: float | None = None
        self._reported = False

    def start(self, t: float) -> None:
        """A survey begins: the clock runs from now (no sample yet is not a gap before t)."""
        self.active, self.count, self._closed_s, self._last, self._reported = True, 0, 0.0, t, False

    def pause(self, t: float) -> None:
        """SLAM stopped taking scans (saving, saved, aborted): a gap still open ends at t."""
        if self.active and self._last is not None and t - self._last > self.limit_s:
            self._closed_s += t - self._last
            self.count += 1
        self.active = False

    def resume(self, t: float) -> None:
        """The same survey goes on (a save failed): totals kept, the clock restarts at t."""
        self.active, self._last = True, t

    def sample(self, t: float) -> None:
        if not self.active:
            return
        if self._last is not None and t - self._last > self.limit_s:
            self._closed_s += t - self._last
            self.count += 1
        self._last = t if self._last is None else max(self._last, t)

    def open_s(self, now: float) -> float:
        if not self.active or self._last is None or now - self._last <= self.limit_s:
            return 0.0
        return now - self._last

    def total_s(self, now: float) -> float:
        return self._closed_s + self.open_s(now)

    def first_gap(self, now: float) -> bool:
        """True exactly once per survey: when the first gap shows (closed or still open)."""
        if self._reported or self.total_s(now) <= 0.0:
            return False
        self._reported = True
        return True

    def summary(self, now: float) -> dict:
        """What the manifest records."""
        return {"imu_gap_s": round(self.total_s(now), 2),
                "imu_gaps": self.count + (1 if self.open_s(now) > 0.0 else 0),
                "imu_gap_limit_s": self.limit_s}

    def text(self, now: float) -> str:
        """'' with no gap, else the line MappingState.message carries."""
        g = self.total_s(now)
        if g <= 0.0:
            return ""
        return f"IMU gaps {g:.1f} s this survey (map may be bent: check it before use)"
