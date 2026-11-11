"""Two MRU machines in one order (contract v1.2 PROPOSAL, owner 2026-11-11). The bridge's side: the
order shape and its checks, the `state` rows. One-machine orders stay as contract section 2 (the other
test files, read against the contract text)."""

import copy
import itertools
import json

import contract
import pytest
from test_vda_order import SEEN, check, ring
from test_vda_state import fields, view

from amr_station import bridge_core
from amr_station import vda_order as vo
from amr_station import vda_state as vs

SITE = contract.site()
PAIR_ID = "MRU1+MRU3-20261111T101500"


def pair_order(a=1, b=3, order_id=PAIR_ID):
    return {
        "headerId": 12,
        "timestamp": "2026-11-11T03:15:00.000Z",
        "version": "3.0.0",
        "manufacturer": "gvi",
        "serialNumber": "agv1",
        "orderId": order_id,
        "orderUpdateId": 0,
        "seenStateHeaderId": SEEN,
        **vo.canonical_order(SITE, f"MRU{a}+MRU{b}", order_id),
    }


def _wait(suffix):
    return [
        {
            "actionId": f"{PAIR_ID}:{suffix}",
            "actionType": "waitForTrigger",
            "blockingType": "HARD",
            "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}],
        }
    ]


def test_the_pair_order_is_the_proposed_table():
    home = SITE["HOME"]
    want_nodes = [
        (home, 0, []),
        ("ATT", 2, _wait("ATT")),
        ("MW-1", 4, _wait("MW-1")),
        ("MW-3", 6, _wait("MW-3")),
        ("ME-3", 8, _wait("ME-3")),
        ("ME-1", 10, _wait("ME-1")),
        (home, 12, []),
    ]
    doc = vo.canonical_order(SITE, "MRU1+MRU3", PAIR_ID)
    assert [(n["nodeId"], n["sequenceId"], n["actions"]) for n in doc["nodes"]] == want_nodes
    assert all(n["released"] for n in doc["nodes"] + doc["edges"])
    assert [(e["edgeId"], e["sequenceId"], e["actions"]) for e in doc["edges"]] == [
        (f"{home}:ATT", 1, []),
        ("ATT:MW-1", 3, []),
        ("MW-1:MW-3", 5, []),
        ("MW-3:ME-3", 7, []),
        ("ME-3:ME-1", 9, []),
        (f"ME-1:{home}", 11, []),
    ]


def test_one_machine_keeps_section_2_word_for_word():
    doc = vo.canonical_order(SITE, "MRU3", "X")
    assert [(n["nodeId"], n["sequenceId"], [a["actionId"] for a in n["actions"]]) for n in doc["nodes"]] == [
        ("HOME-N", 0, []),
        ("ATT", 2, ["X:ATT"]),
        ("MW-3", 4, ["X:MW"]),
        ("ME-3", 6, ["X:ME"]),
        ("HOME-N", 8, []),
    ]
    assert [e["edgeId"] for e in doc["edges"]] == ["HOME-N:ATT", "ATT:MW-3", "MW-3:ME-3", "ME-3:HOME-N"]


@pytest.mark.parametrize("a, b", list(itertools.combinations((1, 2, 3, 4), 2)))
def test_every_pair_closer_first_is_accepted(a, b):
    r = check(pair_order(a, b))
    assert (r.outcome, r.machine) == (vo.ACCEPT, f"MRU{a}+MRU{b}")


def _swap(doc, i, j):
    n = doc["nodes"]
    n[i]["nodeId"], n[j]["nodeId"] = n[j]["nodeId"], n[i]["nodeId"]
    return doc


def _farther_first(doc):
    out = vo.canonical_order(SITE, "MRU1+MRU3", PAIR_ID)  # rebuilt below with the machines swapped
    out["nodes"][2]["nodeId"], out["nodes"][5]["nodeId"] = "MW-3", "ME-3"
    out["nodes"][3]["nodeId"], out["nodes"][4]["nodeId"] = "MW-1", "ME-1"
    doc["nodes"] = out["nodes"]
    return doc


def _drop_node(doc):
    del doc["nodes"][3]
    return doc


def _same_twice(doc):
    for i, nid in ((3, "MW-1"), (4, "ME-1")):
        doc["nodes"][i]["nodeId"] = nid
    return doc


def _edge_off(doc):
    doc["edges"][2]["edgeId"] = "MW-1:MW-2"
    return doc


def _takes_in_call_order(doc):
    return _swap(doc, 4, 5)


@pytest.mark.parametrize(
    "make, error",
    [
        (_farther_first, vo.VALIDATION_FAILURE),
        (_drop_node, vo.VALIDATION_FAILURE),
        (_same_twice, vo.VALIDATION_FAILURE),
        (_edge_off, vo.VALIDATION_FAILURE),
        (_takes_in_call_order, vo.VALIDATION_FAILURE),
        (lambda d: d["nodes"].append(copy.deepcopy(d["nodes"][-1])) or d, vo.VALIDATION_FAILURE),
    ],
    ids=["farther-first", "six-nodes", "same-machine-twice", "edge", "takes-swapped", "eight-nodes"],
)
def test_a_wrong_pair_is_refused(make, error):
    r = check(make(pair_order()))
    assert (r.outcome, r.error) == (vo.REFUSE, error), r


def test_a_pair_with_the_one_machine_action_ids_is_an_invalid_action():
    doc = pair_order()
    doc["nodes"][2]["actions"][0]["actionId"] = f"{PAIR_ID}:MW"
    r = check(doc)
    assert (r.outcome, r.error, r.reason) == (vo.REFUSE, vo.INVALID_ORDER_ACTION, "ACTION")


