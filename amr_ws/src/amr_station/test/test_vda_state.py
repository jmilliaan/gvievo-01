"""Contract section 6.2: every state example, built from a matching OrderState (plan 12.11)."""

import copy

import contract
import pytest
from contract import ORDER_ID as O_ID
from contract import strip_header

from amr_station import vda_state as vs

SITE = contract.site()
ABSENT, PRESENT, UNKNOWN = 1, 2, 0
CLEAR, FIELD_UNKNOWN = 1, 0


def fields(**over):
    d = dict(
        order_id="",
        machine="",
        active=False,
        departed=False,
        att_status="",
        mw_status="",
        me_status="",
        last_node_id="",
        last_node_seq=0,
        driving=False,
        trolley=ABSENT,
        rear_field=CLEAR,
        not_ready=[],
        cancelled_reason="",
        cancelled_text="",
        aborted_reason="",
        aborted_text="",
        start_refused_node="",
        start_refused_reason="",
    )
    d.update(over)
    return d


def trip(att="WAITING", mw="WAITING", me="WAITING", node="HOME-N", seq=0, active=True, **over):
    return fields(
        order_id=O_ID,
        machine="MRU3",
        active=active,
        departed=True,
        att_status=att,
        mw_status=mw,
        me_status=me,
        last_node_id=node,
        last_node_seq=seq,
        **over,
    )


def view(order, **over):
    base = dict(
        mode=7, layer_ready=True, panel_valid=True, panel_auto=True, field_fresh=True, protective_clear=True
    )
    base.update(over)
    return vs.StateView(order=order, **base)


REFUSED = {"type": "DEPARTURE_REFUSED", "order_id": O_ID, "reason": "TROLLEY_UNKNOWN"}
NOT_FREE = dict(
    trolley=UNKNOWN, rear_field=FIELD_UNKNOWN, not_ready=["TROLLEY_UNKNOWN", "REAR_FIELD_UNKNOWN"]
)
FAILED = dict(att="FAILED", mw="FAILED", me="FAILED", active=False)
VIEWS = {
    "QUEUED, AGV free": view(fields()),
    "QUEUED, AGV not free": view(fields(**NOT_FREE)),
    "QUEUED, order refused": view(fields(**NOT_FREE), refusal=REFUSED),
    "TO_PICKUP": view(trip()),
    "AT_PICKUP": view(trip("RUNNING", node="ATT", seq=2)),
    "AT_PICKUP, START refused": view(
        trip("RUNNING", node="ATT", seq=2, start_refused_node="ATT", start_refused_reason="NO_TROLLEY")
    ),
    "TO_MACHINE": view(trip("FINISHED", node="ATT", seq=2, trolley=PRESENT, driving=True)),
    "AT_RELEASE": view(trip("FINISHED", "RUNNING", node="MW-3", seq=4, trolley=PRESENT)),
    "TURNING": view(trip("FINISHED", "FINISHED", node="MW-3", seq=4, driving=True)),
    "AT_ATTACH": view(trip("FINISHED", "FINISHED", "RUNNING", node="ME-3", seq=6)),
    "RETURNING": view(
        trip("FINISHED", "FINISHED", "FINISHED", node="ME-3", seq=6, trolley=PRESENT, driving=True)
    ),
    "Closed": view(
        trip(
            "FINISHED",
            "FINISHED",
            "FINISHED",
            node="HOME-N",
            seq=8,
            active=False,
            trolley=PRESENT,
            not_ready=["TROLLEY_PRESENT", "SETTLING"],
        )
    ),
    "Aborted": view(
        trip(
            "FINISHED",
            "FAILED",
            "FAILED",
            node="ATT",
            seq=2,
            active=False,
            trolley=PRESENT,
            aborted_reason="NOT_AUTO",
            aborted_text="Selector left AUTO during a trip",
            not_ready=["NOT_AUTO", "NOT_AT_HOME", "TROLLEY_PRESENT"],
        ),
        panel_auto=False,
    ),
    "Requeued": view(
        trip(
            **FAILED,
            cancelled_reason="PREREQUISITE",
            cancelled_text="Front field not clear during the warning",
            not_ready=["PREREQUISITE", "SETTLING", "HOLDOFF"],
        ),
        protective_clear=False,
    ),
    "Cancelled": view(
        trip(**FAILED, not_ready=["SETTLING"]),
        instant_states=(
            {"actionId": f"cancel-{O_ID}", "actionType": "cancelOrder", "actionStatus": "FINISHED"},
        ),
    ),
}


