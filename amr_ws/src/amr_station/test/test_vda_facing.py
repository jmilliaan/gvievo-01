"""Facing machines (contract v1.4, owner 2026-11-14; mapping changed by the owner 2026-11-17): BTU9-16 face
BTU17-24 across row 2. Since 2026-11-17 the pairs are shifted by one: R2-k serves BTU(25-k) (own) and
BTU(16-k) (facing) for k = 1..7, R2-8 serves BTU17 alone, and BTU16 alone has its own stop R2-0, first on the
lap. A swap wait names its stop's machines in a `machines` parameter, own first, whenever they are not just
the stop's first machine (so BTU16 alone at R2-0 carries none). Two at one stop are one wait, one START: the
one-stop shape. An order serves at most two machines. The bridge's side: shapes, checks, state.
Contract v1.5 (station patch, applied 2026-11-17) states this mapping."""

import copy
import json

import contract
import pytest
from test_vda_order import check, ring
from test_vda_state import view
from test_vda_swap import btu_fields

from amr_station import bridge_core
from amr_station import vda_order as vo
from amr_station import vda_state as vs

SITE = contract.site()
SEEN = 1042


def own(k):
    return f"BTU{25 - k}"


def facing(k):
    """The machine facing R2-k's own one, k = 1..7 (owner 2026-11-17). R2-8 has none; BTU16 is at R2-0."""
    return f"BTU{16 - k}"



def order_of(key, order_id=None):
    order_id = order_id or f"{key}-20261114T102000"
    return {
        "headerId": 14,
        "timestamp": "2026-11-14T03:20:00.500Z",
        "version": "3.0.0",
        "manufacturer": "gvi",
        "serialNumber": "agv1",
        "orderId": order_id,
        "orderUpdateId": 0,
        "seenStateHeaderId": SEEN,
        **vo.canonical_order(SITE, key, order_id),
    }


def params(doc, i):
    return doc["nodes"][i]["actions"][0]["actionParameters"]


# -- the canonical shapes -------------------------------------------------------------------------
def test_the_contract_example_is_the_canonical_face_to_face_order():
    """Contract section 2, the station's text: the AGV builds and accepts exactly its example. The machines
    come from the example's own orderId, so the patched example is checked as it stands."""
    doc = contract.contract_btu_face_order()
    key = doc["orderId"].rsplit("-", 1)[0]
    want = vo.canonical_order(SITE, key, doc["orderId"])
    assert doc["nodes"] == want["nodes"] and doc["edges"] == want["edges"]
    r = check(doc, the_ring=ring(doc["seenStateHeaderId"]))
    assert (r.outcome, r.machine) == (vo.ACCEPT, key)


@pytest.mark.parametrize("k", range(1, 8))
def test_one_facing_machine_is_one_stop_with_machines(k):
    doc = order_of(facing(k))
    assert [n["nodeId"] for n in doc["nodes"]] == ["HOME-N", "ATT", f"R2-{k}", "HOME-N"]
    assert params(doc, 2) == [{"key": "triggerType", "value": ["LOCAL"]},
                              {"key": "machines", "value": [facing(k)]}]
    assert params(doc, 1) == [{"key": "triggerType", "value": ["LOCAL"]}], "ATT never carries machines"
    assert (check(doc).outcome, check(doc).machine) == (vo.ACCEPT, facing(k))


@pytest.mark.parametrize("k", range(1, 8))
def test_both_machines_of_a_stop_are_one_wait_own_first(k):
    key = f"{own(k)}+{facing(k)}"
    doc = order_of(key)
    assert [(n["nodeId"], n["sequenceId"]) for n in doc["nodes"]] == [
        ("HOME-N", 0), ("ATT", 2), (f"R2-{k}", 4), ("HOME-N", 6)]
    assert doc["nodes"][2]["actions"][0]["actionId"] == f"{key}-20261114T102000:R2-{k}"
    assert params(doc, 2)[1] == {"key": "machines", "value": [own(k), facing(k)]}
    assert (check(doc).outcome, check(doc).machine) == (vo.ACCEPT, key)


def test_the_own_machine_alone_has_no_machines_parameter_as_in_v13():
    doc = order_of("BTU23")
    assert params(doc, 2) == [{"key": "triggerType", "value": ["LOCAL"]}]


