"""instantActions: cancelOrder only, once per actionId (plan 12.8)."""

import json

import contract
import pytest

from amr_station import bridge_core as bc


def core():
    return bc.BridgeCore(contract.site(), "gvi", "agv1")


def msg(*actions, serial="agv1"):
    return json.dumps(
        {
            "headerId": 1,
            "timestamp": "t",
            "version": "3.0.0",
            "manufacturer": "gvi",
            "serialNumber": serial,
            "actions": list(actions),
        }
    ).encode()


def cancel(action_id="c1", order_id="O1"):
    return {
        "actionId": action_id,
        "actionType": "cancelOrder",
        "blockingType": "NONE",
        "actionParameters": [{"key": "orderId", "value": order_id}],
    }


def result(c, seq, action_id, status, error=""):
    c.on_order_state(
        {
            "order_id": "O1",
            "active": True,
            "cancel_seq": seq,
            "cancel_action_id": action_id,
            "cancel_status": status,
            "cancel_error": error,
            "refusal_seq": 0,
        },
        1.0,
    )


def test_a_cancel_acts_once_per_action_id():
    c = core()
    assert c.on_instant(msg(cancel()), False) == [("cancel", "O1", "c1")]
    assert c.on_instant(msg(cancel()), False) == []
    assert c.instant[0]["actionStatus"] == "RUNNING"


def test_a_retained_instant_action_is_discarded():
    c = core()
    assert c.on_instant(msg(cancel()), True) == [] and c.instant == []


def test_another_agvs_message_has_no_effect():
    c = core()
    assert c.on_instant(msg(cancel(), serial="agv2"), False) == [] and c.instant == []
    assert c.on_instant(b"{nope", False) == [] and c.instant == []


@pytest.mark.parametrize(
    "status, error, errors",
    [
        ("FINISHED", "", []),
        ("FAILED", "CANCEL_REFUSED", ["CANCEL_REFUSED"]),
        ("FAILED", "NO_ORDER_TO_CANCEL", ["NO_ORDER_TO_CANCEL"]),
    ],
)
def test_results_for_each_situation(status, error, errors):
    c = core()
    c.on_order_state({"order_id": "O1", "active": True, "cancel_seq": 0, "refusal_seq": 0}, 0.5)
    c.on_instant(msg(cancel()), False)
    result(c, 1, "c1", status, error)
    assert c.instant[0]["actionStatus"] == status
    assert [e["errorType"] for e in c.instant_errors] == errors
    v = c.view(1.0)
    assert all(not k.startswith("_") for s in v.instant_states for k in s)


@pytest.mark.parametrize(
    "atype", ["startPause", "stopPause", "trigger", "factsheetRequest", "stateRequest", "initPosition"]
)
def test_any_other_action_is_refused(atype):
    c = core()
    assert c.on_instant(msg({"actionId": "a", "actionType": atype, "blockingType": "NONE"}), False) == []
    assert c.instant == [{"actionId": "a", "actionType": atype, "actionStatus": "FAILED"}]
    assert c.instant_errors == [{"errorType": "INVALID_INSTANT_ACTION", "actionId": "a"}]


def test_a_cancel_with_no_order_id_is_invalid():
    c = core()
    assert c.on_instant(msg({"actionId": "a", "actionType": "cancelOrder"}), False) == []
    assert c.instant_errors[0]["errorType"] == "INVALID_INSTANT_ACTION"


def test_last_five_kept_and_cleared_on_accept():
    c = core()
    c.on_order_state({"order_id": "O0", "active": False, "cancel_seq": 0, "refusal_seq": 0}, 0.5)
    for n in range(7):
        c.on_instant(msg(cancel(f"c{n}")), False)
    assert [s["actionId"] for s in c.instant] == [f"c{n}" for n in range(2, 7)]
    c.on_order_state({"order_id": "O2", "active": True, "cancel_seq": 0, "refusal_seq": 0}, 1.0)
    assert c.instant == [] and c.instant_errors == []


def test_the_refusal_slot_holds_the_newest_and_clears_on_accept():
    c = core()
    c.refuse("STALE_ORDER", "A", "x")
    c.on_order_state(
        {
            "order_id": "",
            "active": False,
            "cancel_seq": 0,
            "refusal_seq": 1,
            "refusal_type": "DEPARTURE_REFUSED",
            "refusal_order_id": "B",
            "refusal_reason": "SETTLING",
        },
        1.0,
    )
    assert c.refusal == {"type": "DEPARTURE_REFUSED", "order_id": "B", "reason": "SETTLING"}
    c.on_order_state({"order_id": "B", "active": True, "cancel_seq": 0, "refusal_seq": 1}, 2.0)
    assert c.refusal is None


def test_an_old_order_state_reads_as_none():
    c = core()
    c.on_order_state({"order_id": "", "active": False, "cancel_seq": 0, "refusal_seq": 0}, 1.0)
    assert c.view(3.9).order is not None and c.view(4.1).order is None


def test_state_is_due_on_a_change_and_each_second():
    c = core()
    assert c.state_due({"a": 1}, 0.0) and not c.state_due({"a": 1}, 0.5)
    assert c.state_due({"a": 2}, 0.6) and c.state_due({"a": 2}, 1.7)
