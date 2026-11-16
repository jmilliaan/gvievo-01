"""Hold each scan until its odom transform exists, then release it - at a bounded rate.

Why (2026-09-17 vehicle): the nanoScan3 stamps a scan on arrival but the EKF's
odom->base_footprint for that instant lands 20-40 ms later. Every consumer built
on tf2_ros::MessageFilter (slam_toolbox, AMCL) therefore took the asynchronous
"wait for the transform, call back from the TF thread, arm a timeout timer"
path 34 times a second - and slam_toolbox hung in it after ~95 s (executor dead,
0 % CPU, map->odom and /map re-sent with a frozen stamp; a survey that could
never be saved). Scans that are already transformable when the filter sees them
take the synchronous path and never touch that machinery.

Consumers of /scan_gated: slam_toolbox, AMCL, the Nav2 local costmap's obstacle
layer, the localization monitor's scan-vs-map comparison and the route executor's
obstruction check. The web live view stays on raw /scan.

This module is the pure decision logic; scan_gate_node wraps it with ROS I/O.

Raw pass-through (CPU, 2026-11-16, cpu-load plan §4a d): the node takes /scan as its
serialized bytes and publishes those same bytes. The gate only needs the stamp and the
frame, which cdr_header() reads from the front of the CDR buffer; no LaserScan is ever
deserialised or serialised here.
"""

from __future__ import annotations

import math
import struct
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
    max_pending: int = 64  # ~2 s of 34 Hz scans; older ones are worthless anyway
    rewind_s: float = 1.0  # a stamp this far behind the last release is a source-clock reset
    stats: GateStats = field(default_factory=GateStats)
    _pending: deque = field(default_factory=deque)
    _last_out: float | None = None

    def __post_init__(self) -> None:
        for name in ("min_period_s", "settle_s", "hold_max_s", "rewind_s"):
            v = getattr(self, name)
            if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0.0):
                raise ValueError(f"{name} must be a finite non-negative number, got {v!r}")
        if self.max_pending < 1:
            raise ValueError("max_pending must be >= 1")

    def push(self, stamp: float, msg, now: float, frame: str | None = None) -> None:
        """`frame`: the scan's frame_id when `msg` is raw bytes (None: msg.header.frame_id)."""
        self.stats.received += 1
        if self._last_out is not None and stamp < self._last_out - self.rewind_s:
            # the source clock went backwards (bag/sim restart): the old epoch's thinning
            # reference would silence every scan until the stamps caught up (review Q13)
            self._last_out = None
        # Dropped at the door (CPU, 2026-10-02): a scan inside min_period_s of the last
        # RELEASE can only ever be thinned - _last_out only moves forward (a rewind is
        # handled above) - so queueing it buys TF queries for nothing.
        if (self._last_out is not None and stamp >= self._last_out
                and stamp - self._last_out < self.min_period_s - 1e-9):
            self.stats.thinned += 1
            return
        self._pending.append((stamp, msg, now, frame))
        while len(self._pending) > self.max_pending:
            self._pending.popleft()
            self.stats.expired += 1

    def poll(self, now: float, transformable: Callable[[float], bool]) -> list:
        out = []
        while self._pending:
            stamp, msg, arrived, _frame = self._pending[0]
            # residence deadline first, whatever TF says: a scan that sat here past
            # hold_max_s (a stalled timer) is stale even if it is transformable now (Q13)
            if now - arrived > self.hold_max_s:
                self._pending.popleft()
                self.stats.expired += 1
                continue
            if not transformable(stamp + self.settle_s):
                break  # keep order: nothing behind it can go first
            self._pending.popleft()
            if self._last_out is not None and stamp - self._last_out < self.min_period_s - 1e-9:
                self.stats.thinned += 1
                continue
            self._last_out = stamp
            self.stats.released += 1
            out.append(msg)
        return out

    def frame_of_oldest(self):
        if not self._pending:
            return None
        _stamp, msg, _arrived, frame = self._pending[0]
        return msg.header.frame_id if frame is None else frame

    @property
    def pending(self) -> int:
        return len(self._pending)


def cdr_header(raw: bytes) -> tuple[float, str]:
    """(stamp in s, frame_id) of a serialized message whose first field is a std_msgs/Header
    (LaserScan). Layout: the 4-byte encapsulation header (byte 1: 1 = little endian), then
    int32 sec, uint32 nanosec, uint32 string length (with its NUL), the characters. Every
    field sits on its natural alignment, so no padding. ValueError on a buffer too short
    or a length that runs past it."""
    if len(raw) < 16:
        raise ValueError(f"serialized message too short for a header ({len(raw)} bytes)")
    e = "<" if raw[1] & 1 else ">"
    sec, nanosec, n = struct.unpack_from(e + "iII", raw, 4)
    if n < 1 or 16 + n > len(raw):
        raise ValueError(f"frame_id length {n} runs past the {len(raw)}-byte buffer")
    frame = bytes(raw[16:16 + n - 1]).decode("utf-8", errors="replace")
    return (sec * 1_000_000_000 + nanosec) * 1e-9, frame  # as Time.from_msg(stamp).nanoseconds * 1e-9
