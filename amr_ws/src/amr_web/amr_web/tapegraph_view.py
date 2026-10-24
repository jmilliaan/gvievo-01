"""The tape graph for the map overlay (2026-10-24): files only, no ROS, read-only.

What the LINE layer teaches lives on disk (amr_line.tape_graph_store): the selection pointer
<state_dir>/line_graph.json, published graphs under <maps_dir>/<map>/tapegraph/g<N>/, and the
teach workspace <state_dir>/teach/<map>-rev<R>/ (passes, anchors, stations, marks). This
gathers what a map view draws: the active graph's legs and stations, or - before a graph is
published - the newest recorded pass; the junction anchors; the marks.
"""
from __future__ import annotations

import json
import math
import os
import re

PLAIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
STEP_M = 0.20       # leg and pass points thinned to this spacing for drawing


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _thin(pts, step=STEP_M):
    out = []
    for p in pts:
        if not out or math.dist(out[-1], p[:2]) >= step:
            out.append([round(p[0], 3), round(p[1], 3)])
    if pts and out[-1] != [round(pts[-1][0], 3), round(pts[-1][1], 3)]:
        out.append([round(pts[-1][0], 3), round(pts[-1][1], 3)])
    return out


def view(state_dir, maps_dir):
    """{available, map_id, map_revision, graph_revision, legs, pass, anchors, stations, marks}."""
    sel = _read(os.path.join(state_dir, "line_graph.json")) or {}
    map_id, rev = sel.get("map_id"), sel.get("map_revision")
    if not isinstance(map_id, str) or not PLAIN.match(map_id) or not isinstance(rev, int):
        return {"available": False, "why": "no teaching map selected"}
    out = {"available": True, "map_id": map_id, "map_revision": rev, "graph_revision": None,
           "legs": [], "pass": None, "anchors": [], "stations": [], "marks": []}
    g = sel.get("graph_revision")
    if isinstance(g, int):
        doc = _read(os.path.join(maps_dir, map_id, "tapegraph", f"g{g}", "graph.json")) or {}
        out["graph_revision"] = g
        out["legs"] = [{"id": leg["id"], "pts": _thin(leg["points"])} for leg in doc.get("legs", [])
                       if isinstance(leg, dict) and leg.get("points")]
        out["stations"] = [{"id": st["id"], "x": st["pose"][0], "y": st["pose"][1], "leg": st.get("leg")}
                           for st in doc.get("stations", []) if isinstance(st, dict) and st.get("pose")]
    teach = os.path.join(state_dir, "teach", f"{map_id}-rev{rev}")
    if not out["legs"]:
        pdir = os.path.join(teach, "passes")
        try:
            names = sorted(f for f in os.listdir(pdir) if f.endswith(".json"))
        except OSError:
            names = []
        if names:
            rec = _read(os.path.join(pdir, names[-1])) or {}
            pts = [p[1:] for p in sorted(rec.get("samples", []))]
            out["pass"] = {"name": names[-1][:-5], "pts": _thin(pts)}
    if not out["stations"]:
        taught = _read(os.path.join(teach, "stations.json")) or {}
        out["stations"] = [{"id": k, "x": v["pose"][0], "y": v["pose"][1], "leg": None}
                           for k, v in taught.items() if isinstance(v, dict) and v.get("pose")]
    anchors = _read(os.path.join(teach, "anchors.json")) or {}
    out["anchors"] = [{"id": k, "x": v[0], "y": v[1]} for k, v in anchors.items()
                      if isinstance(v, list) and len(v) == 2]
    marks = _read(os.path.join(teach, "marks.json")) or {}
    out["marks"] = [{"id": k, "x": v["pose"][0], "y": v["pose"][1],
                     "label": v.get("role") or v.get("label", ""), "leg": v.get("leg"), "s": v.get("s")}
                    for k, v in marks.items() if isinstance(v, dict) and v.get("pose")]
    return out