@pytest.mark.parametrize("machine, node", [("BTU16", "R2-0"), ("BTU17", "R2-8")])
def test_a_machine_alone_at_its_stop_has_no_machines_parameter(machine, node):
    """Owner 2026-11-17: BTU16 has its own stop R2-0 (first on the lap), BTU17 is alone at R2-8. A stop's
    only machine is its first: no `machines`, exactly like a v1.3 order."""
    doc = order_of(machine)
    assert [n["nodeId"] for n in doc["nodes"]] == ["HOME-N", "ATT", node, "HOME-N"]
    assert params(doc, 2) == [{"key": "triggerType", "value": ["LOCAL"]}]
    assert (check(doc).outcome, check(doc).machine) == (vo.ACCEPT, machine)


def test_r2_0_is_the_first_stop_of_the_lap():
    doc = order_of("BTU16+BTU24")
    assert [n["nodeId"] for n in doc["nodes"]] == ["HOME-N", "ATT", "R2-0", "R2-1", "HOME-N"]
    assert check(doc).machine == "BTU16+BTU24"
    assert not vo.valid_key(SITE, "BTU24+BTU16")


@pytest.mark.parametrize("key, named", [
    ("BTU24+BTU13", [None, ["BTU13"]]),
    ("BTU15+BTU22", [["BTU15"], None]),
    ("BTU15+BTU13", [["BTU15"], ["BTU13"]]),
    ("BTU16+BTU14", [None, ["BTU14"]]),
])
def test_two_stops_name_each_facing_machine_at_its_stop(key, named):
    doc = order_of(key)
    got = [next((p["value"] for p in params(doc, i) if p["key"] == "machines"), None) for i in (2, 3)]
    assert got == named
    assert (check(doc).outcome, check(doc).machine) == (vo.ACCEPT, key)


def test_every_machine_pair_the_contract_allows_is_accepted():
    """All 16 machines; one or two; at one stop own first, else the closer stop first (R2-0 .. R2-8)."""
    sw = vo.swap_machines(SITE)
    pos = {f"R2-{k}": k for k in range(0, 9)}
    names = sorted(sw, key=lambda m: int(m[3:]))
    accepted = 0
    for a in names:
        assert check(order_of(a)).machine == a
        accepted += 1
        for b in names:
            same = sw[a] == sw[b]
            ok = a != b and ((same and int(a[3:]) > int(b[3:])) or (not same and pos[sw[a]] < pos[sw[b]]))
            assert vo.valid_key(SITE, f"{a}+{b}") == ok, (a, b)
            if ok:
                assert check(order_of(f"{a}+{b}")).machine == f"{a}+{b}"
                accepted += 1
    # 16 alone + 7 face-to-face (R2-1..R2-7) + the 120 - 7 pairs at two stops, one order each
    assert accepted == 16 + 7 + 113


# -- refusals (contract section 10) ----------------------------------------------------------------
def _set_machines(doc, i, value):
    ps = params(doc, i)
    ps[:] = [p for p in ps if p["key"] != "machines"]
    if value is not None:
        ps.append({"key": "machines", "value": value})
    return doc


@pytest.mark.parametrize("value", [
    ["BTU23"],                    # naming only the own machine
    ["BTU14", "BTU23"],           # out of order
    ["BTU15"],                    # not at that stop (the v1.4 pairing)
    ["BTU23", "BTU15"],
    ["BTU14", "BTU14"],           # the same twice
    ["BTU23", "BTU14", "BTU14"],
    ["MRU1"],
])
def test_a_wrong_machines_list_is_a_validation_failure(value):
    doc = _set_machines(order_of("BTU23+BTU14"), 2, value)
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE), r


def test_three_machines_in_two_stops_are_refused():
    doc = _set_machines(order_of("BTU24+BTU22"), 2, ["BTU24", "BTU15"])
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE), r


def test_a_face_to_face_pair_as_two_stops_is_refused():
    """The same node twice: the one-stop shape is the only spelling."""
    doc = order_of("BTU24+BTU19")
    doc["nodes"][3]["nodeId"] = "R2-1"
    _set_machines(doc, 3, ["BTU15"])
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.VALIDATION_FAILURE), r


@pytest.mark.parametrize("value", ["BTU14", [], [14], {"BTU14": True}])
def test_a_machines_value_that_is_no_list_of_names_is_an_invalid_action(value):
    doc = _set_machines(order_of("BTU14"), 2, value)
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.INVALID_ORDER_ACTION), r