def test_the_order_id_is_opaque_for_a_pair_too():
    r = check(pair_order(order_id="MRU4+MRU2-anything"))
    assert (r.outcome, r.machine) == (vo.ACCEPT, "MRU1+MRU3")


def test_pairs_off_refuses_a_pair_and_keeps_one_machine():
    payload = json.dumps(pair_order()).encode()
    kw = dict(manufacturer="gvi", serial="agv1", site=SITE, state_order_id="", state_machine="", now=100.0)
    r = vo.check_order(payload, False, ring=ring(), pairs=False, **kw)
    assert (r.outcome, r.error, r.reason) == (vo.REFUSE, vo.VALIDATION_FAILURE, "SHAPE")
    one = dict(pair_order(), **vo.canonical_order(SITE, "MRU3", PAIR_ID))
    r = vo.check_order(json.dumps(one).encode(), False, ring=ring(), pairs=False, **kw)
    assert r.outcome == vo.ACCEPT


def test_the_same_pair_again_is_ignored_and_other_content_is_not():
    assert check(pair_order(), state_order_id=PAIR_ID, state_machine="MRU1+MRU3").outcome == vo.IGNORE
    r = check(pair_order(1, 4), state_order_id=PAIR_ID, state_machine="MRU1+MRU3")
    assert (r.outcome, r.error) == (vo.REFUSE, vo.SAME_ORDER_UPDATE_ID)


@pytest.mark.parametrize("key", ["MRU3+MRU1", "MRU1+MRU1", "MRU1+BTU16", "MRU1+MRU2+MRU3", "MRU1+", "+MRU1"])
def test_valid_key(key):
    assert not vo.valid_key(SITE, key)
    assert vo.valid_key(SITE, "MRU1+MRU3") and vo.valid_key(SITE, "MRU3")


def test_the_bridge_departs_a_pair_with_its_machine_key():
    core = bridge_core.BridgeCore(SITE, "gvi", "agv1")
    core.ring.sent(SEEN, 100.0)
    assert core.on_order(json.dumps(pair_order()).encode(), False, 100.0) == ("depart", PAIR_ID, "MRU1+MRU3")
    old = bridge_core.BridgeCore(SITE, "gvi", "agv1", pairs=False)
    old.ring.sent(SEEN, 100.0)
    assert old.on_order(json.dumps(pair_order()).encode(), False, 100.0) is None
    assert old.refusal == {"type": vo.VALIDATION_FAILURE, "order_id": PAIR_ID, "reason": "SHAPE"}


# -- state ----------------------------------------------------------------------------------------
def pair_fields(att="WAITING", mw="WAITING", mw2="WAITING", me2="WAITING", me="WAITING", node="HOME-N",
                seq=0, active=True, **over):
    return fields(order_id=PAIR_ID, machine="MRU1+MRU3", active=active, departed=seq > 0, att_status=att,
                  mw_status=mw, mw2_status=mw2, me2_status=me2, me_status=me, last_node_id=node,
                  last_node_seq=seq, **over)


def _actions(body):
    return [(a["actionId"].split(":", 1)[1], a["actionStatus"]) for a in body["actionStates"]]


def test_state_at_the_second_release():
    body = vs.build_state(view(pair_fields("FINISHED", "FINISHED", "RUNNING", node="MW-3", seq=6)), SITE)
    assert _actions(body) == [("ATT", "FINISHED"), ("MW-1", "FINISHED"), ("MW-3", "RUNNING"),
                              ("ME-3", "WAITING"), ("ME-1", "WAITING")]
    assert all(a["actionType"] == "waitForTrigger" for a in body["actionStates"])
    assert [(n["nodeId"], n["sequenceId"]) for n in body["nodeStates"]] == [("ME-3", 8), ("ME-1", 10),
                                                                           ("HOME-N", 12)]
    assert [e["edgeId"] for e in body["edgeStates"]] == ["MW-3:ME-3", "ME-3:ME-1", "ME-1:HOME-N"]
    assert (body["lastNodeId"], body["lastNodeSequenceId"]) == ("MW-3", 6)


def test_a_closed_pair_has_no_nodes_and_sequence_12():
    done = dict(att="FINISHED", mw="FINISHED", mw2="FINISHED", me2="FINISHED", me="FINISHED")
    body = vs.build_state(view(pair_fields(**done, node="HOME-N", seq=12, active=False)), SITE)
    assert body["nodeStates"] == [] and body["edgeStates"] == [] and body["lastNodeSequenceId"] == 12
    assert [s for _id, s in _actions(body)] == ["FINISHED"] * 5


@pytest.mark.parametrize(
    "node, action", [("ATT", "ATT"), ("MW-1", "MW-1"), ("MW-3", "MW-3"), ("ME-3", "ME-3"), ("ME-1", "ME-1")]
)
def test_start_refused_names_the_stop_of_a_pair(node, action):
    body = vs.build_state(
        view(pair_fields(node=node, seq=4, start_refused_node=node, start_refused_reason="NO_TROLLEY")), SITE
    )
    (err,) = [e for e in body["errors"] if e["errorType"] == "START_REFUSED"]
    refs = {r["referenceKey"]: r["referenceValue"] for r in err["errorReferences"]}
    assert refs == {"nodeId": node, "actionId": f"{PAIR_ID}:{action}", "reason": "NO_TROLLEY"}


def test_one_machine_state_ignores_the_pair_fields():
    one = fields(order_id="X", machine="MRU3", active=True, departed=True, att_status="FINISHED",
                 mw_status="RUNNING", me_status="WAITING", mw2_status="", me2_status="", last_node_id="MW-3",
                 last_node_seq=4)
    body = vs.build_state(view(one), SITE)
    assert _actions(body) == [("ATT", "FINISHED"), ("MW", "RUNNING"), ("ME", "WAITING")]
