"""BTU laps from station orders (contract v1.3, owner 2026-11-13). The bridge's side: the order shape and its
checks, the `state` rows. One BTU: HOME 0, ATT 2, R2-k 4, HOME 6. Two BTUs, the closer first: HOME 0, ATT 2,
R2-j 4, R2-k 6, HOME 8. Action ids end in the node id. R2-k names BTU(25-k): the BTU9-16 that share the stops
cannot be named by nodes, refusing them is the station's rule."""

import copy
import itertools
import json

import contract
import pytest
from test_vda_order import SEEN, check, ring
from test_vda_pair import pair_order
from test_vda_state import fields, view

from amr_station import bridge_core
from amr_station import vda_order as vo
from amr_station import vda_state as vs

SITE = contract.site()
ONE_ID = "BTU24-20261113T101500"
TWO_ID = "BTU24+BTU19-20261113T101500"


def btu(k):
    return f"BTU{25 - k}"


def btu_order(*ks, order_id=None):
    key = "+".join(btu(k) for k in ks)
    order_id = order_id or f"{key}-20261113T101500"
    return {
        "headerId": 12,
        "timestamp": "2026-11-13T03:15:00.000Z",
        "version": "3.0.0",
        "manufacturer": "gvi",
        "serialNumber": "agv1",
        "orderId": order_id,
        "orderUpdateId": 0,
        "seenStateHeaderId": SEEN,
        **vo.canonical_order(SITE, key, order_id),
    }


def _wait(order_id, suffix):
    return [
        {
            "actionId": f"{order_id}:{suffix}",
            "actionType": "waitForTrigger",
            "blockingType": "HARD",
            "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}],
        }
    ]


# -- the shape ------------------------------------------------------------------------------------
def test_one_btu_is_the_v13_table():
    doc = vo.canonical_order(SITE, "BTU24", ONE_ID)
    assert [(n["nodeId"], n["sequenceId"], n["actions"]) for n in doc["nodes"]] == [
        ("HOME-N", 0, []),
        ("ATT", 2, _wait(ONE_ID, "ATT")),
        ("R2-1", 4, _wait(ONE_ID, "R2-1")),
        ("HOME-N", 6, []),
    ]
    assert [(e["edgeId"], e["sequenceId"], e["actions"]) for e in doc["edges"]] == [
        ("HOME-N:ATT", 1, []), ("ATT:R2-1", 3, []), ("R2-1:HOME-N", 5, []),
    ]
    assert all(n["released"] for n in doc["nodes"] + doc["edges"])


def test_two_btus_closer_first_is_the_v13_table():
    doc = vo.canonical_order(SITE, "BTU24+BTU19", TWO_ID)
    assert [(n["nodeId"], n["sequenceId"], [a["actionId"] for a in n["actions"]]) for n in doc["nodes"]] == [
        ("HOME-N", 0, []),
        ("ATT", 2, [f"{TWO_ID}:ATT"]),
        ("R2-1", 4, [f"{TWO_ID}:R2-1"]),
        ("R2-6", 6, [f"{TWO_ID}:R2-6"]),
        ("HOME-N", 8, []),
    ]
    assert [e["edgeId"] for e in doc["edges"]] == ["HOME-N:ATT", "ATT:R2-1", "R2-1:R2-6", "R2-6:HOME-N"]


@pytest.mark.parametrize("k", range(1, 9))
def test_r2_k_names_btu_25_minus_k(k):
    r = check(btu_order(k))
    assert (r.outcome, r.machine) == (vo.ACCEPT, btu(k))


@pytest.mark.parametrize("j, k", list(itertools.combinations(range(1, 9), 2)))
def test_every_two_btus_closer_first_are_accepted(j, k):
    r = check(btu_order(j, k))
    assert (r.outcome, r.machine) == (vo.ACCEPT, f"{btu(j)}+{btu(k)}")


def test_the_mission_order_decides_which_machine_a_shared_stop_names():
    """BTU16..BTU9 share R2-1..R2-8 and come after BTU24..BTU17 in site-103: never named by an order."""
    assert vo.swaps(SITE) == {btu(k): f"R2-{k}" for k in range(1, 9)}
    assert all(not vo.valid_key(SITE, f"BTU{n}") for n in range(9, 17))


def mru3_order():
    doc = btu_order(1, order_id="MRU3-20261113T101500")
    return dict(doc, **vo.canonical_order(SITE, "MRU3", doc["orderId"]))


def test_one_mru_is_still_one_mru_with_five_nodes():
    assert check(mru3_order()).machine == "MRU3"
    assert check(btu_order(1, 6)).machine == "BTU24+BTU19"


