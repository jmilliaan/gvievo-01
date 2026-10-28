"""The /amr/rfid stream merged into the driver's snapshot shape. Pure, clock-fed.

line_follow_node feeds every StationDetection here and hands snapshot(now) to the
mission engine (tape_run.scan, TagOdometer), which wants the shape of
agv_core.drivers.rfid.RfidLink.snapshot(encounters=True).

Generation rules (unified plan WP-A1):
- A new generation means rfid_node reconnected or restarted: the buffered
  encounters belong to the old one and are dropped.
- A seq that goes DOWN within one generation can only be a restarted rfid_node
  that happened to draw the same generation, so it is treated as a generation
  change too: the consumer must not keep a cursor from the old numbering.
"""

from __future__ import annotations

import collections


class RfidIntake:
    def __init__(self, fresh_s: float, keep: int = 256) -> None:
        self.fresh_s = float(fresh_s)
        self.encounters: collections.deque = collections.deque(maxlen=keep)
        self.status = {"comms_ok": False, "encounter_seq": 0, "generation": 0, "tag_age_s": None}
        # Bumped on a seq regression inside one generation, so consumers see a change.
        self._epoch = 0
        self._wire_generation: int | None = None
        self.t_recv: float | None = None

    def on_message(self, now: float, heartbeat: bool, tag: str, seq: int, generation: int,
                   comms_ok: bool, tag_age_s: float, work_mode_mismatch: bool = False) -> None:
        seq, generation = int(seq), int(generation)
        same = generation == self._wire_generation
        if same and seq < self.status["encounter_seq"]:
            self._epoch += 1
            same = False
        if not same:
            self.encounters.clear()
            self.status["encounter_seq"] = 0
        self._wire_generation = generation
        if not heartbeat and tag:
            self.encounters.append((seq, str(tag)))
        self.status = {
            "comms_ok": bool(comms_ok),
            "encounter_seq": max(seq, self.status["encounter_seq"]),
            # Still an int: the wire generation is 31 bits, the epoch sits above it.
            "generation": generation + (self._epoch << 32),
            "tag_age_s": None if tag_age_s < 0 else float(tag_age_s),
            "work_mode_mismatch": bool(work_mode_mismatch),
        }
        self.t_recv = now

    def snapshot(self, now: float) -> dict:
        """The driver's snapshot shape. A silent node is a link that is down."""
        fresh = self.t_recv is not None and 0.0 <= now - self.t_recv <= self.fresh_s
        st = dict(self.status)
        st["comms_ok"] = bool(fresh and st["comms_ok"])
        if st["tag_age_s"] is not None and self.t_recv is not None:
            st["tag_age_s"] += now - self.t_recv
        st["encounters"] = list(self.encounters)
        return st
