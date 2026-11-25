"""AGV 2's pairs, the bridge's side (contract v1.6 section 2a, amended 2026-11-25, owner): ROW3 with ROW3 in
the two-stop BTU shape, STU7-10 with STU7-10 in the MRU pair shape, closer first. The site mission's
trip_calls 1 governs screen calls only: a station pair is taken by its shape."""

import json
import os

import pytest
from agv_core import mission
from test_vda_order import SEEN, ring

from amr_station import vda_order as vo

with open(os.path.join(mission.MISSION_DIR, "site-103-agv2.json")) as fh:
    SITE = mission.parse_site(json.load(fh))

# key -> the waits' node ids after ATT, in sequence order
PAIRS = {
    "BTU5+BTU2": ["R3-6", "R3-12"],
    "BTU8+BTU1": ["R3-1", "R3-14"],
    "STU7+STU10": ["SW-7", "SW-10", "SE-10", "SE-7"],
    "STU8+STU9": ["SW-8", "SW-9", "SE-9", "SE-8"],
}


def order(key, order_id=None):
    order_id = order_id or f"{key}-20261125T101500"
    return {
        "headerId": 12,
        "timestamp": "2026-11-25T03:15:00.000Z",
        "version": "3.0.0",
        "manufacturer": "gvi",
        "serialNumber": "agv2",
        "orderId": order_id,
        "orderUpdateId": 0,
        "seenStateHeaderId": SEEN,
        **vo.canonical_order(SITE, key, order_id),
    }


def check(doc):
    return vo.check_order(json.dumps(doc).encode(), False, manufacturer="gvi", serial="agv2", site=SITE,
                          state_order_id="", state_machine="", ring=ring(), now=100.0)


def test_agv2_keeps_trip_calls_1_for_screen_calls():
    assert SITE["TRIP_CALLS"] == 1


@pytest.mark.parametrize("key", sorted(PAIRS))
def test_an_agv2_pair_has_the_contract_shape_and_is_accepted(key):
    assert vo.valid_key(SITE, key)
    doc = order(key)
    oid = doc["orderId"]
    ids = [n["nodeId"] for n in doc["nodes"]]
    assert ids == ["HOME-N", "ATT", *PAIRS[key], "HOME-N"]
    assert [n["sequenceId"] for n in doc["nodes"]] == list(range(0, 2 * len(ids), 2))
    assert doc["nodes"][-1]["sequenceId"] == (8 if key.startswith("BTU") else 12)   # home lastNodeSequenceId
    # node-named action ids, no `machines` parameter (ROW3: every machine has its own stop)
    assert [[a["actionId"] for a in n["actions"]] for n in doc["nodes"][1:-1]] == \
        [[f"{oid}:{nid}"] for nid in ["ATT", *PAIRS[key]]]
    params = [p for n in doc["nodes"] for a in n["actions"] for p in a["actionParameters"]]
    assert all(p["key"] != "machines" for p in params)
    r = check(doc)
    assert (r.outcome, r.machine) == (vo.ACCEPT, key), r


@pytest.mark.parametrize("key", ["BTU2+BTU5", "BTU1+BTU8", "STU10+STU7", "STU9+STU8"])
def test_a_reversed_agv2_pair_is_no_valid_key(key):
    assert not vo.valid_key(SITE, key)


def test_a_reversed_row3_pair_order_is_refused_validation_failure():
    doc = order("BTU5+BTU2")
    oid = doc["orderId"]
    a, b = doc["nodes"][2], doc["nodes"][3]          # R3-6, R3-12 -> R3-12, R3-6
    a["nodeId"], b["nodeId"] = b["nodeId"], a["nodeId"]
    a["actions"][0]["actionId"], b["actions"][0]["actionId"] = f"{oid}:R3-12", f"{oid}:R3-6"
    nodes = doc["nodes"]
    for e, (x, y) in zip(doc["edges"], zip(nodes, nodes[1:], strict=False), strict=True):
        e["edgeId"] = f"{x['nodeId']}:{y['nodeId']}"
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE), r


@pytest.mark.parametrize("key", ["BTU5+STU7", "STU7+BTU5", "STU6+STU7", "STU7+STU6"])
def test_a_pair_mixing_row3_and_stu_is_no_valid_key(key):
    assert not vo.valid_key(SITE, key)
