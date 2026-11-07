"""Add one recorded lap of a new circuit to an existing tape graph, as a new revision.

Build makes a whole graph from the saved passes, so it would lose whatever the current graph holds
that no pass has: since 2026-11-06 the drawn right bay and HOME-N2. This takes one lap and adds only
the legs the graph lacks, plus that circuit's stops from the lap's marks. Every leg and station of the
base graph is kept as it is.

    python3 -m amr_line.tape_merge                     report only, nothing written
    python3 -m amr_line.tape_merge --publish           write g<N+1>; activate it on the Teach page

Failure modes, all refused before anything is written:
- the pass does not match the circuit's forks (tape_teach.split_pass)
- a fork was mistaken for another: a new leg does not meet the leg next to it (MAX_JOIN_GAP_M)
- the wrong number of marks for the circuit's stops, or a mark that does not lie on its leg
- any trip of any group stops compiling

The active pointer is never touched. Recovery: activate the previous revision, g<N> stays on disk.
"""

import argparse
import math
import os
import sys

from agv_core import mission as missions
from agv_core import paths

from amr_line import tape_graph as tg
from amr_line import tape_graph_store as store
from amr_line import tape_teach as tt
from amr_line import trip as tripmod
from amr_line import trip_route

MAX_JOIN_GAP_M = tt.ANCHOR_R_M
DEFAULT_CIRCUIT = "C-BTU"


class MergeError(ValueError):
    """The lap cannot be added: refused, with the reason."""


def new_legs(base, mission, circuit):
    return [leg for leg in mission["CIRCUITS"][circuit]["legs"] if leg["id"] not in base.legs]


def stops_needed(base, mission, circuit):
    """The stops on the circuit's new legs that the base graph has no position for, in tape order."""
    return [
        sid for leg in new_legs(base, mission, circuit) for sid in leg["stops"] if sid not in base.stations
    ]


def pick_marks(marks, rec, stops, explicit=None):
    """{stop id: mark id}. By default the marks made during the lap with no role yet, in the order they
    were made; `explicit` lists the mark ids instead, in stop order."""

    def number(mid):
        return int(mid[1:]) if mid[1:].isdigit() else 0

    if explicit is not None:
        unknown = [mid for mid in explicit if mid not in marks]
        if unknown:
            raise MergeError(f"no mark {', '.join(unknown)}")
        chosen = list(explicit)
    else:
        chosen = sorted(
            (
                mid
                for mid, mk in marks.items()
                if not mk.get("role") and mk.get("marked", "") >= rec.get("started", "")
            ),
            key=number,
        )
    if len(chosen) != len(stops):
        raise MergeError(
            f"{len(chosen)} mark(s) ({', '.join(chosen) or 'none'}) for {len(stops)} stop(s) "
            f"({', '.join(stops)}): name them with --stops, in stop order"
        )
    return dict(zip(stops, chosen, strict=True))


def _check_joins(graph, mission, circuit, added):
    legs = [graph.legs[leg["id"]] for leg in mission["CIRCUITS"][circuit]["legs"]]
    for a, b in zip(legs, legs[1:] + legs[:1], strict=True):
        if a.id not in added and b.id not in added:
            continue
        gap = math.dist(a.line.pts[-1], b.line.pts[0])
        if gap > MAX_JOIN_GAP_M:
            raise MergeError(
                f"{a.id} ends {gap:.2f} m from where {b.id} starts (> {MAX_JOIN_GAP_M} m): "
                f"a fork taken for another one, or AMCL off there. Name the junctions "
                f"with --anchor"
            )


def merge_lap(base, rec, mission, stop_poses, anchors=None):
    """Base graph + one pass + {stop id: pose} -> (new Graph, report lines). The base is not changed."""
    circuit = rec.get("circuit")
    if circuit not in mission["CIRCUITS"]:
        raise MergeError(f"pass {rec.get('started')}: circuit {circuit!r} is not in the mission")
    specs = new_legs(base, mission, circuit)
    if not specs:
        raise MergeError(f"the graph already has every leg of {circuit}")
    notes = []
    try:
        parts = tt.split_pass(rec, mission, notes, anchors)
    except tt.TeachError as e:
        raise MergeError(str(e)) from None
    report = [f"pass {rec.get('started')}: {n}" for n in notes]
    added = []
    for spec in specs:
        part = parts[spec["id"]]
        leg = tt.mean_leg(
            spec["id"],
            spec["from"],
            spec["order"],
            spec["to"],
            [part["pts"]],
            [part["fork_back"]],
            part["end_kind"],
        )
        added.append(leg)
        report.append(
            f"new leg {leg.id}: {leg.length:.2f} m, {leg.end_kind}, two tapes for "
            f"{leg.fork_back_m:.2f} m before its end"
        )
    why = (
        f"{circuit} added from pass {rec.get('started')} by tape_merge; every other leg and station as in "
        f"g{base.revision}"
    )
    was = base.notes if isinstance(base.notes, list) else ([base.notes] if base.notes else [])
    graph = tg.Graph(
        base.binding,
        list(base.legs.values()) + added,
        stations=base.stations.values(),
        mission=base.mission,
        notes=[*was, why],
    )
    _check_joins(graph, mission, circuit, {leg.id for leg in added})
    for sid in stops_needed(base, mission, circuit):
        if sid not in stop_poses:
            raise MergeError(f"no position for stop {sid}")
        try:
            st = tt.project_station(graph, mission, sid, stop_poses[sid], tt.now_iso(), 0)
            graph.put_station(st)
        except tg.GraphError as e:
            raise MergeError(str(e)) from None
        report.append(f"stop {sid}: {st.leg} at {st.s:.2f} m, {st.d * 100:+.1f} cm from the tape")
    return graph, report


