"""Teaching the tape graph (tracked plan 3, D3: teach and repeat, never draw). Pure.

A PASS is one full circuit, HOME bay to HOME bay, driven on the tape (an ordinary
LINE run or a supervised drive) while AMCL localises on the bound map revision. It
records AMCL positions against wheel travel, the MLS fork episodes and the U-turn.

build() cuts every pass at its NODES - the laid junctions and U-turns of the circuit,
in order - and averages each leg over its passes:

  - a junction node is where the MLS saw a single track again (tape_graph.ForkDetector),
    the same point the locator resyncs at;
  - a U-turn node is where the approach stopped at the tape end;
  - the home leg is the end of the pass (after the last node) joined to its start
    (before the first node): park where the pass began.

A pass whose events do not match the circuit's nodes is refused with both sequences:
an MLS that missed a fork, or a circuit driven differently from the mission, would
otherwise teach a leg that is two legs. Stations are taught separately, at standstill
under MANUAL, on legs that are already built.
"""

import datetime
import math
import statistics

from amr_line import tape_graph as tg
from amr_line.tape_locator import OdomBuffer

# A home leg whose pass ended this far from where it started is refused.
HOME_GAP_M = 0.5
# Quality flags for the Teach page (plan section 4, P1).
MIN_PASSES = 3
MAX_SPREAD_M = 0.05
# Averaging passes: how far along a pass to look for the point matching the reference.
WINDOW_M = 0.5
# A fork episode this close to a pivot (a kink corner or the U-turn spin) is the corner seen
# by the MLS - incoming and outgoing tape under the sensor at once - not a junction
# (2026-10-24: 6 and 7 forks on the way out where C-MRU has 4; 1 and 2 kink pivots).
PIVOT_FORK_M = 0.4
# Matching by position (2026-10-24): every junction's fork episode ends at the same map point
# lap after lap (two passes agreed within 5 cm), while the episode COUNT does not (the bay
# merge sits on a kink corner, a 3 cm blip follows J-N). With anchors, each node takes the
# episode nearest its anchor, in circuit order, within this radius; everything else is not
# a junction. Without anchors, the count heuristic below.
ANCHOR_R_M = 0.6
# A mark (2026-10-24) is taken from the moving vehicle: the last AMCL pose, projected onto
# the leg it lies on and facing along, then moved on by the wheel travel since that pose.
MARK_MAX_LATERAL_M = 0.30
MARK_MAX_YAW_DEG = 60.0


class TeachError(ValueError):
    pass


class PassRecorder:
    """One pass being recorded. Fed by the node every tick and on every AMCL pose."""

    def __init__(self, circuit, started=""):
        self.circuit = circuit
        self.started = started
        self.samples = []     # [travel, x, y]
        self.forks = []       # [start, end, crossing]
        self.uturns = []      # [travel]
        self.pivots = []      # [travel] where a kink pivot or a U-turn spin began
        self.odom = OdomBuffer(span_s=3.0)
        self.forks_seen = tg.ForkDetector()
        self.dropped = 0      # poses without odometry at their stamp
        self._pivoting = False

    def tick(self, t, travel, nlcp, pivot=False):
        """pivot: a kink pivot or the U-turn spin is turning the sensor across the tape."""
        self.odom.add(t, travel)
        if pivot and not self._pivoting:
            self.pivots.append(float(travel))
        self._pivoting = bool(pivot)
        ep = self.forks_seen.update(travel, 0 if pivot else nlcp)
        if ep is not None:
            self.forks.append([ep[0], ep[1], ep[2]])

    def pose(self, stamp, x, y):
        tr = self.odom.at(stamp)
        if tr is None:
            self.dropped += 1
            return
        if self.samples and tr < self.samples[-1][0] - 0.02:
            self.dropped += 1   # reversing (a jog back): not a pass any more
            return
        self.samples.append([tr, float(x), float(y)])

    def uturn(self, travel):
        self.uturns.append(float(travel))

    def summary(self):
        length = self.samples[-1][0] - self.samples[0][0] if len(self.samples) > 1 else 0.0
        return (f"{self.circuit}: {length:.1f} m, {len(self.samples)} poses, {len(self.forks)} forks, "
                f"{len(self.uturns)} U-turn(s), {self.dropped} poses dropped")

    def to_dict(self):
        return {"circuit": self.circuit, "started": self.started, "samples": self.samples,
                "forks": self.forks, "uturns": self.uturns, "pivots": self.pivots}


