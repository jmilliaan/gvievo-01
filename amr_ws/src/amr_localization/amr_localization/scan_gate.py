"""Hold each scan until its odom transform exists, then release it - at a bounded rate.

Why (2026-09-17 vehicle): the nanoScan3 stamps a scan on arrival but the EKF's
odom->base_footprint for that instant lands 20-40 ms later. Every consumer built
on tf2_ros::MessageFilter (slam_toolbox, AMCL) therefore took the asynchronous
"wait for the transform, call back from the TF thread, arm a timeout timer"
path 34 times a second - and slam_toolbox hung in it after ~95 s (executor dead,
0 % CPU, map->odom and /map re-sent with a frozen stamp; a survey that could
never be saved). Scans that are already transformable when the filter sees them
take the synchronous path and never touch that machinery.

This module is the pure decision logic; scan_gate_node wraps it with ROS I/O.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class GateStats:
    received: int = 0
    released: int = 0
    thinned: int = 0  # transformable but inside the minimum period
    expired: int = 0  # never became transformable within hold_max_s


@dataclass
class ScanGate:
    """`push(stamp, msg)` queues a scan; `poll(now, transformable)` returns the
    scans to publish in order. `transformable(stamp)` is asked for the stamp plus
    `settle_s`: needing TF data slightly AFTER the scan guarantees the samples
    bracketing it reached this process a full sample period ago, so a consumer
    whose own TF listener runs a few milliseconds behind still has them."""

    min_period_s: float = 0.1  # 10 Hz is plenty: slam_toolbox thins to minimum_time_interval anyway
    settle_s: float = 0.02  # one EKF period at 50 Hz
    hold_max_s: float = 0.5
    stats: GateStats = field(default_factory=GateStats)
    _pending: deque = field(default_factory=deque)
    _last_out: float | None = None

    def push(self, stamp: float, msg, now: float) -> None:
        self.stats.received += 1
        self._pending.append((stamp, msg, now))

    def poll(self, now: float, transformable: Callable[[float], bool]) -> list:
        out = []
        while self._pending:
            stamp, msg, arrived = self._pending[0]
            if not transformable(stamp + self.settle_s):
                if now - arrived > self.hold_max_s:
                    self._pending.popleft()
                    self.stats.expired += 1
                    continue
                break  # keep order: nothing behind it can go first
            self._pending.popleft()
            if self._last_out is not None and stamp - self._last_out < self.min_period_s - 1e-9:
                self.stats.thinned += 1
                continue
            self._last_out = stamp
            self.stats.released += 1
            out.append(msg)
        return out

    @property
    def pending(self) -> int:
        return len(self._pending)
