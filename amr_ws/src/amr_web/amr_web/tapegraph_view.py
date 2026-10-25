"""The tape graph for the map overlay (2026-10-24): files only, no ROS, read-only.

What the LINE layer teaches lives on disk (amr_line.tape_graph_store): the selection pointer
<state_dir>/line_graph.json, published graphs under <maps_dir>/<map>/tapegraph/g<N>/, and the
teach workspace <state_dir>/teach/<map>-rev<R>/ (passes, anchors, stations, marks). This
gathers what a map view draws: the active graph's legs and stations, or - before a graph is
published - the newest recorded pass; the junction anchors; the marks; the high-speed areas.

The areas (tracked plan 4, 2026-10-25) are the one thing written here: polygons drawn on the
map, <teach>/areas.json, in the format amr_line.tape_graph_store.load_areas reads. A trip
compiles them into HIGH ranges along its route at Start; nothing here moves anything.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile

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


# An area: 3..64 corners, at least AREA_MIN_M2 square metres, inside +-AREA_MAX_ABS_M of the origin.
AREA_MAX_POINTS = 64
AREA_MIN_M2 = 0.5
AREA_MAX_ABS_M = 10000.0


def _selection(state_dir):
    sel = _read(os.path.join(state_dir, "line_graph.json")) or {}
    map_id, rev = sel.get("map_id"), sel.get("map_revision")
    if not isinstance(map_id, str) or not PLAIN.match(map_id) or not isinstance(rev, int):
        return None
    return sel


def _teach_dir(state_dir, sel):
    return os.path.join(state_dir, "teach", f"{sel['map_id']}-rev{sel['map_revision']}")


def check_polygon(pts):
    """[(x, y)] or a reason it is not an area."""
    if not isinstance(pts, list) or not 3 <= len(pts) <= AREA_MAX_POINTS:
        return None, f"an area needs 3 to {AREA_MAX_POINTS} corners"
    out = []
    for p in pts:
        if not (isinstance(p, list) and len(p) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)):
            return None, "each corner is [x, y] in metres"
        x, y = float(p[0]), float(p[1])
        if not (math.isfinite(x) and math.isfinite(y)) or max(abs(x), abs(y)) > AREA_MAX_ABS_M:
            return None, "a corner is not a map coordinate"
        out.append((x, y))
    a = 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(out, out[1:] + out[:1], strict=True)))
    if a < AREA_MIN_M2:
        return None, f"the area is {a:.2f} m², less than {AREA_MIN_M2} m²"
    return out, ""


def save_area(state_dir, ident, polygon):
    """Write (polygon) or delete (None) one high-speed area of the selected map revision.
    -> (ok, message)."""
    sel = _selection(state_dir)
    if sel is None:
        return False, "no teaching map selected (Teach page: Select map)"
    if not isinstance(ident, str) or not PLAIN.match(ident) or len(ident) > 32:
        return False, "an area id is a plain name (letters, digits, _ . -), at most 32"
    d = _teach_dir(state_dir, sel)
    path = os.path.join(d, "areas.json")
    doc = _read(path)
    doc = doc if isinstance(doc, dict) else {}
    where = f"{sel['map_id']} rev{sel['map_revision']}"
    if polygon is None:
        if doc.pop(ident, None) is None:
            return False, f"no area {ident} on {where}"
        msg = f"area {ident} deleted from {where}"
    else:
        pts, why = check_polygon(polygon)
        if pts is None:
            return False, why
        doc[ident] = {"polygon": [[round(x, 3), round(y, 3)] for x, y in pts], "kind": "high"}
        msg = f"area {ident} saved on {where} ({len(pts)} corners): HIGH there from the next trip on"
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".areas.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)
    return True, msg


def view(state_dir, maps_dir):
    """{available, map_id, map_revision, graph_revision, legs, pass, anchors, stations, marks, areas}."""
    sel = _read(os.path.join(state_dir, "line_graph.json")) or {}
    map_id, rev = sel.get("map_id"), sel.get("map_revision")
    if not isinstance(map_id, str) or not PLAIN.match(map_id) or not isinstance(rev, int):
        return {"available": False, "why": "no teaching map selected"}
    out = {"available": True, "map_id": map_id, "map_revision": rev, "graph_revision": None,
           "legs": [], "pass": None, "anchors": [], "stations": [], "marks": [], "areas": []}
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
    areas = _read(os.path.join(teach, "areas.json")) or {}
    out["areas"] = [{"id": k, "polygon": v["polygon"]} for k, v in sorted(areas.items())
                    if isinstance(v, dict) and isinstance(v.get("polygon"), list)]
    return out