def _interp(samples, travel):
    """(x, y) at a wheel travel inside the samples."""
    lo = 0
    for i in range(len(samples) - 1):
        if samples[i + 1][0] >= travel:
            lo = i
            break
    else:
        lo = len(samples) - 2
    (t0, x0, y0), (t1, x1, y1) = samples[lo], samples[lo + 1]
    f = 0.0 if t1 == t0 else min(max((travel - t0) / (t1 - t0), 0.0), 1.0)
    return x0 + f * (x1 - x0), y0 + f * (y1 - y0)


def _cut(samples, t0, t1):
    pts = [_interp(samples, t0)] + [(x, y) for t, x, y in samples if t0 < t < t1] + [_interp(samples, t1)]
    return pts


def _nodes(mission, circuit_id):
    legs = mission["CIRCUITS"][circuit_id]["legs"]
    return [leg["from"] for leg in legs[:-1]] + [legs[-1]["from"]]


def _align_anchored(rec, nodes, want, samples, anchors, turns, notes):
    """_align by position: each fork node takes the nearest episode to its anchor."""
    t0, t1 = samples[0][0], samples[-1][0]
    eps = sorted(end for _s, end, _x in rec["forks"] if t0 < end < t1)
    bounds = [t0] + turns + [t1]
    events, stretch, last = [], 0, t0
    for n, kind in zip(nodes, want, strict=True):
        if kind == "uturn":
            events.append((turns[stretch], "uturn", 0.0))
            stretch += 1
            last = turns[stretch - 1]
            continue
        ax, ay = anchors[n]
        cands = [(math.dist(_interp(samples, e), (ax, ay)), e) for e in eps if last < e < bounds[stretch + 1]]
        if not cands:
            raise TeachError(f"pass {rec.get('started')}: no fork episode left for {n} after {last:.1f} m "
                             f"- a missed MLS fork or a different route")
        d, e = min(cands)
        if d > ANCHOR_R_M:
            raise TeachError(f"pass {rec.get('started')}: no fork within {ANCHOR_R_M} m of {n}'s position "
                             f"(nearest {d:.2f} m, at {e:.1f} m) - a missed MLS fork or a different route")
        span = next(end - start for start, end, _x in rec["forks"] if end == e)
        events.append((e, "fork", span))
        notes.append(f"{n} at {e:.1f} m ({d:.2f} m from its position)")
        last = e
    used = {e for e, k, _b in events if k == "fork"}
    extra = [e for e in eps if e not in used]
    if extra:
        notes.append("not junctions: " + ", ".join(f"{e:.1f} m" for e in extra))
    return events


