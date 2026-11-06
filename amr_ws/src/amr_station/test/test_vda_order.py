"""Contract checks 0 to 4 (plan 12.6). The job's checks 5 to 10 are amr_line/test/test_station_order.py."""

import copy
import json

import contract
import pytest

from amr_station import vda_order as vo

SITE = contract.site()
SEEN = 1042


def ring(*ids, now=100.0):
    r = vo.StateRing()
    for h in ids or (SEEN,):
        r.sent(h, now)
    return r


def check(doc, retained=False, state_order_id="", state_machine="", the_ring=None, now=100.0):
    payload = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    return vo.check_order(
        payload,
        retained,
        manufacturer="gvi",
        serial="agv1",
        site=SITE,
        state_order_id=state_order_id,
        state_machine=state_machine,
        ring=the_ring or ring(),
        now=now,
    )


def order(n=3, order_id=None):
    oid = order_id or f"MRU{n}-20261105T081530"
    return {
        "headerId": 12,
        "timestamp": "2026-11-05T01:15:31.200Z",
        "version": "3.0.0",
        "manufacturer": "gvi",
        "serialNumber": "agv1",
        "orderId": oid,
        "orderUpdateId": 0,
        "seenStateHeaderId": SEEN,
        **vo.canonical_order(SITE, f"MRU{n}", oid),
    }


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_the_contract_order_passes_for_each_machine(n):
    r = check(order(n))
    assert (r.outcome, r.machine) == (vo.ACCEPT, f"MRU{n}")


def test_the_order_in_the_contract_text_is_the_canonical_one():
    doc = contract.contract_order()
    want = vo.canonical_order(SITE, "MRU3", doc["orderId"])
    assert doc["nodes"] == want["nodes"] and doc["edges"] == want["edges"]
    assert check(doc).outcome == vo.ACCEPT


def _mut(fn):
    def apply():
        d = order()
        fn(d)
        return d

    return apply


CASES = [
    ("malformed_json", lambda: b"{nope", vo.VALIDATION_FAILURE),
    ("not_an_object", lambda: b"[1]", vo.VALIDATION_FAILURE),
    ("too_large", lambda: b" " * (vo.MAX_BYTES + 1), vo.VALIDATION_FAILURE),
    ("missing_field", _mut(lambda d: d.pop("nodes")), vo.VALIDATION_FAILURE),
    ("missing_seen", _mut(lambda d: d.pop("seenStateHeaderId")), vo.VALIDATION_FAILURE),
    ("other_serial", _mut(lambda d: d.update(serialNumber="agv2")), vo.VALIDATION_FAILURE),
    ("other_manufacturer", _mut(lambda d: d.update(manufacturer="x")), vo.VALIDATION_FAILURE),
    ("version_2", _mut(lambda d: d.update(version="2.1.0")), vo.VALIDATION_FAILURE),
    ("space_in_id", _mut(lambda d: d.update(orderId="a b")), vo.VALIDATION_FAILURE),
    ("released_false", _mut(lambda d: d["nodes"][2].update(released=False)), vo.VALIDATION_FAILURE),
    ("update_id_1", _mut(lambda d: d.update(orderUpdateId=1)), vo.VALIDATION_FAILURE),
    ("node_position", _mut(lambda d: d["nodes"][1].update(nodePosition={"x": 1})), vo.VALIDATION_FAILURE),
    ("trajectory", _mut(lambda d: d["edges"][1].update(trajectory={})), vo.VALIDATION_FAILURE),
    (
        "edge_action",
        _mut(lambda d: d["edges"][0]["actions"].append({"actionType": "x"})),
        vo.VALIDATION_FAILURE,
    ),
    ("btu_node", _mut(lambda d: d["nodes"][2].update(nodeId="R2-1")), vo.VALIDATION_FAILURE),
    (
        "two_machines",
        _mut(lambda d: d["nodes"].insert(3, copy.deepcopy(d["nodes"][2]))),
        vo.VALIDATION_FAILURE,
    ),
    ("mw_of_another", _mut(lambda d: d["nodes"][3].update(nodeId="ME-1")), vo.VALIDATION_FAILURE),
    (
        "fleet_control",
        _mut(lambda d: d["nodes"][1]["actions"][0]["actionParameters"][0].update(value=["FLEET_CONTROL"])),
        vo.INVALID_ORDER_ACTION,
    ),
    (
        "other_action",
        _mut(lambda d: d["nodes"][1]["actions"][0].update(actionType="pick")),
        vo.INVALID_ORDER_ACTION,
    ),
    ("no_action", _mut(lambda d: d["nodes"][1].update(actions=[])), vo.INVALID_ORDER_ACTION),
    (
        "soft_block",
        _mut(lambda d: d["nodes"][2]["actions"][0].update(blockingType="SOFT")),
        vo.INVALID_ORDER_ACTION,
    ),
]


@pytest.mark.parametrize("name, make, error", CASES, ids=[c[0] for c in CASES])
def test_each_check_refuses_with_its_error(name, make, error):
    r = check(make())
    assert (r.outcome, r.error) == (vo.REFUSE, error), (name, r)


def test_a_retained_order_is_discarded_silently():
    assert check(order(), retained=True) == vo.Result(vo.DISCARD)
    assert check(b"{nope", retained=True) == vo.Result(vo.DISCARD), "before any other check"


def test_a_stale_seen_header_is_refused():
    r = check(order(), the_ring=ring(SEEN + 1))
    assert (r.outcome, r.error) == (vo.REFUSE, vo.STALE_ORDER)
    r = check(order(), the_ring=ring(SEEN, now=90.0), now=100.0)
    assert (r.outcome, r.error) == (vo.REFUSE, vo.STALE_ORDER), "older than the 5 s window"


def test_a_seen_header_inside_the_window_passes():
    assert check(order(), the_ring=ring(SEEN, now=95.5), now=100.0).outcome == vo.ACCEPT


def test_same_id_same_content_is_ignored():
    d = order()
    r = check(d, state_order_id=d["orderId"], state_machine="MRU3")
    assert r.outcome == vo.IGNORE and not r.error


def test_same_id_other_content_is_reported():
    d = order(1, order_id="X")
    r = check(d, state_order_id="X", state_machine="MRU3")
    assert (r.outcome, r.error) == (vo.REFUSE, vo.SAME_ORDER_UPDATE_ID)


def test_header_and_seen_header_do_not_count_as_content():
    d = order()
    d.update(headerId=99, timestamp="x", seenStateHeaderId=1)
    r = check(d, state_order_id=d["orderId"], state_machine="MRU3", the_ring=ring(5))
    assert r.outcome == vo.IGNORE, "and check 4 is never reached for a resend"


def test_the_machine_comes_from_the_nodes_not_the_order_id():
    d = order(2, order_id="MRU4-20261105T081530")
    assert check(d).machine == "MRU2"


def test_a_swap_machine_is_not_orderable():
    assert "BTU16" not in vo.machines(SITE) and set(vo.machines(SITE)) == {"MRU1", "MRU2", "MRU3", "MRU4"}
