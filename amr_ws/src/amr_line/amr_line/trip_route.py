"""One trip laid out on ONE distance S (tracked plan 4, section 2.3). Pure: no ROS, no clock.

compile_trip(trip, mission, graph) -> TripRoute. The circuit's legs end to end, HOME to HOME
(as tape_graph.compile_route), but only what THIS trip drives:

    outbound   home leg -> ... -> the release leg, CUT at the trip's U-turn: the mid-line point
               of its farthest release (site D16), or the tape end when that machine has none
    inbound    the return leg ENTERED where the U-turn point projects onto it (the two
               directions of one tape are two legs), then -> ... -> home
    stops      the trip's own (trip.Trip.plan): HOME (start), ATT, its machines, HOME (end).
               A station of a machine not called need not be taught
    nodes      every leg boundary, in the locator's format (tape_locator.TapeLocator): the
               junctions it resyncs at, and the U-turn. A mid-line U-turn node is "mirror": the
               pivot leaves the AGV on the same floor point, now on the return leg
    events     what the engine (amr_line.site_run) acts on, sorted by S: stop, order (armed at
               S_fork - junction_lead_m, never before the previous node is passed), uturn
    zones      [(S_a, S_b, id)]: HIGH between two taught points (site D19)

Positions are vehicle data, so the checks that need them are here, not in the mission loader:
a U-turn point before its machine's release, a take-back stop before the U-turn point's return,
a zone end before its start. Each is a RouteError naming the station; the layer refuses the trip.
"""

import bisect
import itertools

from amr_line import tape_graph as tg

# A U-turn point must lie on the return leg this close (it is the same tape, the other way).
RETURN_MAX_LATERAL_M = 0.15
# An order needs this much tape between the previous node and its fork to be armed in.
MIN_ARM_M = 0.05

_ids = itertools.count(1)


class TripRoute:
    """The locator's route (same surface as tape_graph.Route) plus the trip's events."""

    def __init__(self, circuit, segments, stops, nodes, uturn, zones, events, notes, label):
        self.circuit = circuit
        self.segments = segments                    # [(S0, leg, lo, hi)]: S = S0 + (s - lo)
        self._starts = [seg[0] for seg in segments]
        self.stops = stops                          # [{"id", "S", "role", "work"}], HOME first and last
        self.nodes = nodes
        self.uturn = uturn                          # {"id", "mode", "direction", "S", ...} or None
        self.zones = zones                          # [(S_a, S_b, id)]
        self.events = events
        self.notes = notes
        self.label = label
        self.ident = f"{label}#{next(_ids)}"        # the locator must be on THIS route
        self.S_start = stops[0]["S"]
        self.S_end = stops[-1]["S"]

    @property
    def length(self):
        s0, _leg, lo, hi = self.segments[-1]
        return s0 + hi - lo

    def at(self, S):
        """(index, leg, s on the leg) of the segment holding S (clamped to the route)."""
        i = min(max(bisect.bisect_right(self._starts, S) - 1, 0), len(self.segments) - 1)
        s0, leg, lo, hi = self.segments[i]
        return i, leg, min(max(lo + S - s0, lo), hi)

    def point(self, S):
        _, leg, s = self.at(S)
        return leg.line.point(s)

    def project(self, x, y, S_lo, S_hi, hint=None):
        """Nearest route point with S in [S_lo, S_hi] -> (S, d) or None (tape_graph.Route.project)."""
        hits = []
        for s0, leg, lo, hi in self.segments:
            if s0 > S_hi or s0 + hi - lo < S_lo:
                continue
            a, b = max(lo, lo + S_lo - s0), min(hi, lo + S_hi - s0)
            hits += [(s0 + s - lo, d, dist) for s, d, dist in leg.line._candidates(x, y, a, b)]
        return tg._pick(hits, hint)

    def stop(self, ident):
        return next((s for s in self.stops if s["id"] == ident), None)

    def where(self, S):
        """'<leg> at <s> m' for messages."""
        _, leg, s = self.at(S)
        return f"{leg.id} at {s:.2f} m"


