"""A site-4 test circuit with its graph taught exactly (tracked plan 4 tests).

The C-M circuit of test_tape_localization (HOME on the home leg, ATT, J-B right onto the
machine line, the tape end U, back past the machines, J-C left home), plus two mid-line
U-turn points and a high-speed zone on the machine line:

    J-C:left>J-A   (0,0)->(10,0)      HOME at 5
    J-A:merge>J-B  (10,0)->(10,10)    ATT at 3
    J-B:right>U    (10,10)->(30,10)   MW-1 at 8 (x 18), UT-M1 at 11, MW-2 at 14 (x 24), UT-M2 at 17
    U:pivot>J-C    (30,10)->(0,10)->(0,0)   ME-2 at 6 (x 24), ME-1 at 12 (x 18)
    zone Z-LINE    ZA at x 11, ZB at x 17 on the way out (J-B:right>U at 1 and 7)
"""
import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agv_core import mission as missions  # noqa: E402

from amr_line import tape_graph as tg  # noqa: E402
from amr_line import tape_teach as tt  # noqa: E402

DOC = {
    "schema": "site-4", "mission_name": "t", "home": "HOME", "attach": "ATT", "trip_calls": 2,
    "stop_distance_m": 0.5, "cruise_mps": 0.4,
    "junctions": {"J-A": {"shape": "Y", "laid": True}, "J-B": {"shape": "Y", "laid": True},
                  "J-C": {"shape": "Y", "laid": True}},
    "uturns": {"U": {"direction": "cw", "approach_mps": 0.1, "decel_m": 0.3, "max_approach_m": 2.0,
                     "lead_m": 1.5}},
    "circuits": {"C-M": [{"stop": "HOME"}, {"junction": "J-A", "order": "merge"}, {"stop": "ATT"},
                         {"junction": "J-B", "order": "right"}, {"stop": "MW-1"}, {"stop": "MW-2"},
                         {"uturn": "U"}, {"stop": "ME-2"}, {"stop": "ME-1"},
                         {"junction": "J-C", "order": "left"}, {"stop": "HOME"}]},
    "groups": {"M": {"circuit": "C-M", "machines": {
        "M1": {"release": "MW-1", "take": "ME-1", "uturn": "UT-M1"},
        "M2": {"release": "MW-2", "take": "ME-2", "uturn": "UT-M2"}}}},
    "uturn_points": {"UT-M1": {"direction": "cw"}, "UT-M2": {"direction": "cw"}},
    "zones": {"Z-LINE": {"from": "ZA", "to": "ZB"}},
}
BINDING = {"map_id": "t", "map_revision": 1, "map_sha256": "ab" * 32}
TRUE = {
    "J-C:left>J-A": [(0, 0), (10, 0)],
    "J-A:merge>J-B": [(10, 0), (10, 10)],
    "J-B:right>U": [(10, 10), (30, 10)],
    "U:pivot>J-C": [(30, 10), (0, 10), (0, 0)],
}
END = {"J-C:left>J-A": "fork", "J-A:merge>J-B": "fork", "J-B:right>U": "uturn", "U:pivot>J-C": "fork"}
FORK_BACK_M = 0.4
TAUGHT = {"HOME": ("J-C:left>J-A", 5.0), "ATT": ("J-A:merge>J-B", 3.0), "MW-1": ("J-B:right>U", 8.0),
          "MW-2": ("J-B:right>U", 14.0), "ME-2": ("U:pivot>J-C", 6.0), "ME-1": ("U:pivot>J-C", 12.0),
          "UT-M1": ("J-B:right>U", 11.0), "UT-M2": ("J-B:right>U", 17.0),
          "ZA": ("J-B:right>U", 1.0), "ZB": ("J-B:right>U", 7.0)}


def site(**over):
    d = copy.deepcopy(DOC)
    d.update(over)
    return missions.parse_site(d)


def graph(m, skip=()):
    legs = []
    for lid, pts in TRUE.items():
        frm, rest = lid.split(":")
        order, to = rest.split(">")
        legs.append(tg.Leg(lid, frm, order, to, tg.resample(pts), end_kind=END[lid],
                           fork_back_m=FORK_BACK_M if END[lid] == "fork" else 0.0))
    g = tg.Graph(BINDING, legs)
    for sid, (lid, s) in TAUGHT.items():
        if sid in skip:
            continue
        x, y, h = g.legs[lid].line.point(s)
        g.put_station(tt.project_station(g, m, sid, (x, y, h)))
    return g
