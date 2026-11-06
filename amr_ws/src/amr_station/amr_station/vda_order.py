"""Station orders: parse, contract checks 0 to 4, the canonical order of a machine. Pure.

The interface contract is embedded at the end of manuals/station-call-plan.md. This is a subset of
VDA5050 3.0.0 and is NOT compliant (contract section 10). The job runs checks 5 to 10: this file only
decides whether a message is a well-formed, fresh order for this AGV. The orderId is opaque here: the
machine comes from the nodes, through the site mission, never from the id.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import re

MAX_BYTES = 64 * 1024
FRESH_WINDOW_S = 5.0  # contract section 8, check 4: the AGV's own monotonic clock
REQUIRED = (
    "headerId",
    "timestamp",
    "version",
    "manufacturer",
    "serialNumber",
    "orderId",
    "orderUpdateId",
    "seenStateHeaderId",
    "nodes",
    "edges",
)
ID_RE = re.compile(r"\S{1,128}")  # the service argument splits on white space

# Outcomes of check_order.
DISCARD, IGNORE, REFUSE, ACCEPT = "discard", "ignore", "refuse", "accept"
VALIDATION_FAILURE = "VALIDATION_FAILURE"
INVALID_ORDER_ACTION = "INVALID_ORDER_ACTION"
SAME_ORDER_UPDATE_ID = "SAME_ORDER_UPDATE_ID"
STALE_ORDER = "STALE_ORDER"


@dataclasses.dataclass(frozen=True)
class Result:
    outcome: str
    order_id: str = ""
    machine: str = ""
    error: str = ""
    reason: str = ""


def machines(site) -> dict[str, tuple[str, str]]:
    """The machines an order can name: {machine: (release node, take node)}. A swap machine (BTU) has
    no release, so it is not among them: BTU trips stay on the AGV's own screen."""
    out = {}
    for row in site["GROUPS"].values():
        for mc, rec in row["machines"].items():
            if "release" in rec and "take" in rec:
                out[mc] = (rec["release"], rec["take"])
    return out


def _wait(order_id: str, suffix: str) -> dict:
    return {
        "actionId": f"{order_id}:{suffix}",
        "actionType": "waitForTrigger",
        "blockingType": "HARD",
        "actionParameters": [{"key": "triggerType", "value": ["LOCAL"]}],
    }


def canonical_order(site, machine: str, order_id: str) -> dict:
    """The exact nodes and edges of contract section 2, from the mission's home and attach."""
    home, att = site["HOME"], site["ATTACH"]
    release, take = machines(site)[machine]
    node = lambda nid, seq, actions: {"nodeId": nid, "sequenceId": seq, "released": True, "actions": actions}  # noqa: E731
    edge = lambda a, b, seq: {"edgeId": f"{a}:{b}", "sequenceId": seq, "released": True, "actions": []}  # noqa: E731
    return {
        "nodes": [
            node(home, 0, []),
            node(att, 2, [_wait(order_id, "ATT")]),
            node(release, 4, [_wait(order_id, "MW")]),
            node(take, 6, [_wait(order_id, "ME")]),
            node(home, 8, []),
        ],
        "edges": [edge(home, att, 1), edge(att, release, 3), edge(release, take, 5), edge(take, home, 7)],
    }


class StateRing:
    """Our own `state` sends of the last FRESH_WINDOW_S: (headerId, monotonic). Check 4: an order
    held in a TCP buffer through a Wi-Fi drop names a state older than this and is refused. No clock
    comparison across machines."""

    def __init__(self, window_s: float = FRESH_WINDOW_S) -> None:
        self.window_s = window_s
        self._sent: collections.deque = collections.deque()

    def sent(self, header_id: int, now: float) -> None:
        self._sent.append((header_id, now))
        self._trim(now)

    def _trim(self, now: float) -> None:
        while self._sent and now - self._sent[0][1] > self.window_s:
            self._sent.popleft()

    def fresh(self, header_id, now: float) -> bool:
        self._trim(now)
        return any(h == header_id for h, _t in self._sent)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _structure_only(items: list) -> list:
    """Nodes or edges without their actions: what the shape check compares."""
    return [{k: v for k, v in it.items() if k != "actions"} if isinstance(it, dict) else it for it in items]


def _find_machine(site, nodes) -> str | None:
    if not isinstance(nodes, list) or len(nodes) != 5 or not all(isinstance(n, dict) for n in nodes):
        return None
    pair = (nodes[2].get("nodeId"), nodes[3].get("nodeId"))
    return next((mc for mc, nodes_of in machines(site).items() if nodes_of == pair), None)


def check_order(
    payload: bytes,
    retained: bool,
    *,
    manufacturer: str,
    serial: str,
    site,
    state_order_id: str,
    state_machine: str,
    ring: StateRing,
    now: float,
) -> Result:
    """Contract checks 0 to 4, in order. The first failure ends it."""
    if retained:  # check 0
        return Result(DISCARD)
    # check 1
    if len(payload) > MAX_BYTES:
        return Result(REFUSE, error=VALIDATION_FAILURE, reason="TOO_LARGE")
    try:
        doc = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return Result(REFUSE, error=VALIDATION_FAILURE, reason="JSON")
    if not isinstance(doc, dict):
        return Result(REFUSE, error=VALIDATION_FAILURE, reason="JSON")
    order_id = doc.get("orderId") if isinstance(doc.get("orderId"), str) else ""
    bad = lambda reason: Result(REFUSE, order_id=order_id, error=VALIDATION_FAILURE, reason=reason)  # noqa: E731
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        return bad(f"MISSING_{missing[0]}")
    if doc["manufacturer"] != manufacturer or doc["serialNumber"] != serial:
        return bad("NOT_THIS_AGV")
    if not isinstance(doc["version"], str) or not doc["version"].startswith("3."):
        return bad("VERSION")
    if (
        not ID_RE.fullmatch(order_id)
        or not _is_int(doc["orderUpdateId"])
        or not _is_int(doc["seenStateHeaderId"])
        or not isinstance(doc["nodes"], list)
        or not isinstance(doc["edges"], list)
    ):
        return bad("FIELD_TYPE")
    # check 2
    if order_id == state_order_id:
        want = canonical_order(site, state_machine, order_id) if state_machine in machines(site) else None
        if want is not None and doc["nodes"] == want["nodes"] and doc["edges"] == want["edges"]:
            return Result(IGNORE, order_id=order_id)
        return Result(REFUSE, order_id=order_id, error=SAME_ORDER_UPDATE_ID, reason="CONTENT")
    # check 3
    if doc["orderUpdateId"] != 0:
        return bad("ORDER_UPDATE_ID")
    machine = _find_machine(site, doc["nodes"])
    if machine is None:
        return bad("SHAPE")
    want = canonical_order(site, machine, order_id)
    if _structure_only(doc["nodes"]) != _structure_only(want["nodes"]) or doc["edges"] != want["edges"]:
        return bad("SHAPE")
    if doc["nodes"] != want["nodes"]:
        return Result(REFUSE, order_id=order_id, error=INVALID_ORDER_ACTION, reason="ACTION")
    # check 4
    if not ring.fresh(doc["seenStateHeaderId"], now):
        return Result(REFUSE, order_id=order_id, error=STALE_ORDER, reason="SEEN_STATE_HEADER")
    return Result(ACCEPT, order_id=order_id, machine=machine)