def _align(rec, nodes, want, t0, t1, notes):
    """The pass's events matched to the circuit's nodes -> [(travel, kind, fork_back)].

    The U-turns split the pass into stretches; each stretch must give exactly the forks its
    nodes need. Fork episodes at a pivot (kink corner, U-turn spin) are corners: dropped
    first. Still too many: the shortest episodes go (a junction keeps two tapes under the
    sensor longest). Too few: corner episodes come back, longest first. Every dropped or
    restored episode is noted, so the engineer can check it against the floor."""
    pivots = list(rec.get("pivots", [])) + list(rec["uturns"])
    eps = []
    for start, end, cross in rec["forks"]:
        if t0 < end < t1:
            corner = any(start - PIVOT_FORK_M <= p <= end + PIVOT_FORK_M for p in pivots)
            eps.append({"end": end, "span": end - start, "corner": corner, "cross": bool(cross)})
    turns = sorted(t for t in rec["uturns"] if t0 < t < t1)
    n_turns = want.count("uturn")
    if len(turns) != n_turns:
        raise TeachError(f"pass {rec.get('started')}: {len(turns)} U-turn(s) recorded, the circuit has "
                         f"{n_turns} - a run that did not U-turn, or a different route")
    bounds = [t0] + turns + [t1]
    counts, k = [], 0
    for kind in want + ["uturn"]:
        if kind == "uturn":
            counts.append(k)
            k = 0
        else:
            k += 1
    events = []
    for i, need in enumerate(counts):
        lo, hi = bounds[i], bounds[i + 1]
        here = sorted((e for e in eps if lo < e["end"] < hi), key=lambda e: e["end"])
        keep = [e for e in here if not e["corner"]]
        extra = sorted((e for e in here if e["corner"]), key=lambda e: -e["span"])
        while len(keep) < need and extra:
            e = extra.pop(0)
            keep.append(e)
            notes.append(f"kept a fork at a pivot, {e['end']:.1f} m (two tapes {e['span']:.2f} m)")
        for e in extra:
            notes.append(f"dropped a corner fork at {e['end']:.1f} m (two tapes {e['span']:.2f} m, pivot)")
        while len(keep) > need:
            # the shortest goes: 2026-10-24 a 4 cm blip next to X1 (#LCP 7 like X1 itself)
            e = min(keep, key=lambda e: e["span"])
            keep.remove(e)
            notes.append(f"dropped the shortest fork at {e['end']:.1f} m (two tapes {e['span']:.2f} m)")
        if len(keep) < need:
            names = [n for n, w in zip(nodes, want, strict=True) if w == "fork"]
            raise TeachError(
                f"pass {rec.get('started')}: {len(keep)} fork(s) between {lo:.1f} and {hi:.1f} m where "
                f"the circuit needs {need} - a missed MLS fork or a different route (forks: {names})")
        keep.sort(key=lambda e: e["end"])
        names = [n for n, w in zip(nodes, want, strict=True) if w == "fork"]
        first = sum(counts[:i])
        notes.append(", ".join(f"{names[first + j]} at {e['end']:.1f} m" for j, e in enumerate(keep)))
        events += [(e["end"], "fork", e["span"]) for e in keep]
        if i < len(turns):
            events.append((turns[i], "uturn", 0.0))
    return sorted(events)


def split_pass(rec, mission, notes=None, anchors=None):
    """One recorded pass -> {leg id: {"pts", "fork_back"}}. TeachError if it does not match.
    notes: a list that receives what the matching dropped or restored."""
    cid = rec["circuit"]
    legs = mission["CIRCUITS"][cid]["legs"]
    nodes = _nodes(mission, cid)
    samples = sorted(rec["samples"])
    if len(samples) < 10:
        raise TeachError(f"pass {rec.get('started')}: only {len(samples)} AMCL poses")
    want = ["uturn" if n in mission["UTURNS"] else "fork" for n in nodes]
    notes = [] if notes is None else notes
    forks = [n for n, w in zip(nodes, want, strict=True) if w == "fork"]
    if anchors and all(n in anchors for n in forks):
        turns = sorted(t for t in rec["uturns"] if samples[0][0] < t < samples[-1][0])
        if len(turns) != want.count("uturn"):
            raise TeachError(f"pass {rec.get('started')}: {len(turns)} U-turn(s) recorded, the circuit has "
                             f"{want.count('uturn')} - a run that did not U-turn, or a different route")
        events = _align_anchored(rec, nodes, want, samples, anchors, turns, notes)
    else:
        events = _align(rec, nodes, want, samples[0][0], samples[-1][0], notes)
    b = [t for t, _k, _ in events]
    out = {}
    for i, leg in enumerate(legs[:-1]):
        out[leg["id"]] = {"pts": _cut(samples, b[i], b[i + 1]), "fork_back": events[i + 1][2],
                          "end_kind": events[i + 1][1]}
    # The home leg: from the last node to the end of the pass, then the start of the pass
    # to the first node.
    suffix = _cut(samples, b[-1], samples[-1][0])
    prefix = _cut(samples, samples[0][0], b[0])
    home = legs[-1]["id"]
    if len(suffix) < 2:
        raise TeachError(f"pass {rec.get('started')}: ended at {nodes[-1]}, before the home leg")
    line = tg.Polyline(suffix)
    hit = line.project(*prefix[0])
    if hit and hit[0] < line.length - 1e-6 and abs(hit[1]) <= tg.STATION_MAX_LATERAL_M:
        pts = line.cut(0.0, hit[0]) + prefix[1:]
    else:
        gap = math.dist(suffix[-1], prefix[0])
        if gap > HOME_GAP_M:
            raise TeachError(f"pass {rec.get('started')}: ended {gap:.2f} m from where it started "
                             f"(> {HOME_GAP_M} m): park where the pass began")
        pts = suffix + prefix
    out[home] = {"pts": pts, "fork_back": events[0][2], "end_kind": events[0][1]}
    return out


