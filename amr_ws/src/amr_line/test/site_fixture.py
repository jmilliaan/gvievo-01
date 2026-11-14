"""A site-4 test circuit with its graph taught exactly (tracked plan 4 tests).

The C-M circuit of test_tape_localization (HOME on the home leg, ATT, J-B right onto the
machine line, the tape end U, back past the machines, J-C left home), plus two mid-line
U-turn points, and a high-speed area over the machine line (both directions of its tape):

    J-C:left>J-A   (0,0)->(10,0)      HOME at 5
    J-A:merge>J-B  (10,0)->(10,10)    ATT at 3
    J-B:right>U    (10,10)->(30,10)   MW-1 at 8 (x 18), UT-M1 at 11, MW-2 at 14 (x 24), UT-M2 at 17
    U:pivot>J-C    (30,10)->(0,10)->(0,0)   ME-2 at 6 (x 24), ME-1 at 12 (x 18)
    area Z-LINE    x 11..17 around y 10: J-B:right>U 1..7, and U:pivot>J-C 13..19 on the way back
"""
import copy

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
}
AREAS = {"Z-LINE": {"polygon": [(10.98, 9.0), (17.02, 9.0), (17.02, 11.0), (10.98, 11.0)], "kind": "high"}}
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
          "UT-M1": ("J-B:right>U", 11.0), "UT-M2": ("J-B:right>U", 17.0)}


# Swap machines, a BTU lap in small (contract v1.3, 2026-11-13): circuit C-S leaves J-B LEFT onto a loop
# with no U-turn and comes home through J-C. S2 swaps at R-1 (the closer, as BTU24 at R2-1), S1 at R-2;
# S9 shares R-1 and is listed after S2, as BTU16 shares R2-1 with BTU24.
#     J-B:left>J-C   (10,10)->(10,20)->(0,20)->(0,0)   R-1 at 12 (x 8), R-2 at 18 (x 2)
SWAP_TRUE = {"J-B:left>J-C": [(10, 10), (10, 20), (0, 20), (0, 0)]}
SWAP_TAUGHT = {"R-1": ("J-B:left>J-C", 12.0), "R-2": ("J-B:left>J-C", 18.0)}


def site(**over):
    d = copy.deepcopy(DOC)
    d.update(over)
    return missions.parse_site(d)


def swap_site(**over):
    """DOC plus circuit C-S and group S (swap machines S2, S1, S9)."""
    d = copy.deepcopy(DOC)
    d["circuits"]["C-S"] = [{"stop": "HOME"}, {"junction": "J-A", "order": "merge"}, {"stop": "ATT"},
                            {"junction": "J-B", "order": "left"}, {"stop": "R-1"}, {"stop": "R-2"},
                            {"junction": "J-C", "order": "left"}, {"stop": "HOME"}]
    d["groups"]["S"] = {"circuit": "C-S", "machines": {"S2": {"swap": "R-1"}, "S1": {"swap": "R-2"},
                                                      "S9": {"swap": "R-1"}}}
    d.update(over)
    return missions.parse_site(d)


def swap_graph(m):
    return graph(m, true={**TRUE, **SWAP_TRUE}, taught={**TAUGHT, **SWAP_TAUGHT})


def graph(m, skip=(), true=None, taught=None):
    legs = []
    for lid, pts in (true or TRUE).items():
        frm, rest = lid.split(":")
        order, to = rest.split(">")
        end = END.get(lid, "fork")
        legs.append(tg.Leg(lid, frm, order, to, tg.resample(pts), end_kind=end,
                           fork_back_m=FORK_BACK_M if end == "fork" else 0.0))
    g = tg.Graph(BINDING, legs)
    for sid, (lid, s) in (taught or TAUGHT).items():
        if sid in skip:
            continue
        x, y, h = g.legs[lid].line.point(s)
        g.put_station(tt.project_station(g, m, sid, (x, y, h)))
    return g