def test_there_are_fifteen_examples_and_a_view_for_each():
    assert set(contract.examples()) == set(VIEWS) and len(VIEWS) == 15


@pytest.mark.parametrize("title", list(VIEWS))
def test_each_contract_example_is_reproduced(title):
    assert vs.build_state(VIEWS[title], SITE) == strip_header(contract.examples()[title])


def test_the_real_aborted_message_also_carries_the_fault():
    """Plan 4.5 R2: the job is in FAULT there, so the real message follows contract 6.3 and carries
    AGV_FAULT and the FAULT reason, which the example leaves out. Mapping row 5 reads the same."""
    o = copy.deepcopy(VIEWS["Aborted"].order)
    o["not_ready"] = ["NOT_AUTO", "NOT_AT_HOME", "FAULT", "TROLLEY_PRESENT"]
    want = strip_header(contract.examples()["Aborted"])
    want["errors"].insert(
        1,
        {
            "errorType": "AGV_FAULT",
            "errorLevel": "CRITICAL",
            "errorReferences": [{"referenceKey": "code", "referenceValue": "AUTHORITY_LOST"}],
        },
    )
    want["errors"][2]["errorReferences"].insert(2, {"referenceKey": "reason", "referenceValue": "FAULT"})
    got = vs.build_state(view(o, panel_auto=False, line_state=5, line_code="AUTHORITY_LOST"), SITE)
    assert got == want


def test_loads_has_three_forms():
    assert vs.build_state(view(fields(trolley=ABSENT)), SITE)["loads"] == []
    assert vs.build_state(view(fields(trolley=PRESENT)), SITE)["loads"] == [
        {"loadType": "TROLLEY", "loadPosition": "rear"}
    ]
    assert "loads" not in vs.build_state(view(fields(trolley=UNKNOWN)), SITE)


def test_power_supply_is_the_fixed_placeholder():
    assert vs.build_state(view(fields()), SITE)["powerSupply"] == {"stateOfCharge": 0, "charging": False}


def test_a_missing_order_state_is_startup():
    body = vs.build_state(view(None), SITE)
    assert (
        body["operatingMode"] == "STARTUP" and body["orderId"] == "" and body["safetyState"]["fieldViolation"]
    )


@pytest.mark.parametrize("mode", [0, 4, 6])
def test_a_layer_change_is_startup(mode):
    assert vs.build_state(view(fields(), mode=mode), SITE)["operatingMode"] == "STARTUP"


@pytest.mark.parametrize(
    "over", [{"mode": 1}, {"layer_ready": False}, {"panel_valid": False}, {"panel_auto": False}]
)
def test_anything_else_is_manual(over):
    assert vs.build_state(view(fields(), **over), SITE)["operatingMode"] == "MANUAL"


def test_a_hold_at_a_stop_is_not_an_agv_hold():
    o = trip("RUNNING", node="ATT", seq=2)
    assert (
        vs.build_state(view(o, line_state=3, hold_cause="station", line_code="AT_STATION"), SITE)["errors"]
        == []
    )
    body = vs.build_state(view(o, line_state=3, hold_cause="field", line_code="FIELD_BLOCKED"), SITE)
    assert body["errors"][0]["errorType"] == "AGV_HOLD"
    assert {"referenceKey": "holdCause", "referenceValue": "field"} in body["errors"][0]["errorReferences"]


def test_an_estop_hold_reads_manual_on_the_display_field_only():
    body = vs.build_state(view(trip(), line_state=3, hold_cause="estop", line_code="ESTOP"), SITE)
    assert body["safetyState"]["activeEmergencyStop"] == "MANUAL"
    assert vs.build_state(view(trip()), SITE)["safetyState"]["activeEmergencyStop"] == "NONE"
