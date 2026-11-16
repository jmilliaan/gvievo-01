"""The marker stream's cursor (manuals/mls-marker-plan.md 6, 2026-10-09).

Pure. The node keeps /amr/line_marker as a snapshot - the latest status and the recent
events of the current generation - in the same shape as the RFID encounter stream:

    {"ok": bool, "status": str, "generation": int, "base": int,
     "encounters": [(seq, code, direction, lcp2_mm, line_good), ...]}

`base` is the seq the node had already seen when it first met this generation (the
heartbeat's latest seq, or one before the first event), so a line follower started
after drive_node does not count every earlier marker as missed.

The job logs each marker and shows the last one. Since 2026-10-09 the high-zone codes
also go to the speed zone (amr_line.tape_run.markers); no marker changes the job's state.
"""


class MarkerReader:
    def __init__(self):
        self.generation = None
        self.cursor = 0
        self.count = 0     # markers read since the node started
        self.missed = 0    # sequence gaps: messages lost on the topic
        self.last = None   # {"code", "direction", "lcp2_mm"} of the newest marker
        self._gaps = None  # drive_node's TPDO1 hole counter (MarkerEvent.gaps) last seen
        self.holes = 0     # TPDO1 holes seen since the node started (WP-E8)

    def scan(self, snap):
        """New markers since the last call, oldest first: [(code, direction, lcp2_mm, gap,
        line_good)] where gap is how many markers went missing just before this one. An
        entry without line_good is not good: it can never count as a speed cue.

        TPDO1 holes (WP-E8, 2026-11-16): when drive_node's `gaps` counter grew, one more entry
        (0, 0, 0, holes, False) comes last: a marker may have been decoded in a hole and never
        sent. Code 0 is no marker (codes are 1..7), so it matches no zone or marker-run code;
        its gap is what tape_run's marker_lost / drop_high act on. The counter is followed
        across marker generations (an MLS reboot while moving still counts); a counter that went
        DOWN is a restarted drive_node: stored, not counted."""
        if not snap:
            return []
        gen = snap.get("generation")
        if gen != self.generation:
            self.generation = gen
            self.cursor = int(snap.get("base", 0))
        out = []
        for seq, code, direction, lcp2, *rest in snap.get("encounters") or ():
            if seq <= self.cursor:
                continue
            gap = seq - self.cursor - 1
            self.missed += gap
            self.cursor = seq
            self.count += 1
            self.last = {"code": int(code), "direction": int(direction), "lcp2_mm": int(lcp2)}
            out.append((int(code), int(direction), int(lcp2), gap, bool(rest and rest[0])))
        gaps = snap.get("gaps")
        if gaps is not None:
            gaps = int(gaps)
            if self._gaps is not None and gaps > self._gaps:
                self.holes += gaps - self._gaps
                out.append((0, 0, 0, gaps - self._gaps, False))
            self._gaps = gaps
        return out
