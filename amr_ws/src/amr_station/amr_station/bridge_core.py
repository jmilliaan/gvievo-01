"""The MQTT bridge's decisions, without ROS or a socket. Clock-fed; the node stays thin.

    on_order(payload, retained, now)    -> ("depart", order_id, machine) or None
    on_instant(payload, retained)       -> [("cancel", order_id, action_id)]
    on_order_state(fields)              the latest OrderState
    view(...)                           what vda_state.build_state needs
    state_due(body, now)                publish this body?

Motion authority: only what `depart` asks for, which the job may refuse. Nothing is stored for later: a
refused order is gone, and the station resends with a fresh seenStateHeaderId.
"""

from __future__ import annotations

import json

from amr_station import vda_order, vda_state

INSTANT_KEEP = 5
PUBLISH_PERIOD_S = 1.0
ORDER_STATE_MAX_AGE_S = 3.0  # older: STARTUP (plan 4.5 R3)


class BridgeCore:
    def __init__(self, site, manufacturer: str, serial: str) -> None:
        self.site, self.manufacturer, self.serial = site, manufacturer, serial
        self.ring = vda_order.StateRing()
        self.order: dict | None = None
        self.order_t: float | None = None
        self.refusal: dict | None = None  # one slot, the newest replaces, cleared on accept
        self.instant: list[dict] = []  # the last INSTANT_KEEP, oldest first
        self.instant_errors: list[dict] = []
        self._accepted = None  # the order id last seen accepted
        self._refusal_seq = None
        self._cancel_seq = None
        self._last_body = None
        self._last_t = None

    # -- order -------------------------------------------------------------------------------
    def refuse(self, etype: str, order_id: str, reason: str) -> None:
        self.refusal = {"type": etype, "order_id": order_id, "reason": reason}

    def on_order(self, payload: bytes, retained: bool, now: float):
        o = self.order or {}
        r = vda_order.check_order(
            payload,
            retained,
            manufacturer=self.manufacturer,
            serial=self.serial,
            site=self.site,
            state_order_id=o.get("order_id", ""),
            state_machine=o.get("machine", ""),
            ring=self.ring,
            now=now,
        )
        if r.outcome == vda_order.REFUSE:
            self.refuse(r.error, r.order_id, r.reason)
            return None
        return ("depart", r.order_id, r.machine) if r.outcome == vda_order.ACCEPT else None

    # -- instantActions: cancelOrder only -----------------------------------------------------
    def _find(self, action_id):
        return next((s for s in self.instant if s["actionId"] == action_id), None)

    def _keep(self, entry: dict) -> None:
        self.instant.append(entry)
        del self.instant[:-INSTANT_KEEP]

    def on_instant(self, payload: bytes, retained: bool) -> list:
        """Acts once per actionId. Anything that is not a well-formed cancelOrder has no effect."""
        if retained:
            return []
        try:
            doc = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return []
        if (
            not isinstance(doc, dict)
            or doc.get("manufacturer") != self.manufacturer
            or doc.get("serialNumber") != self.serial
            or not isinstance(doc.get("actions"), list)
        ):
            return []
        out = []
        for a in doc["actions"]:
            if not isinstance(a, dict) or not isinstance(a.get("actionId"), str) or not a["actionId"]:
                continue
            action_id = a["actionId"]
            if self._find(action_id) is not None:
                continue  # the stored result stands
            atype = str(a.get("actionType", ""))
            order_id = _cancel_target(a) if atype == "cancelOrder" else None
            if order_id is None or not vda_order.ID_RE.fullmatch(action_id):
                self._keep({"actionId": action_id, "actionType": atype, "actionStatus": "FAILED"})
                self.instant_errors.append({"errorType": "INVALID_INSTANT_ACTION", "actionId": action_id})
                continue
            self._keep(
                {"actionId": action_id, "actionType": atype, "actionStatus": "RUNNING", "_order": order_id}
            )
            out.append(("cancel", order_id, action_id))
        return out

    # -- the job's side -----------------------------------------------------------------------
    def on_order_state(self, fields: dict, now: float) -> None:
        self.order, self.order_t = fields, now
        order_id = fields.get("order_id", "")
        if order_id and order_id != self._accepted:
            if self._accepted is not None or fields.get("active"):
                self.refusal = None  # contract 6.3: until the next accepted order
                self.instant, self.instant_errors = [], []
            self._accepted = order_id
        seq = fields.get("refusal_seq")
        if seq != self._refusal_seq:
            self._refusal_seq = seq
            if seq and fields.get("refusal_type"):
                self.refuse(fields["refusal_type"], fields["refusal_order_id"], fields["refusal_reason"])
        cseq = fields.get("cancel_seq")
        if cseq != self._cancel_seq:
            self._cancel_seq = cseq
            self._cancel_result(fields)

    def _cancel_result(self, fields: dict) -> None:
        entry = self._find(fields.get("cancel_action_id", ""))
        if entry is None or entry["actionStatus"] != "RUNNING":
            return
        entry["actionStatus"] = fields.get("cancel_status") or "FAILED"
        error = fields.get("cancel_error")
        if error:
            self.instant_errors.append(
                {"errorType": error, "actionId": entry["actionId"], "orderId": entry.get("_order", "")}
            )

    # -- the state message --------------------------------------------------------------------
    def view(self, now: float, **inputs) -> vda_state.StateView:
        fresh = self.order_t is not None and now - self.order_t <= ORDER_STATE_MAX_AGE_S
        states = tuple({k: v for k, v in s.items() if not k.startswith("_")} for s in self.instant)
        return vda_state.StateView(
            order=self.order if fresh else None,
            refusal=self.refusal,
            instant_states=states,
            instant_errors=tuple(self.instant_errors),
            **inputs,
        )

    def state_due(self, body: dict, now: float) -> bool:
        """Within 200 ms of a change (the 10 Hz timer), and at least once per second."""
        if body == self._last_body and self._last_t is not None and now - self._last_t < PUBLISH_PERIOD_S:
            return False
        self._last_body, self._last_t = body, now
        return True


def _cancel_target(action: dict) -> str | None:
    params = action.get("actionParameters")
    if not isinstance(params, list):
        return None
    for p in params:
        if (
            isinstance(p, dict)
            and p.get("key") == "orderId"
            and isinstance(p.get("value"), str)
            and vda_order.ID_RE.fullmatch(p["value"])
        ):
            return p["value"]
    return None
