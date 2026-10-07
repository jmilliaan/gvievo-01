"""RFID speed toggle (2026-10-07): any toggle tag flips cruise <-> slow.

A single bidirectional line with corners: a tag pair brackets each corner and
the vehicle may enter from either end, so a tag cannot mean "slow" or "fast" by
itself. Every tag in the set means "change speed":

    slow and read a toggle tag -> fast
    fast and read a toggle tag -> slow

then every toggle tag is ignored for `lockout_s`, so a tag read twice, or two
tags close together, do not flip it straight back.

*** The state is one bit and nothing re-synchronises it. *** A missed read
inverts every corner after it - fast through corners, slow on straights - until
another miss or a new run, which starts fast. Accepted deliberately (true toggle
chosen over pair-aware); the operator sees the speed and each flip in the event log.

The lockout applies to toggle tags ONLY. Station, U-turn and branch tags are a
different namespace (agv_core.mission refuses overlaps) and are never held off.

Pure and clock-fed: no ROS, no I/O; the caller passes `now`.
"""


class SpeedToggle:
    def __init__(self, tags=(), lockout_s=2.0):
        self.tags = frozenset(tags)
        self.lockout_s = float(lockout_s)
        self.slow = False
        self.changed_at = None
        self.ignored = 0            # toggle reads swallowed by the lockout, for the UI

    def scan(self, now, tag):
        """One tag encounter. Returns "slow" / "fast" if it flipped, "lockout"
        if it was a toggle tag inside the lockout, None if not a toggle tag."""
        if tag not in self.tags:
            return None
        if self.changed_at is not None and now - self.changed_at < self.lockout_s:
            self.ignored += 1
            return "lockout"
        self.slow = not self.slow
        self.changed_at = now
        return "slow" if self.slow else "fast"