@pytest.mark.parametrize("mutate", ["before-trigger", "missing", "on-att", "other-key"])
def test_a_machines_parameter_out_of_place_is_an_invalid_action(mutate):
    doc = order_of("BTU23+BTU14")
    ps = params(doc, 2)
    if mutate == "before-trigger":
        ps.reverse()
    elif mutate == "missing":
        doc = order_of("BTU14")
        _set_machines(doc, 2, None)                 # reads as BTU23, then the action ids differ
        doc["nodes"][2]["actions"][0]["actionParameters"].append({"key": "machines"})
    elif mutate == "on-att":
        params(doc, 1).append({"key": "machines", "value": ["BTU23"]})
    else:
        ps.append({"key": "note", "value": "x"})
    r = check(doc)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.INVALID_ORDER_ACTION), r


def test_a_wait_with_no_machines_is_the_own_machine_whatever_the_order_id():
    """The orderId is opaque (contract section 2): a wait with no `machines` is the stop's own machine, BTU23,
    whatever the id says. Spelling the facing machine is the station's job."""
    doc = _set_machines(order_of("BTU14"), 2, None)
    r = check(doc)
    assert (r.outcome, r.machine) == (vo.ACCEPT, "BTU23")


def test_pairs_off_still_takes_one_stop_with_two_machines():
    """The pairs gate is about a second wait (mw2_status). A face-to-face pair has one wait after ATT."""
    kw = dict(manufacturer="gvi", serial="agv1", site=SITE, state_order_id="", state_machine="", now=100.0)
    r = vo.check_order(json.dumps(order_of("BTU23+BTU14")).encode(), False, ring=ring(), pairs=False, **kw)
    assert (r.outcome, r.machine) == (vo.ACCEPT, "BTU23+BTU14")
    r = vo.check_order(json.dumps(order_of("BTU16+BTU14")).encode(), False, ring=ring(), pairs=False, **kw)
    assert (r.outcome, r.reason) == (vo.REFUSE, "SHAPE")


def test_the_same_face_to_face_order_again_is_ignored():
    doc = order_of("BTU23+BTU14")
    assert check(doc, state_order_id=doc["orderId"], state_machine="BTU23+BTU14").outcome == vo.IGNORE
    other = copy.deepcopy(doc)
    _set_machines(other, 2, ["BTU14"])
    r = check(other, state_order_id=doc["orderId"], state_machine="BTU23+BTU14")
    assert (r.outcome, r.error) == (vo.REFUSE, vo.SAME_ORDER_UPDATE_ID)


def test_every_v13_order_is_unchanged_byte_for_byte():
    """Contract v1.4: every v1.3 order is unchanged. Own machines only: no `machines` anywhere."""
    for key in ["BTU24", "BTU17", "BTU24+BTU19", "BTU22+BTU17"]:
        doc = order_of(key)
        assert all(len(n["actions"][0]["actionParameters"]) == 1 for n in doc["nodes"] if n["actions"]), key


def test_the_bridge_departs_a_face_to_face_pair_with_its_machine_key():
    core = bridge_core.BridgeCore(SITE, "gvi", "agv1")
    core.ring.sent(SEEN, 100.0)
    doc = order_of("BTU23+BTU14")
    assert core.on_order(json.dumps(doc).encode(), False, 100.0) == ("depart", doc["orderId"], "BTU23+BTU14")


# -- state ----------------------------------------------------------------------------------------
FACE_ID = "BTU23+BTU14-20261117T102000"


def _actions(body):
    return [(a["actionId"].split(":", 1)[1], a["actionStatus"]) for a in body["actionStates"]]


def test_state_of_a_face_to_face_pair_has_one_swap_row():
    """Both calls read the same O:R2-k (contract section 6, v1.4)."""
    body = vs.build_state(view(btu_fields("BTU23+BTU14", FACE_ID, "FINISHED", "RUNNING", node="R2-2", seq=4)),
                          SITE)
    assert _actions(body) == [("ATT", "FINISHED"), ("R2-2", "RUNNING")]
    assert [(n["nodeId"], n["sequenceId"]) for n in body["nodeStates"]] == [("HOME-N", 6)]
    assert [e["edgeId"] for e in body["edgeStates"]] == ["R2-2:HOME-N"]


def test_a_closed_face_to_face_pair_ends_at_6():
    f = btu_fields("BTU23+BTU14", FACE_ID, "FINISHED", "FINISHED", seq=6, node="HOME-N", active=False)
    body = vs.build_state(view(f), SITE)
    assert body["nodeStates"] == [] and body["lastNodeSequenceId"] == 6
    assert _actions(body) == [("ATT", "FINISHED"), ("R2-2", "FINISHED")]