def _farther_first(doc):
    n = doc["nodes"]
    n[2]["nodeId"], n[3]["nodeId"] = n[3]["nodeId"], n[2]["nodeId"]
    return doc


def _same_twice(doc):
    doc["nodes"][3]["nodeId"] = doc["nodes"][2]["nodeId"]
    return doc


def _three(doc):
    three = vo.canonical_order(SITE, "BTU24+BTU19", doc["orderId"])
    extra = copy.deepcopy(three["nodes"][3])
    extra.update(nodeId="R2-8", sequenceId=8)
    doc["nodes"] = three["nodes"][:4] + [extra, dict(three["nodes"][4], sequenceId=10)]
    return doc


def _mixed(doc):
    doc["nodes"][3]["nodeId"] = "MW-1"
    return doc


def _btu9_16_by_name(doc):
    doc["nodes"][2]["nodeId"] = "BTU16"
    return doc


def _uturn_node(doc):
    doc["nodes"][2]["nodeId"] = "UT-MRU1"
    return doc


def _edge_off(doc):
    doc["edges"][2]["edgeId"] = "R2-1:HOME-N"
    return doc


def _not_released(doc):
    doc["nodes"][2]["released"] = False
    return doc


@pytest.mark.parametrize(
    "make",
    [_farther_first, _same_twice, _three, _mixed, _btu9_16_by_name, _uturn_node, _edge_off, _not_released],
    ids=["farther-first", "same-twice", "three-btus", "mixed-groups", "btu9-16", "uturn-node", "edge",
         "released-false"],
)
def test_a_wrong_btu_order_is_refused(make):
    r = check(make(btu_order(1, 6)))
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE), r


def test_one_btu_with_a_wrong_node_is_refused():
    doc = btu_order(1)
    doc["nodes"][2]["nodeId"] = "R2-9"
    assert (check(doc).outcome, check(doc).error) == (vo.REFUSE, vo.VALIDATION_FAILURE)


def test_a_btu_wait_with_another_suffix_is_an_invalid_action():
    doc = btu_order(1)
    doc["nodes"][2]["actions"][0]["actionId"] = f"{doc['orderId']}:MW"
    r = check(doc)
    assert (r.outcome, r.error, r.reason) == (vo.REFUSE, vo.INVALID_ORDER_ACTION, "ACTION")


def test_a_node_id_of_the_wrong_type_is_refused_not_raised():
    doc = btu_order(1)
    doc["nodes"][2]["nodeId"] = ["R2-1"]
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE)


def test_the_order_id_is_opaque_for_btu_too():
    r = check(btu_order(1, 6, order_id="BTU17-anything"))
    assert (r.outcome, r.machine) == (vo.ACCEPT, "BTU24+BTU19")


def test_pairs_off_refuses_two_btus_and_keeps_one():
    kw = dict(manufacturer="gvi", serial="agv1", site=SITE, state_order_id="", state_machine="", now=100.0)
    r = vo.check_order(json.dumps(btu_order(1, 6)).encode(), False, ring=ring(), pairs=False, **kw)
    assert (r.outcome, r.error, r.reason) == (vo.REFUSE, vo.VALIDATION_FAILURE, "SHAPE")
    r = vo.check_order(json.dumps(btu_order(1)).encode(), False, ring=ring(), pairs=False, **kw)
    assert (r.outcome, r.machine) == (vo.ACCEPT, "BTU24")


def test_the_same_btu_order_again_is_ignored_and_other_content_is_not():
    doc = btu_order(1, 6)
    assert check(doc, state_order_id=doc["orderId"], state_machine="BTU24+BTU19").outcome == vo.IGNORE
    other = btu_order(1, 7, order_id=doc["orderId"])
    r = check(other, state_order_id=doc["orderId"], state_machine="BTU24+BTU19")
    assert (r.outcome, r.error) == (vo.REFUSE, vo.SAME_ORDER_UPDATE_ID)


@pytest.mark.parametrize(
    "key", ["BTU19+BTU24", "BTU24+BTU24", "BTU24+BTU16", "BTU16", "BTU24+MRU1", "MRU1+BTU24",
            "BTU24+BTU19+BTU17", "BTU24+"],
)
def test_valid_key_for_btu(key):
    assert not vo.valid_key(SITE, key)
    assert vo.valid_key(SITE, "BTU24") and vo.valid_key(SITE, "BTU24+BTU17") and vo.valid_key(SITE, "BTU17")


def test_the_mru_orders_are_unchanged():
    """A one-machine station order must keep working exactly as it does now; the pair too."""
    assert check(mru3_order()).machine == "MRU3"
    assert check(pair_order(1, 3)).machine == "MRU1+MRU3"
    assert vo.waits(SITE, "MRU3") == [("ATT", "ATT", 2), ("MW-3", "MW", 4), ("ME-3", "ME", 6)]