def place_mark(graph, x, y, yaw, ahead_m=0.0):
    """A pose -> (leg id, s, d, (x, y, heading) on the tape, metres clamped past the leg's end).
    The leg is the nearest one within MARK_MAX_LATERAL_M whose direction matches the
    heading (the two directions of a tape are two legs); s moves on by ahead_m."""
    best = None
    for leg in graph.legs.values():
        hit = leg.line.project(x, y)
        if hit is None:
            continue
        s, d = hit
        h = leg.line.point(s)[2]
        dyaw = abs(math.degrees(math.atan2(math.sin(yaw - h), math.cos(yaw - h))))
        if abs(d) > MARK_MAX_LATERAL_M or dyaw > MARK_MAX_YAW_DEG:
            continue
        if best is None or (abs(d), dyaw) < best[0]:
            best = ((abs(d), dyaw), leg, s, d)
    if best is None:
        raise TeachError(f"({x:.2f}, {y:.2f}) is not on a built leg (within {MARK_MAX_LATERAL_M} m, "
                         f"facing along it)")
    _, leg, s, d = best
    s2 = s + ahead_m
    over = max(0.0, s2 - leg.line.length)
    s2 = min(max(s2, 0.0), leg.line.length)
    return leg.id, s2, d, leg.line.point(s2), over


