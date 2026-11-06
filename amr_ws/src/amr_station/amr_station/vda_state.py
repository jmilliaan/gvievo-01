"""The `state` and `connection` bodies of the station contract (sections 3, 5, 6, 7). Pure.

A subset of VDA5050 3.0.0, NOT compliant (contract section 10). `build_state` takes one StateView, the
newest of each ROS input, and returns the body without its header fields: the bridge publishes when the
body changed or 1 s has passed. Display fields say what the AGV believes. None of it is a permission.
"""

from __future__ import annotations

import dataclasses

from amr_station.vda_order import canonical_order

LINE_HOLD, LINE_FAULT = 3, 5  # LineState
# ModeState: a layer change or start under way.
MODE_STARTUP = (0, 4, 6)  # STARTING, TRANSITIONING, STOPPING
MODE_LINE = 7
TROLLEY_ABSENT, TROLLEY_PRESENT = 1, 2  # TrolleyState.state
FIELD_CLEAR = 1  # TrolleyState.rear_field
LOAD = {"loadType": "TROLLEY", "loadPosition": "rear"}
ACTION_KEYS = (("att_status", "ATT"), ("mw_status", "MW"), ("me_status", "ME"))


@dataclasses.dataclass(frozen=True)
class StateView:
    """The newest of each input. order is OrderState's fields, or None when it is older than 3 s."""

    order: dict | None
    mode: int | None = None  # ModeState.mode
    layer_ready: bool = False
    panel_valid: bool = False
    panel_auto: bool = False
    line_state: int | None = None  # LineState.state
    hold_cause: str = ""
    line_code: str = ""
    field_fresh: bool = False  # MuxState
    protective_clear: bool = False
    refusal: dict | None = None  # the bridge's one slot: {type, order_id, reason}
    instant_states: tuple = ()  # [{actionId, actionType, actionStatus}]
    instant_errors: tuple = ()  # [{errorType, actionId, orderId}]


def operating_mode(v: StateView) -> str:
    if v.order is None or v.mode is None or v.mode in MODE_STARTUP:
        return "STARTUP"
    if v.mode == MODE_LINE and v.layer_ready and v.panel_valid and v.panel_auto:
        return "AUTOMATIC"
    return "MANUAL"


def _ref(*pairs) -> list:
    return [{"referenceKey": k, "referenceValue": str(val)} for k, val in pairs]


def _order_errors(o: dict, order_id: str) -> list:
    out = []
    if o.get("cancelled_reason"):
        e = {
            "errorType": "DEPARTURE_CANCELLED",
            "errorLevel": "WARNING",
            "errorReferences": _ref(("orderId", order_id), ("reason", o["cancelled_reason"])),
        }
        if o.get("cancelled_text"):
            e["errorDescription"] = o["cancelled_text"]
        out.append(e)
    if o.get("aborted_reason"):
        e = {
            "errorType": "TRIP_ABORTED",
            "errorLevel": "CRITICAL",
            "errorReferences": _ref(("orderId", order_id)),
        }
        if o.get("aborted_text"):
            e["errorDescription"] = o["aborted_text"]
        out.append(e)
    return out


def _start_refused(o: dict, order_id: str, site, machine_nodes) -> list:
    node, reason = o.get("start_refused_node", ""), o.get("start_refused_reason", "")
    if not reason or not order_id:
        return []
    suffix = {site["ATTACH"]: "ATT", machine_nodes[0]: "MW", machine_nodes[1]: "ME"}.get(node)
    if suffix is None:
        return []
    return [
        {
            "errorType": "START_REFUSED",
            "errorLevel": "WARNING",
            "errorReferences": _ref(
                ("nodeId", node), ("actionId", f"{order_id}:{suffix}"), ("reason", reason)
            ),
        }
    ]


