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
    zones      [(S_a, S_b, id, kind)]: HIGH or NORMAL+ where the route runs inside a speed AREA
               drawn on the map (site D19, 2026-10-25: areas, not point pairs; area_ranges()).
               kind "high" or "plus" (NORMAL+, 2026-11-11); where areas overlap the slower wins

Positions are vehicle data, so the checks that need them are here, not in the mission loader:
a U-turn point before its machine's release, a take-back stop before the U-turn point's return,
Each is a RouteError naming the station; the layer refuses the trip.
"""

import itertools
import math

from agv_core import config as vehicle

from amr_line import tape_graph as tg
from amr_line.tape_graph_store import AREA_KINDS

# A U-turn point must lie on the return leg this close (it is the same tape, the other way).
RETURN_MAX_LATERAL_M = 0.15
# An order needs this much tape between the previous node and its fork to be armed in.
MIN_ARM_M = 0.05
# A route is tested against the high-speed areas every AREA_STEP_M; a stretch inside one
# shorter than AREA_MIN_M (an area's corner clipping a curve) is no zone.
AREA_STEP_M = 0.05
AREA_MIN_M = 1.0
# Curved tape is never a speed zone, drawn area or not (2026-11-11: STR-TO-ATT began on the end of
# the bend after HOME-N2, HS-BOIAC-MRU on the BTU curve into J-ML; the AGV sped up while still
# turning and the curve guard took the zone away for good). Curvature is the drawn tape's heading
# change over CURVE_CHORD_M, against the curve guard's own limit (autopilot.curve_guard_kappa);
# CURVE_SETTLE_M after a curve the AGV is still straightening, so no zone yet either.
CURVE_CHORD_M = 0.5
CURVE_SETTLE_M = 1.0

_ids = itertools.count(1)


class TripRoute(tg.Route):
    """The locator's route (tape_graph.Route, legs cut at a mid-line U-turn) plus the trip's events.
    stops: [{"id", "S", "role", "work"}], HOME first and last."""

    def __init__(self, circuit, segments, stops, nodes, uturn, zones, events, notes, label):
        super().__init__(circuit, segments, stops, nodes)
        self.uturn = uturn                          # {"id", "mode", "direction", "S", ...} or None
        self.zones = zones                          # [(S_a, S_b, id)]
        self.events = events
        self.notes = notes
        self.label = label
        self.ident = f"{label}#{next(_ids)}"        # the locator must be on THIS route


def inside(poly, x, y):
    """Is (x, y) inside the polygon [[x, y], ...]? (even-odd ray test)"""
    hit, n = False, len(poly)
    for k in range(n):
        (x0, y0), (x1, y1) = poly[k], poly[(k + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _samples(segments, step):
    """[(S, x, y, heading)] along the route every `step`, contiguous across segments."""
    out = []
    for s0, leg, lo, hi in segments:
        n = max(1, int((hi - lo) / step))
        for k in range(n + 1):
            s = lo + (hi - lo) * k / n
            x, y, h = leg.line.point(s)
            out.append((s0 + s - lo, x, y, h))
    return out


def curved(samples, kappa_max, chord=CURVE_CHORD_M, settle=CURVE_SETTLE_M):
    """Per sample: on curved tape (heading change over `chord` above kappa_max, 1/m), or within
    `settle` after it. A mid-line U-turn's cut (the heading reverses) counts as a curve."""
    if not samples:
        return []
    n = len(samples)
    S = [p[0] for p in samples]
    bend = [False] * n
    lo = hi = 0
    for i in range(n):
        while S[i] - S[lo] > chord / 2:
            lo += 1
        while hi + 1 < n and S[hi + 1] - S[i] <= chord / 2:
            hi += 1
        span = S[hi] - S[lo]
        if span > 0:
            dh = abs((samples[hi][3] - samples[lo][3] + math.pi) % (2 * math.pi) - math.pi)
            bend[i] = dh / span > kappa_max
    out, last = [], None
    for i in range(n):
        if bend[i]:
            last = S[i]
        out.append(last is not None and S[i] - last < settle)
    return out


def area_ranges(segments, areas, step=AREA_STEP_M, min_len=AREA_MIN_M, kappa_max=None):
    """[(S_a, S_b, area id, kind)] where the route's segments [(S0, leg, lo, hi)] run inside the speed
    areas {id: {"polygon": [[x, y], ...], "kind": "high"|"plus"}} (kind defaults to "high"), sorted
    and contiguous across segments.

    Curved tape and the CURVE_SETTLE_M after it are outside every area (curved()); kappa_max
    defaults to the profile's curve guard limit. A stretch inside ANY area shorter than min_len (an
    area's corner clipping a curve) is no zone. Inside a stretch each sample takes the slowest kind
    among the areas holding it (ties: the first id), and every change of (kind, id) starts a new
    zone, whatever its length: the slower area always wins. Zones within one stretch touch end to
    start, so the engine never sees a gap there."""
    order = {k: n for n, k in enumerate(AREA_KINDS)}
    shapes = sorted((order[a.get("kind", "high")], aid, a["polygon"]) for aid, a in areas.items()
                    if a.get("kind", "high") in order)
    if not shapes:
        return []
    samples = _samples(segments, step)
    bent = curved(samples, vehicle.CURVE_GUARD_KAPPA if kappa_max is None else kappa_max)
    stretches, run = [], None                   # run: [(S, label)] of the stretch being followed
    for (S, x, y, _h), off in zip(samples, bent, strict=True):
        label = None if off else next(
            ((AREA_KINDS[rank], aid) for rank, aid, poly in shapes if inside(poly, x, y)), None)
        if label is not None:
            run = run if run is not None else []
            run.append((S, label))
        elif run is not None:
            stretches.append(run)
            run = None
    if run is not None:
        stretches.append(run)
    out = []
    for run in stretches:
        if run[-1][0] - run[0][0] < min_len:
            continue
        start, label = run[0]
        for S, lab in run[1:]:
            if lab != label:
                out.append((start, S, label[1], label[0]))
                start, label = S, lab
        out.append((start, run[-1][0], label[1], label[0]))
    return sorted(out)