def mean_leg(ident, frm, order, to, segs, fork_backs, end_kind):
    """Average a leg over its passes -> tape_graph.Leg."""
    lines = [tg.Polyline(tg.resample(p)) for p in segs if len(p) >= 2]
    if not lines:
        raise TeachError(f"leg {ident}: no usable pass")
    lines.sort(key=lambda g: g.length)
    ref = lines[len(lines) // 2]
    # Passes run parallel, so a point projects near the same fraction of every pass: the
    # window keeps it off another stretch of the same tape (a leg that turns back).
    pts = []
    for s_ref, (x, y) in zip(ref.s, ref.pts, strict=True):
        xs, ys = [x], [y]
        for other in lines:
            if other is ref:
                continue
            guess = s_ref * other.length / ref.length
            hit = other.project(x, y, guess - WINDOW_M, guess + WINDOW_M)
            if hit and 1e-6 < hit[0] < other.length - 1e-6:
                px, py, _ = other.point(hit[0])
                xs.append(px)
                ys.append(py)
        pts.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    mean = tg.Polyline(tg.resample(pts))
    # Hinted: a leg may start and end at the same floor point (pivot to pivot on a straight).
    starts = [mean.project(*g.pts[0], hint=0.0)[0] for g in lines]
    ends = [mean.project(*g.pts[-1], hint=mean.length)[0] for g in lines]
    s0, s1 = statistics.median(starts), statistics.median(ends)
    spread = 0.0
    for g in lines:
        for s_g, (x, y) in zip(g.s[1:-1], g.pts[1:-1], strict=True):
            guess = s_g * mean.length / g.length
            hit = mean.project(x, y, guess - WINDOW_M, guess + WINDOW_M)
            if hit and 1e-6 < hit[0] < mean.length - 1e-6:
                spread = max(spread, abs(hit[1]))
    final = tg.resample(mean.cut(s0, s1))
    return tg.Leg(ident, frm, order, to, final, passes=len(lines), spread_m=spread,
                  end_spread_m=max(abs(e - s1) for e in ends),
                  fork_back_m=statistics.median(fork_backs) if end_kind == "fork" else 0.0,
                  end_kind=end_kind)


def build(passes, mission, binding, stations=(), notes="", anchors=None):
    """Recorded passes (dicts) + the site mission -> (Graph, report lines).

    Refused passes are reported and left out; legs with no pass are simply not in the
    graph (tape_graph.compile_route names them). `stations` are taught station records
    (dicts with "id" and "pose"): re-projected onto the rebuilt legs."""
    report, per_leg = [], {}
    for rec in passes:
        if rec.get("circuit") not in mission["CIRCUITS"]:
            report.append(f"pass {rec.get('started')}: circuit {rec.get('circuit')!r} not in the mission")
            continue
        notes = []
        try:
            parts = split_pass(rec, mission, notes, anchors)
        except (TeachError, tg.GraphError) as e:
            report.append(f"REFUSED {e}")
            continue
        report += [f"pass {rec.get('started')}: {n}" for n in notes]
        for lid, part in parts.items():
            per_leg.setdefault(lid, []).append(part)
    specs = {leg["id"]: leg for c in mission["CIRCUITS"].values() for leg in c["legs"]}
    legs = []
    for lid, parts in sorted(per_leg.items()):
        spec = specs[lid]
        kinds = {p["end_kind"] for p in parts}
        leg = mean_leg(lid, spec["from"], spec["order"], spec["to"], [p["pts"] for p in parts],
                       [p["fork_back"] for p in parts], kinds.pop() if len(kinds) == 1 else "fork")
        flag = ""
        if leg.passes < MIN_PASSES:
            flag += f" (needs {MIN_PASSES} passes)"
        if leg.spread_m > MAX_SPREAD_M:
            flag += f" (spread > {MAX_SPREAD_M} m: check AMCL on this stretch)"
        report.append(f"{lid}: {leg.length:.2f} m, {leg.passes} pass(es), spread {leg.spread_m:.3f} m, "
                      f"end spread {leg.end_spread_m:.3f} m{flag}")
        legs.append(leg)
    g = tg.Graph(binding, legs, mission=mission["MISSION_NAME"], notes=notes)
    for st in stations:
        try:
            g.put_station(project_station(g, mission, st["id"], st["pose"], st.get("taught", ""),
                                          st.get("samples", 0)))
        except tg.GraphError as e:
            report.append(f"station {st['id']} dropped: {e}")
    return g, report


def project_station(graph, mission, sid, pose, taught="", samples=0):
    """A station's taught pose -> tape_graph.Station on its leg (GraphError if not there).

    A site-4 point (tracked plan 4) is taught the same way: a U-turn point on its machine's
    release leg; a zone end on whichever leg it lies on and faces along (place_mark)."""
    points = mission.get("POINTS", {})
    lid = mission["STATIONS"].get(sid) or points.get(sid)
    if lid is None and sid in points:
        try:
            lid = place_mark(graph, *pose)[0]
        except TeachError as e:
            raise tg.GraphError(f"{sid}: {e}") from None
    if lid is None:
        raise tg.GraphError(f"{sid} is not a station or point of {mission['MISSION_NAME']}")
    leg = graph.legs.get(lid)
    if leg is None:
        raise tg.GraphError(f"{sid} lies on {lid}, which is not taught yet: record its passes first")
    x, y, yaw = pose
    # Of the passes of the tape near the pose (a leg can run both ways past one point, as
    # through the turnaround of a test straight), the one running the way the vehicle faces.
    hits = leg.line._candidates(x, y, None, None)
    best = min(h[2] for h in hits)
    near = [h for k, h in enumerate(hits) if h[2] <= best + tg.TIE_M
            and (k == 0 or h[2] <= hits[k - 1][2]) and (k == len(hits) - 1 or h[2] <= hits[k + 1][2])]

    def facing(h):
        return min(tg.heading_error(yaw, leg.line.point(h[0] + k)[2]) for k in (-0.05, 0.05))

    s, d, _dist = min(near, key=facing)
    if facing((s, d, 0)) > math.radians(30):
        raise tg.GraphError(f"{sid}: the vehicle faces {math.degrees(yaw):.0f} deg, the leg runs "
                            f"{math.degrees(leg.line.point(s)[2]):.0f} deg here - wrong direction for {lid}")
    return tg.Station(sid, lid, s, d, pose, taught, samples)


def mean_pose(poses):
    """Mean of standstill AMCL poses [(x, y, yaw)] (circular mean on yaw)."""
    if not poses:
        raise TeachError("no AMCL pose while standing")
    n = len(poses)
    return (sum(p[0] for p in poses) / n, sum(p[1] for p in poses) / n,
            math.atan2(sum(math.sin(p[2]) for p in poses), sum(math.cos(p[2]) for p in poses)))


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")