def _errors(v: StateView, site) -> list:
    o = v.order or {}
    order_id = o.get("order_id", "")
    out = _order_errors(o, order_id)
    if v.line_state == LINE_FAULT:
        out.append(
            {
                "errorType": "AGV_FAULT",
                "errorLevel": "CRITICAL",
                "errorReferences": _ref(("code", v.line_code)),
            }
        )
    if o and not o.get("active") and o.get("not_ready"):
        out.append(
            {
                "errorType": "NOT_READY",
                "errorLevel": "WARNING",
                "errorReferences": _ref(*[("reason", r) for r in o["not_ready"]]),
            }
        )
    if v.refusal:
        out.append(
            {
                "errorType": v.refusal["type"],
                "errorLevel": "WARNING",
                "errorReferences": _ref(
                    ("orderId", v.refusal["order_id"]), ("orderUpdateId", 0), ("reason", v.refusal["reason"])
                ),
            }
        )
    if o and o.get("machine"):
        canon = canonical_order(site, o["machine"], order_id)
        out += _start_refused(o, order_id, site, (canon["nodes"][2]["nodeId"], canon["nodes"][3]["nodeId"]))
    if v.line_state == LINE_HOLD and v.hold_cause != "station":
        out.append(
            {
                "errorType": "AGV_HOLD",
                "errorLevel": "WARNING",
                "errorReferences": _ref(("holdCause", v.hold_cause), ("code", v.line_code)),
            }
        )
    for e in v.instant_errors:
        refs = [("actionId", e["actionId"])]
        if e["errorType"] != "INVALID_INSTANT_ACTION":
            refs.append(("orderId", e.get("orderId", "")))
        out.append({"errorType": e["errorType"], "errorLevel": "WARNING", "errorReferences": _ref(*refs)})
    return out


def build_state(v: StateView, site) -> dict:
    """The state body. No header fields: the bridge adds them when it publishes."""
    o = v.order or {}
    order_id = o.get("order_id", "")
    active = bool(o.get("active"))
    seq = int(o.get("last_node_seq", 0))
    nodes, edges = [], []
    if active and o.get("machine"):
        canon = canonical_order(site, o["machine"], order_id)
        nodes = [
            {"nodeId": n["nodeId"], "sequenceId": n["sequenceId"], "released": True}
            for n in canon["nodes"]
            if n["sequenceId"] > seq
        ]
        edges = [
            {"edgeId": e["edgeId"], "sequenceId": e["sequenceId"], "released": True}
            for e in canon["edges"]
            if e["sequenceId"] > seq
        ]
    actions = [
        {"actionId": f"{order_id}:{suffix}", "actionType": "waitForTrigger", "actionStatus": o[key]}
        for key, suffix in ACTION_KEYS
        if o.get(key)
    ]
    body = {
        "orderId": order_id,
        "orderUpdateId": 0,
        "lastNodeId": o.get("last_node_id", ""),
        "lastNodeSequenceId": seq,
        "nodeStates": nodes,
        "edgeStates": edges,
    }
    trolley = o.get("trolley")
    if trolley == TROLLEY_ABSENT:
        body["loads"] = []
    elif trolley == TROLLEY_PRESENT:
        body["loads"] = [dict(LOAD)]  # unknown: the key is left out (contract section 7)
    body.update(
        {
            "driving": bool(o.get("driving")),
            "actionStates": actions,
            "instantActionStates": [dict(s) for s in v.instant_states],
            # Fixed placeholders: no battery reading, no charge detection. The station ignores them.
            "powerSupply": {"stateOfCharge": 0, "charging": False},
            "operatingMode": operating_mode(v),
            "errors": _errors(v, site),
            "safetyState": {
                # Inferred from torque gone with the field clear, not read from the chain. Display only.
                "activeEmergencyStop": "MANUAL" if v.hold_cause == "estop" else "NONE",
                "fieldViolation": not (v.field_fresh and v.protective_clear)
                or o.get("rear_field") != FIELD_CLEAR,
            },
        }
    )
    return body


def connection_body(state: str) -> dict:
    return {"connectionState": state}
