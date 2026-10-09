"""The marker stream's cursor (manuals/mls-marker-plan.md 6, 2026-10-09).

Pure. The node keeps /amr/line_marker as a snapshot - the latest status and the recent
events of the current generation - in the same shape as the RFID encounter stream:

    {"ok": bool, "status": str, "generation": int, "base": int,
     "encounters": [(seq, code, direction, lcp2_mm), ...]}

`base` is the seq the node had already seen when it first met this generation (the
heartbeat's latest seq, or one before the first event), so a line follower started
after drive_node does not count every earlier marker as missed.

DISPLAY ONLY for now: the job logs each marker and shows the last one; nothing changes
the state or the speed (plan section 8 decides what a code means, later).
"""


class MarkerReader:
    def __init__(self):
        self.generation = None
        self.cursor = 0
        self.count = 0     # markers read since the node started
        self.missed = 0    # sequence gaps: messages lost on the topic
        self.last = None   # {"code", "direction", "lcp2_mm"} of the newest marker

    def scan(self, snap):
        """New markers since the last call, oldest first: [(code, direction, lcp2_mm, gap)]
        where gap is how many markers went missing just before this one."""
        if not snap:
            return []
        gen = snap.get("generation")
        if gen != self.generation:
            self.generation = gen
            self.cursor = int(snap.get("base", 0))
        out = []
        for seq, code, direction, lcp2 in snap.get("encounters") or ():
            if seq <= self.cursor:
                continue
            gap = seq - self.cursor - 1
            self.missed += gap
            self.cursor = seq
            self.count += 1
            self.last = {"code": int(code), "direction": int(direction), "lcp2_mm": int(lcp2)}
            out.append((int(code), int(direction), int(lcp2), gap))
        return out
