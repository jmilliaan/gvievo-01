"""Age-only streams drained at the monitor's tick (CPU 2026-11-16, cpu-load plan §4a a = C#10).

localization_monitor reads /scan, /imu/data, /wheel_states and /drives/status only to
know how old they are (plus a validity bit or two). One executor wakeup per message
cost ~8 % of a core. Their subscriptions now sit in a callback group the executor never
waits on, and the 10 Hz tick takes whatever has queued with take_message().

The age of a sample is its DDS source_timestamp: the publisher's wall-clock write time,
which the Humble take returns in the message info (CycloneDDS leaves received_timestamp
0). Draining late therefore never makes a sample look older or younger than it is. The
limits (readiness.Limits.age_limits) are unchanged.

Pure: `take` is any callable returning (msg, info) or None, as
Subscription.handle.take_message does.
"""

from __future__ import annotations

from collections.abc import Callable

MAX_TAKE = 64  # per stream per drain; the reader cache holds the QoS depth (5) anyway


def sample_time(now: float, wall_now_ns: int, info, prev_drain: float | None) -> float | None:
    """When a taken sample was written, on the node's clock (`now`, s).

    Its wall-clock age (wall_now_ns - source_timestamp) is carried over to the node
    clock, so the result is right under sim time too. A source time in the future
    (clock step) counts as age 0. With no source timestamp the sample is credited with
    the previous drain: it arrived after that, so this can only overstate its age.
    None (not evidence) when there is neither."""
    src = 0
    if isinstance(info, dict):
        src = int(info.get("source_timestamp", 0) or 0)
    if src > 0:
        return now - max(0.0, (wall_now_ns - src) * 1e-9)
    return prev_drain


def drain(take: Callable, now: float, wall_now_ns: int, prev_drain: float | None,
          limit: int = MAX_TAKE) -> list[tuple[object, float]]:
    """Every queued sample as (msg, sample_time), oldest first; at most `limit`."""
    out = []
    for _ in range(limit):
        got = take()
        if got is None:
            break
        msg, info = got
        t = sample_time(now, wall_now_ns, info, prev_drain)
        if t is not None:
            out.append((msg, t))
    return out


def newest(samples: list[tuple[object, float]], keep: Callable = lambda _m: True) -> float | None:
    """The latest sample time among the samples `keep` accepts, or None."""
    times = [t for m, t in samples if keep(m)]
    return max(times) if times else None