def _fits(seg, st):
    _s0, leg, lo, hi = seg
    return leg.id == st.leg and lo - 1e-6 <= st.s <= hi + 1e-6


def compile_trip(trip, mission, graph, junction_lead_m=1.0):
    """A trip.Trip + its site mission + the active graph -> TripRoute (RouteError when not drivable)."""
    circuit = mission["CIRCUITS"][trip.circuit]
    specs = circuit["legs"]                         # home leg last
    order = [specs[-1]] + specs[:-1] + [specs[-1]]
    missing = sorted({leg["id"] for leg in specs if leg["id"] not in graph.legs})
    if missing:
        raise tg.RouteError(f"{trip.circuit} not taught: {', '.join(missing)}")
    plan = [{"id": mission["HOME"], "role": "start", "work": []}] + [dict(p) for p in trip.plan]
    untaught = [p["id"] for p in plan if p["id"] not in graph.stations]
    u = trip.uturn()
    if u is not None and u["mode"] == "midline" and u["id"] not in graph.stations:
        untaught.append(f"U-turn point {u['id']}")
    if untaught:
        raise tg.RouteError(f"trip {trip.describe()}: not taught: {', '.join(dict.fromkeys(untaught))}")

    # -- the cut at a mid-line U-turn ---------------------------------------------------
    cut = None                                     # (index in order, s on the out leg, s on the return leg)
    if u is not None and u["mode"] == "midline":
        st = graph.stations[u["id"]]
        want = mission["POINTS"].get(u["id"])
        k = next((k for k in range(1, len(order) - 1) if order[k]["id"] == st.leg), None)
        if st.leg != want or k is None or order[k + 1]["from"] != order[k]["to"] \
                or mission["UTURNS"].get(order[k]["to"]) is None:
            raise tg.RouteError(f"U-turn point {u['id']} is taught on {st.leg}; it belongs on {want}, "
                                f"the leg into the tape-end U-turn")
        back = graph.legs[order[k + 1]["id"]]
        out_len = graph.legs[st.leg].length
        hit = back.line.project(st.pose[0], st.pose[1], hint=out_len - st.s)   # it starts at the tape end
        if hit is None or abs(hit[1]) > RETURN_MAX_LATERAL_M:
            raise tg.RouteError(f"U-turn point {u['id']} does not lie on the return leg {back.id} "
                                f"(within {RETURN_MAX_LATERAL_M} m)")
        far = trip.m["GROUPS"][trip.group]["machines"][trip.farthest]["release"]
        rel = graph.stations[far]
        if rel.leg == st.leg and rel.s >= st.s:
            raise tg.RouteError(f"U-turn point {u['id']} is taught before {trip.farthest}'s release "
                                f"{far} ({st.s:.2f} m, the release at {rel.s:.2f} m): the AGV never "
                                f"pivots with a trolley attached")
        cut = (k, st.s, hit[0])

    segments, S0 = [], 0.0
    for k, spec in enumerate(order):
        leg = graph.legs[spec["id"]]
        lo, hi = 0.0, leg.length
        if cut is not None and k == cut[0]:
            hi = cut[1]
        elif cut is not None and k == cut[0] + 1:
            lo = cut[2]
        segments.append((S0, leg, lo, hi))
        S0 += hi - lo

    # -- stops, in plan order, each on the first segment at or after the last one ------------
    stops, k = [], 0
    for p in plan:
        st = graph.stations[p["id"]]
        last = len(segments) - 1 if p["role"] == "home" else None
        found = None
        for j in ([last] if last is not None else range(k, len(segments))):
            if _fits(segments[j], st):
                S = segments[j][0] + st.s - segments[j][2]
                if not stops or S >= stops[-1]["S"] - 1e-6:
                    found = (j, S)
                    break
        if found is None:
            where = f"{st.leg} at {st.s:.2f} m"
            raise tg.RouteError(f"station {p['id']} ({where}) is not on trip {trip.describe()} after "
                                f"{stops[-1]['id'] if stops else 'the start'}"
                                + (" - it lies before the U-turn point's return" if cut is not None else ""))
        k = found[0]
        stops.append({"id": p["id"], "S": found[1], "role": p["role"], "work": p["work"]})

    # -- nodes ------------------------------------------------------------------------------
    nodes = []
    for k in range(1, len(segments)):
        s0, leg, _lo, _hi = segments[k]
        _p0, prev, _plo, _phi = segments[k - 1]
        if cut is not None and k == cut[0] + 1:
            nodes.append({"id": u["id"], "kind": "uturn", "order": "pivot", "S": s0, "S_fork": s0,
                          "sigma": tg.MIN_END_SPREAD_M, "leg_in": prev.id, "leg_out": leg.id,
                          "fork": False, "mirror": True})
            continue
        kind = "uturn" if prev.end_kind == "uturn" else "junction"
        nodes.append({"id": leg.frm, "kind": kind, "order": leg.order, "S": s0,
                      "S_fork": s0 - prev.fork_back_m if prev.end_kind == "fork" else s0,
                      "sigma": max(prev.end_spread_m, tg.MIN_END_SPREAD_M), "leg_in": prev.id,
                      "leg_out": leg.id, "fork": prev.end_kind == "fork"})

    # -- the U-turn -------------------------------------------------------------------------
    turn = None
    if u is not None:
        node = next((n for n in nodes if n["kind"] == "uturn"), None)
        if node is None:
            raise tg.RouteError(f"trip {trip.describe()}: the route has no U-turn node")
        turn = dict(u, S=node["S"])
        if u["mode"] == "tapeend":
            turn.update(mission["UTURNS"][u["id"]])

    # -- events -----------------------------------------------------------------------------
    events = [{"kind": "stop", **s} for s in stops[1:]]
    prev_S = stops[0]["S"]
    for n in nodes:
        if n["kind"] == "junction" and n["order"] in ("left", "right"):
            arm = max(n["S_fork"] - junction_lead_m, prev_S)
            if arm > n["S_fork"] - MIN_ARM_M:
                raise tg.RouteError(f"{n['id']}: no tape to arm its order in between the previous node "
                                    f"and its fork ({n['S_fork'] - prev_S:.2f} m)")
            events.append({"kind": "order", "id": n["id"], "order": n["order"], "S": arm,
                           "S_fork": n["S_fork"], "S_node": n["S"]})
        prev_S = n["S"]
    if turn is not None:
        events.append({"kind": "uturn", **turn})
    events.sort(key=lambda e: e["S"])

    # -- zones ------------------------------------------------------------------------------
    zones, notes = [], []
    for zid, z in mission["ZONES"].items():
        ends = [graph.stations.get(z["from"]), graph.stations.get(z["to"])]
        if None in ends:
            gone = [p for p, st in zip((z["from"], z["to"]), ends, strict=True) if st is None]
            notes.append(f"zone {zid}: {', '.join(gone)} not taught - NORMAL there")
            continue
        at = [[seg[0] + st.s - seg[2] for seg in segments if _fits(seg, st)] for st in ends]
        if not at[0] and not at[1]:
            continue                                # another circuit's zone
        pairs = []
        for a in at[0]:
            b = min((b for b in at[1] if b > a), default=None)
            if b is not None and not any(a < a2 < b for a2 in at[0]):
                pairs.append((a, b, zid))
        if not pairs:
            if at[0] and at[1]:
                raise tg.RouteError(f"zone {zid}: its end {z['to']} is not after its start {z['from']} "
                                    f"on trip {trip.describe()}")
            notes.append(f"zone {zid}: one end is beyond this trip's U-turn - NORMAL there")
            continue
        zones += pairs
    zones.sort()
    label = f"{trip.group}:{'+'.join(trip.machines)}"
    return TripRoute(trip.circuit, segments, stops, nodes, turn, zones, events, notes, label)
