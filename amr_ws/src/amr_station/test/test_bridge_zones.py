"""The bridge's side of the RELEASE zone CLUSTER (contract v1.6 section 13): responses in, the job's
heartbeat, and state.zoneRequests out - which must never read as "released" by accident (13.5)."""

import json

import contract
from test_vda_state import fields

from amr_station import bridge_core as bc
from amr_station import vda_state as vs

SITE = contract.site()
RID = "STU8-20261125T081500:CLUSTER:1"


def core():
    return bc.BridgeCore(SITE, "gvi", "agv9")


def resp(*rows, serial="agv9", **over):
    doc = {"headerId": 1, "timestamp": "T", "version": "3.0.0", "manufacturer": "gvi", "serialNumber": serial,
           "responses": [{"requestId": r, "grantType": g} for r, g in rows]}
    doc.update(over)
    return json.dumps(doc).encode()


def zfields(capable=True, rows=(), error=("", ""), **over):
    return fields(
        zone_capable=capable,
        zone_request_ids=[r[0] for r in rows],
        zone_ids=["CLUSTER" for _ in rows],
        zone_set_ids=["SITE103-TRAFFIC-1" for _ in rows],
        zone_statuses=[r[1] for r in rows],
        zone_error_type=error[0],
        zone_error_request_id=error[1],
        **over,
    )


def body(c, now):
    return vs.build_state(c.view(now), SITE)


# -- responses in ---------------------------------------------------------------------------------
def test_responses_become_zone_verbs():
    c = core()
    assert c.on_responses(resp((RID, "GRANTED"), ("x:CLUSTER:2", "QUEUED")), False) == [
        ("zone", RID, "GRANTED"), ("zone", "x:CLUSTER:2", "QUEUED")]


def test_retained_foreign_or_malformed_responses_do_nothing():
    c = core()
    assert c.on_responses(resp((RID, "GRANTED")), True) == []               # retain flag set: discarded
    assert c.on_responses(resp((RID, "GRANTED"), serial="agv1"), False) == []
    assert c.on_responses(b"{not json", False) == []
    assert c.on_responses(resp((RID, "MAYBE"), ("", "GRANTED"), ("a b", "GRANTED")), False) == []
    assert c.on_responses(json.dumps({"manufacturer": "gvi", "serialNumber": "agv9"}).encode(), False) == []


def test_the_heartbeat_goes_once_a_second_and_only_with_the_link_ready():
    c = core()
    assert not c.link_beat(10.0, False)
    assert c.link_beat(10.0, True)
    assert not c.link_beat(10.5, True)
    assert c.link_beat(11.0, True)
    assert not c.link_beat(20.0, False)


# -- state.zoneRequests out -------------------------------------------------------------------------
def test_not_zone_capable_leaves_the_key_out_and_reads_as_v1_5():
    c = core()
    c.on_order_state(zfields(capable=False), 1.0)
    assert "zoneRequests" not in body(c, 1.0)
    c.on_order_state(fields(), 2.0)                                          # an OrderState with no zone fields
    assert "zoneRequests" not in body(c, 2.0)


def test_capable_reports_the_entries_and_an_empty_list():
    c = core()
    c.on_order_state(zfields(), 1.0)
    assert body(c, 1.0)["zoneRequests"] == []
    c.on_order_state(zfields(rows=[(RID, "GRANTED")]), 2.0)
    assert body(c, 2.0)["zoneRequests"] == [{"requestId": RID, "requestType": "ACCESS", "zoneId": "CLUSTER",
                                             "zoneSetId": "SITE103-TRAFFIC-1", "requestStatus": "GRANTED"}]


def test_a_stale_order_state_keeps_the_last_known_entries():
    c = core()
    c.on_order_state(zfields(rows=[(RID, "GRANTED")]), 1.0)
    b = body(c, 1.0 + bc.ORDER_STATE_MAX_AGE_S + 5.0)        # the line layer silent: the order fields age out
    assert b["operatingMode"] == "STARTUP" or b["orderId"] == ""
    assert [r["requestId"] for r in b["zoneRequests"]] == [RID]


def test_a_field_less_order_state_never_empties_the_list():
    # a stale amr_interfaces build on a restarted line layer: the fields are dropped, the grant is not
    c = core()
    c.on_order_state(zfields(rows=[(RID, "GRANTED")]), 1.0)
    c.on_order_state(fields(), 2.0)
    assert [r["requestId"] for r in body(c, 2.0)["zoneRequests"]] == [RID]


def test_once_capable_a_holder_that_loses_its_polygon_still_reports_a_list():
    c = core()
    c.on_order_state(zfields(rows=[(RID, "GRANTED")]), 1.0)
    c.on_order_state(zfields(capable=False, rows=[(RID, "GRANTED")]), 2.0)
    assert [r["requestId"] for r in body(c, 2.0)["zoneRequests"]] == [RID]
    c.on_order_state(zfields(capable=False), 3.0)            # released for real, by the job
    assert body(c, 3.0)["zoneRequests"] == []


def test_zone_errors_reach_the_station():
    c = core()
    c.on_order_state(zfields(rows=[(RID, "REVOKED")], error=("ZONE_RELEASE_LOST", RID)), 1.0)
    errs = [e for e in body(c, 1.0)["errors"] if e["errorType"].startswith("ZONE_")]
    assert errs == [{"errorType": "ZONE_RELEASE_LOST", "errorLevel": "CRITICAL",
                     "errorReferences": [{"referenceKey": "requestId", "referenceValue": RID}]}]
    c.on_order_state(zfields(rows=[(RID, "REQUESTED")], error=("ZONE_REQUEST_REJECTED", RID)), 2.0)
    [e] = [e for e in body(c, 2.0)["errors"] if e["errorType"].startswith("ZONE_")]
    assert e["errorType"] == "ZONE_REQUEST_REJECTED" and e["errorLevel"] == "WARNING"


def test_a_traffic_hold_is_an_agv_hold():
    c = core()
    c.on_order_state(zfields(rows=[(RID, "REQUESTED")]), 1.0)
    b = vs.build_state(c.view(1.0, line_state=vs.LINE_HOLD, hold_cause="traffic"), SITE)
    [e] = [e for e in b["errors"] if e["errorType"] == "AGV_HOLD"]
    assert {"referenceKey": "holdCause", "referenceValue": "traffic"} in e["errorReferences"]
