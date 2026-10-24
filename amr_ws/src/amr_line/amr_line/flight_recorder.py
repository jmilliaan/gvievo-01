"""Line flight recorder (2026-10-24): the last seconds of every control tick, written to a
CSV when something worth explaining happens - a run ending, a hold, a kink pivot, a U-turn.

The events log says WHAT happened ("track lost"); this says why: the MLS reading, track
level and #LCP, the follower's state and error, and the wheel commands, tick by tick. Pure
apart from the file write; a disk problem is reported to the caller, never raised into the
control loop.
"""
from __future__ import annotations

import collections
import csv
import os
import time

FIELDS = ("t", "job", "engine", "nlcp", "tracks_mm", "level", "has_track", "e_used_mm",
          "v_base_rpm", "left_rpm", "right_rpm", "kink", "uturn", "travel_m", "note")


class FlightRecorder:
    def __init__(self, state_dir, span_s=15.0, rate_hz=50.0, keep=60):
        self.dir = os.path.join(state_dir, "logs", "line_trace")
        self.rows = collections.deque(maxlen=max(1, int(span_s * rate_hz)))
        self.keep = int(keep)

    def add(self, **row):
        self.rows.append(row)

    def dump(self, reason, now=None):
        """Write the buffer as <date-time>-<reason>.csv. Returns the path; OSError to the caller."""
        if not self.rows:
            return None
        os.makedirs(self.dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        slug = "".join(c if c.isalnum() else "-" for c in reason.lower())[:40].strip("-")
        path = os.path.join(self.dir, f"{stamp}-{slug}.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in self.rows:
                w.writerow(r)
        self._prune()
        return path

    def _prune(self):
        files = sorted(f for f in os.listdir(self.dir) if f.endswith(".csv"))
        for f in files[:-self.keep]:
            try:
                os.unlink(os.path.join(self.dir, f))
            except OSError:
                pass