def test_the_bridge_departs_btu_with_its_machine_key():
    core = bridge_core.BridgeCore(SITE, "gvi", "agv1")
    core.ring.sent(SEEN, 100.0)
    doc = btu_order(1, 6)
    assert core.on_order(json.dumps(doc).encode(), False, 100.0) == ("depart", doc["orderId"], "BTU24+BTU19")


# -- state ----------------------------------------------------------------------------------------
def btu_fields(key, order_id, att="WAITING", mw="WAITING", mw2="", node="HOME-N", seq=0, active=True, **over):
    return fields(order_id=order_id, machine=key, active=active, departed=seq > 0, att_status=att,
                  mw_status=mw, mw2_status=mw2, me_status="", me2_status="", last_node_id=node,
                  last_node_seq=seq, **over)


def _actions(body):
    return [(a["actionId"].split(":", 1)[1], a["actionStatus"]) for a in body["actionStates"]]


def test_state_of_one_btu_at_its_swap():
    body = vs.build_state(view(btu_fields("BTU24", ONE_ID, "FINISHED", "RUNNING", node="R2-1", seq=4)), SITE)
    assert _actions(body) == [("ATT", "FINISHED"), ("R2-1", "RUNNING")]
    assert all(a["actionType"] == "waitForTrigger" for a in body["actionStates"])
    assert [(n["nodeId"], n["sequenceId"]) for n in body["nodeStates"]] == [("HOME-N", 6)]
    assert [e["edgeId"] for e in body["edgeStates"]] == ["R2-1:HOME-N"]
    assert (body["lastNodeId"], body["lastNodeSequenceId"]) == ("R2-1", 4)


def test_state_of_two_btus_at_the_second_swap():
    f = btu_fields("BTU24+BTU19", TWO_ID, "FINISHED", "FINISHED", "RUNNING", node="R2-6", seq=6)
    body = vs.build_state(view(f), SITE)
    assert _actions(body) == [("ATT", "FINISHED"), ("R2-1", "FINISHED"), ("R2-6", "RUNNING")]
    assert [(n["nodeId"], n["sequenceId"]) for n in body["nodeStates"]] == [("HOME-N", 8)]


@pytest.mark.parametrize("key, order_id, seq", [("BTU24", ONE_ID, 6), ("BTU24+BTU19", TWO_ID, 8)])
def test_a_closed_btu_lap_has_no_nodes_and_ends_at_6_or_8(key, order_id, seq):
    two = "+" in key
    f = btu_fields(key, order_id, "FINISHED", "FINISHED", "FINISHED" if two else "", seq=seq, active=False)
    body = vs.build_state(view(f), SITE)
    assert body["nodeStates"] == [] and body["edgeStates"] == [] and body["lastNodeSequenceId"] == seq
    assert [s for _id, s in _actions(body)] == ["FINISHED"] * (3 if two else 2)


@pytest.mark.parametrize("node", ["ATT", "R2-1", "R2-6"])
def test_start_refused_names_the_stop_of_a_btu_lap(node):
    f = btu_fields("BTU24+BTU19", TWO_ID, node=node, seq=4, start_refused_node=node,
                   start_refused_reason="WARNING_CANCELLED")
    (err,) = [e for e in vs.build_state(view(f), SITE)["errors"] if e["errorType"] == "START_REFUSED"]
    refs = {r["referenceKey"]: r["referenceValue"] for r in err["errorReferences"]}
    assert refs == {"nodeId": node, "actionId": f"{TWO_ID}:{node}", "reason": "WARNING_CANCELLED"}


def test_the_btu_pair_in_the_contract_text_is_the_canonical_one():
    """Contract v1.3 section 2, the station's text: the AGV builds and accepts exactly its example."""
    doc = contract.contract_btu_pair_order()
    want = vo.canonical_order(SITE, "BTU24+BTU19", doc["orderId"])
    assert doc["nodes"] == want["nodes"] and doc["edges"] == want["edges"]
    r = check(doc)
    assert (r.outcome, r.machine) == (vo.ACCEPT, "BTU24+BTU19")


def test_the_contract_text_maps_r2_k_to_btu_25_minus_k():
    row = contract.PLAN.split("| Swap node |", 1)[1].split("\n", 1)[0]
    nodes = [c.strip(" `") for c in row.split("|") if c.strip()]
    head = contract.PLAN.split("| Machine | BTU24", 1)[1].split("\n", 1)[0]
    machines = ["BTU24"] + [c.strip() for c in head.split("|") if c.strip()]
    assert dict(zip(machines, nodes, strict=True)) == vo.swaps(SITE)
