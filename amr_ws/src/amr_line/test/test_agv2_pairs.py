"""AGV 2's pairs, the job's side (contract v1.6 section 2a, amended 2026-11-25, owner): check 5 takes a ROW3
or STU7-10 pair closer first and refuses a reversed or mixed one; the trip and its route on AGV 2's taught
graph (rev-boiacca-map-01 g3), with the CLUSTER box of section 13.1: a pair makes the same two crossings as a
single trip, and an STU pair U-turns at the farther machine's own point, after its release.

The route tests read the vehicle's graph store (not in the repo) and skip where it is not installed."""

import json
import os
from types import SimpleNamespace

import pytest
from agv_core import mission

from amr_line import job as lj
from amr_line import order as om
from amr_line import tape_graph_store as store
from amr_line import trip as tripmod
from amr_line import trip_route

with open(os.path.join(mission.MISSION_DIR, "site-103-agv2.json")) as fh:
    SITE = mission.parse_site(json.load(fh))

MAP_ID, GRAPH_REV = "rev-boiacca-map-01", 3
MAPS = os.environ.get("AMR_MAPS_DIR") or os.path.expanduser("~/amr_maps")
CLUSTER = {"CLUSTER": [(-13.6, -3.3), (-5.0, -3.3), (-5.0, 2.2), (-13.6, 2.2)]}   # contract 13.1


def recs(key):
    """check 5 (job._order_recs) on AGV 2's site: the machine records, or None (VALIDATION_FAILURE
    MACHINE)."""
    stub = SimpleNamespace(site=SITE)
    stub._order_machine = lambda mc: lj.FollowJob._order_machine(stub, mc)
    return lj.FollowJob._order_recs(stub, om.OrderRequest(order_id=f"{key}-1", machine=key))


@pytest.mark.parametrize("key", ["BTU5+BTU2", "BTU8+BTU1", "STU6+STU1", "STU7+STU10", "STU8+STU9"])
def test_check_5_takes_an_agv2_pair_closer_first(key):
    assert recs(key) is not None


@pytest.mark.parametrize("key", ["BTU2+BTU5", "STU10+STU7", "BTU5+STU7", "STU6+STU7", "STU7+STU7"])
def test_check_5_refuses_a_reversed_or_mixed_agv2_pair(key):
    assert recs(key) is None


def test_an_stu_pair_turns_at_the_farther_machines_point():
    t = tripmod.Trip(SITE, "STU", ["STU7", "STU10"])
    assert t.uturn() == {"id": "UT-STU10", "mode": "midline", "direction": "ccw"}


def _graph():
    try:
        g, _sha = store.load(MAPS, MAP_ID, GRAPH_REV)
    except (OSError, store.StoreError) as e:
        pytest.skip(f"AGV 2's graph {MAP_ID} g{GRAPH_REV} is not installed here ({e})")
    return g


def route(group, names):
    return trip_route.compile_trip(tripmod.Trip(SITE, group, names), SITE, _graph(), release=CLUSTER)


@pytest.mark.parametrize("names, stops", [
    (["BTU5", "BTU2"], ["R3-6", "R3-12"]),
    (["BTU8", "BTU1"], ["R3-1", "R3-14"]),
    (["STU7", "STU10"], ["SW-7", "SW-10", "SE-10", "SE-7"]),
    (["STU8", "STU9"], ["SW-8", "SW-9", "SE-9", "SE-8"]),
])
def test_an_agv2_pair_compiles_on_g3_with_the_two_cluster_crossings(names, stops):
    group = "ROW3" if names[0].startswith("BTU") else "STU"
    r = route(group, names)
    ids = [s["id"] for s in r.stops]
    assert ids == ["HOME-N", "ATT", *stops, "HOME-N"]
    S = [s["S"] for s in r.stops]
    assert S == sorted(S)
    out, home = r.release_zones                       # exactly two crossings, as a single trip (13.2)
    assert (out["zone"], out["ask_at"], out["home"]) == ("CLUSTER", "ATT", False)
    assert (home["zone"], home["ask_at"], home["home"]) == ("CLUSTER", None, True)
    assert home["S_in"] - home["S_ask"] == pytest.approx(10.0)
    assert out["S_out"] < r.stops[2]["S"] and home["S_ask"] > r.stops[-2]["S"]   # the pair's stops are clear
    if group == "STU":
        far_release, far_take = r.stops[3]["S"], r.stops[4]["S"]
        assert far_release < r.uturn["S"] < far_take, "the U-turn comes after the far release"


def test_a_pair_route_crosses_cluster_where_the_single_trip_does():
    single, pair = route("ROW3", ["BTU2"]), route("ROW3", ["BTU5", "BTU2"])
    key = lambda r: [(z["S_in"], z["S_out"], z["home"]) for z in r.release_zones]  # noqa: E731
    assert key(pair) == key(single)