def check_trips(graph, mission, areas=None):
    """Every one-machine trip of every group on this graph -> [(machine, why)] for those that fail."""
    bad = []
    for group, row in mission["GROUPS"].items():
        for machine in row["machines"]:
            try:
                trip_route.compile_trip(tripmod.Trip(mission, group, [machine]), mission, graph, areas=areas)
            except (tg.RouteError, tg.GraphError, ValueError) as e:
                bad.append((machine, str(e)))
    return bad


def _parse_anchors(rows):
    out = {}
    for row in rows or ():
        name, sep, xy = row.partition("=")
        x, comma, y = xy.partition(",")
        if not (sep and comma):
            raise MergeError(f"--anchor {row!r}: expected J-S=x,y")
        out[name] = [float(x), float(y)]
    return out


def run(args, out=print):
    """The command, without the argument parsing. Returns the new revision, or None for a report."""
    active = store.read_active(args.state_dir) or {}
    map_id = args.map or active.get("map_id")
    map_revision = args.map_revision if args.map_revision is not None else active.get("map_revision")
    base_revision = args.base if args.base is not None else active.get("graph_revision")
    if not map_id or map_revision is None or base_revision is None:
        raise MergeError("no active graph: say --map, --map-revision and --base")
    mission = missions.load_site(args.mission)
    base, _sha = store.load(args.maps_dir, map_id, base_revision)
    passes = [
        p
        for p in store.load_passes(args.state_dir, map_id, map_revision)
        if p.get("circuit") == args.circuit
        and (not args.pass_started or p.get("started") == args.pass_started)
    ]
    if not passes:
        raise MergeError(
            f"no saved {args.circuit} pass on {map_id} rev{map_revision}"
            + (f" started {args.pass_started}" if args.pass_started else "")
        )
    rec = max(passes, key=lambda p: p.get("started", ""))
    marks = store.load_marks(args.state_dir, map_id, map_revision)
    stops = stops_needed(base, mission, args.circuit)
    chosen = pick_marks(marks, rec, stops, args.stops.split(",") if args.stops else None)
    anchors = {**store.load_anchors(args.state_dir, map_id, map_revision), **_parse_anchors(args.anchor)}
    graph, report = merge_lap(
        base, rec, mission, {sid: marks[mid]["pose"] for sid, mid in chosen.items()}, anchors
    )
    for line in report:
        out(line)
    for sid, mid in chosen.items():
        out(f"{sid} = {mid}")
    areas = store.load_areas(args.state_dir, map_id, map_revision)
    bad = check_trips(graph, mission, areas)
    if bad:
        raise MergeError("; ".join(f"{machine}: {why}" for machine, why in bad))
    out(f"every trip of every group compiles on g{base_revision} + {args.circuit}")
    if not args.publish:
        out("report only: nothing written. --publish writes the new revision")
        return None
    n = store.publish(
        args.maps_dir, graph, summary=f"g{base_revision} + {args.circuit} lap {rec.get('started')}"
    )
    stations = store.load_stations(args.state_dir, map_id, map_revision)
    for sid, mid in chosen.items():
        st = graph.stations[sid]
        marks[mid].update(role=sid, leg=st.leg, s=round(st.s, 3))
        stations[sid] = {
            "id": sid,
            "pose": list(marks[mid]["pose"]),
            "taught": st.taught,
            "samples": 0,
            "mark": mid,
        }
    store.save_marks(args.state_dir, map_id, map_revision, marks)
    store.save_stations(args.state_dir, map_id, map_revision, stations)
    out(f"published {map_id} g{n}: Teach page, activate {n}, then restart amr.service. Not activated")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Add one recorded lap of a circuit to a tape graph, as a new revision."
    )
    ap.add_argument("--circuit", default=DEFAULT_CIRCUIT)
    ap.add_argument("--mission", default="site-103")
    ap.add_argument("--map", default="", help="map id (default: the active graph's)")
    ap.add_argument("--map-revision", type=int, default=None)
    ap.add_argument(
        "--base", type=int, default=None, help="graph revision to add to (default: the active one)"
    )
    ap.add_argument(
        "--pass", dest="pass_started", default="", help="the pass's start time (default: the newest)"
    )
    ap.add_argument(
        "--stops", default="", help="mark ids in stop order: M19,M20,... (default: the lap's own)"
    )
    ap.add_argument("--anchor", action="append", help="a junction's map position, J-S=x,y (repeatable)")
    ap.add_argument("--maps-dir", default=paths.maps_dir())
    ap.add_argument("--state-dir", default=paths.state_dir())
    ap.add_argument("--publish", action="store_true", help="write the new revision (default: report only)")
    args = ap.parse_args(argv)
    args.maps_dir = os.path.expanduser(args.maps_dir)
    args.state_dir = os.path.expanduser(args.state_dir)
    try:
        run(args)
    except (MergeError, store.StoreError, missions.MissionError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