def side_at(node, steers):
    """The side to arm before a junction node: its order at a diverge, the circuit's "steer" at a
    merge (mission site-4), "" for none (straight on, a crossing, an unsteered merge)."""
    if node["kind"] != "junction":
        return ""
    if node["order"] in ("left", "right"):
        return node["order"]
    return steers.get(f"{node['id']}:{node['order']}", "")


def decision_points(stops, nodes, junction_lead_m, steers=None, turns=(), check=True):
    """What the engine (site_run) acts on, sorted by S: a stop at each stop after the first, an
    order armed at S_fork - junction_lead_m but never before the previous node is passed, and the
    U-turn(s). `check`: refuse an order with no tape to arm it in (RouteError); the Shadow logs
    instead of refusing, so it passes False.

    A CHAIN: an order whose fork is closer than junction_lead_m to the previous node, when that node
    has an order too. Position cannot put it between the two forks (2026-11-07, J-N then J-S: 0.15 m
    of one tape between them), so the engine arms it when the previous order is taken by its fork:
    the earlier event says "then": this id, the later one "after": that id. `held`: the node's order
    is straight on, and the side only keeps the AGV off a tape leaving on the other side."""
    events = [{"kind": "stop", **s} for s in stops[1:]]
    prev_S = stops[0]["S"]
    prev_order = None                     # the previous node's order event, if it had one
    for n in nodes:
        side = side_at(n, steers or {})
        if side:
            arm = max(n["S_fork"] - junction_lead_m, prev_S)
            if check and arm > n["S_fork"] - MIN_ARM_M:
                raise tg.RouteError(f"{n['id']}: no tape to arm its order in between the previous node "
                                    f"and its fork ({n['S_fork'] - prev_S:.2f} m)")
            e = {"kind": "order", "id": n["id"], "order": side, "S": arm, "S_fork": n["S_fork"],
                 "S_node": n["S"], "S_prev": prev_S, "held": n["order"] == "straight"}
            if prev_order is not None and n["S_fork"] - junction_lead_m < prev_S:
                between = [s["id"] for s in stops[1:] if prev_S - 1e-6 <= s["S"] <= n["S_fork"]]
                between += [t["id"] for t in turns if prev_S - 1e-6 <= t["S"] <= n["S_fork"]]
                if between:
                    raise tg.RouteError(f"{n['id']}: chained to {prev_order['id']}, "
                                        f"{n['S_fork'] - prev_S:.2f} m after it, with "
                                        f"{', '.join(between)} between")
                prev_order["then"], e["after"] = n["id"], prev_order["id"]
            events.append(e)
            prev_order = e
        else:
            prev_order = None             # a plain node between: a fork the next order is not chained to
        prev_S = n["S"]
    events += [{"kind": "uturn", **t} for t in turns]
    events.sort(key=lambda e: e["S"])
    return events


def trigger_S(e, stop_distance_m):
    """Where the engine acts on event `e`: an order at its arm point, a tape-end U-turn its lead
    before the tape end, a stop (or a mid-line U-turn, which stops first) the stop distance before."""
    if e["kind"] == "order":
        return e["S"]
    if e["kind"] == "uturn" and e["mode"] == "tapeend":
        return e["S"] - e["lead_m"]
    return e["S"] - stop_distance_m


def _fits(seg, st):
    _s0, leg, lo, hi = seg
    return leg.id == st.leg and lo - 1e-6 <= st.s <= hi + 1e-6


def compile_trip(trip, mission, graph, junction_lead_m=1.0, areas=None):
    """A trip.Trip + its site mission + the active graph (+ the map revision's high-speed areas)
    -> TripRoute (RouteError when not drivable)."""
    circuit = mission["CIRCUITS"][trip.circuit]
    order = tg._circuit_order(trip.circuit, circuit, graph)
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
        nodes.append(tg._node(prev, leg, s0))

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
    events = decision_points(stops, nodes, junction_lead_m, circuit.get("steers", {}),
                             [turn] if turn is not None else [])

    # -- speed areas (HIGH, NORMAL+) ----------------------------------------------------------
    zones = area_ranges(segments, areas or {})
    notes = []
    label = f"{trip.group}:{'+'.join(trip.machines)}"
    return TripRoute(trip.circuit, segments, stops, nodes, turn, zones, events, notes, label)
