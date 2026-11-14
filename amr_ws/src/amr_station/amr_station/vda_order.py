"""Station orders: parse, contract checks 0 to 4, the canonical order of a machine. Pure.

The interface contract is embedded at the end of manuals/station-call-plan.md. This is a subset of
VDA5050 3.0.0 and is NOT compliant (contract section 10). The job runs checks 5 to 10: this file only
decides whether a message is a well-formed, fresh order for this AGV. The orderId is opaque here: the
machine comes from the nodes, through the site mission, never from the id.

A pair (contract v1.2 PROPOSAL, owner 2026-11-11, not yet in the embedded contract text): two MRU machines
in one order, the closer (its release earlier in circuit order) first, 7 nodes:
HOME 0, ATT 2, MW-a 4, MW-b 6, ME-b 8, ME-a 10, HOME 12; action ids end in the node id (`:MW-1`). It is
handed to the job as the machine key "a+b". One machine keeps contract section 2 exactly.

BTU laps (contract v1.3, owner 2026-11-13): one or two swap machines, the closer first, no U-turn:
HOME 0, ATT 2, R2-j 4[, R2-k 6], HOME 6 or 8; action ids end in the node id (`:ATT`, `:R2-1`). Which shape an
order is comes from its node ids, never its node count alone: two BTUs and one MRU both have 5 nodes.

Facing machines (contract v1.4, 2026-11-14): a swap stop's OWN machine is the first the mission lists at it
(R2-k is BTU(25-k)); the others listed there face it (BTU(17-k)). A wait names its stop's machines in a
`machines` action parameter, own first, whenever they are not just the own machine: ["BTU15"],
["BTU23", "BTU15"]. A wait without one is the own machine, as in v1.3, and ["BTU23"] alone is refused. Two
machines at one stop are one wait, one START: the one-stop shape. An order still serves at most two machines.
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


PAIR_SEP = "+"  # the machine key of a pair: "MRU1+MRU3". order.PAIR_SEP (amr_line) is the same


def machines(site) -> dict[str, tuple[str, str]]:
    """The release-and-take machines an order can name: {machine: (release node, take node)}. Swap
    machines (BTU, contract v1.3) are swaps()."""
    out = {}
    for row in site["GROUPS"].values():
        for mc, rec in row["machines"].items():
            if "release" in rec and "take" in rec:
                out[mc] = (rec["release"], rec["take"])
    return out


def swaps(site) -> dict[str, str]:
    """Each swap stop's OWN machine: {machine: swap node}, the first the mission lists at the node (contract
    v1.3: R2-k is BTU(25-k)). A wait without a `machines` parameter names this one."""
    return {at[0]: node for node, at in stop_machines(site).items()}


def swap_machines(site) -> dict[str, str]:
    """Every swap machine an order can name: {machine: swap node}, the facing ones too (contract v1.4)."""
    return {mc: rec["swap"] for row in site["GROUPS"].values() for mc, rec in row["machines"].items()
            if rec.get("swap") is not None}


def stop_machines(site) -> dict[str, list[str]]:
    """{swap node: its machines in mission order}, the own machine first."""
    out: dict[str, list[str]] = {}
    for mc, node in swap_machines(site).items():
        out.setdefault(node, []).append(mc)
    return out


def is_swap(site, key: str) -> bool:
    """A valid_key() of swap machines (a BTU lap), not release and take."""
    return isinstance(key, str) and all(n in swap_machines(site) for n in key.split(PAIR_SEP))


def swap_stops(site, key: str) -> list[tuple[str, list[str]]]:
    """[(swap node, the key's machines there)] of a swap key, in key order: one entry per stop."""
    sw, out = swap_machines(site), []
    for mc in key.split(PAIR_SEP):
        if out and out[-1][0] == sw[mc]:
            out[-1][1].append(mc)
        else:
            out.append((sw[mc], [mc]))
    return out


def _group_of(site, machine: str):
    return next((name for name, g in site["GROUPS"].items() if machine in g["machines"]), None)


def _wait(order_id: str, suffix: str, names=None) -> dict:
    params = [{"key": "triggerType", "value": ["LOCAL"]}]
    if names is not None:
        params.append({"key": "machines", "value": list(names)})
    return {
        "actionId": f"{order_id}:{suffix}",
        "actionType": "waitForTrigger",
        "blockingType": "HARD",
        "actionParameters": params,
    }


def _circuit_pos(site, machine: str) -> dict:
    group = next(g for g in site["GROUPS"].values() if machine in g["machines"])
    items = site["CIRCUITS"][group["circuit"]]["items"]
    return {it["id"]: k for k, it in enumerate(items) if it["kind"] == "stop"}


def valid_key(site, key: str) -> bool:
    """A machine key an order can carry: one machine of machines() or swap_machines(), or a pair "a+b" of two
    different machines of one group and one kind. Release and take: a's release before b's and b's take
    before a's in circuit order. Swap: a's stop before b's, or one stop, a listed before b there (v1.4)."""
    names = key.split(PAIR_SEP) if isinstance(key, str) else []
    known, sw = machines(site), swap_machines(site)
    if len(names) == 1:
        return names[0] in known or names[0] in sw
    if len(names) != 2 or names[0] == names[1]:
        return False
    if all(n in sw for n in names):
        if _group_of(site, names[0]) != _group_of(site, names[1]):
            return False
        pos = _circuit_pos(site, names[0])
        a, b = sw[names[0]], sw[names[1]]
        if a == b:
            at = stop_machines(site)[a]
            return a in pos and at.index(names[0]) < at.index(names[1])
        return a in pos and b in pos and pos[a] < pos[b]
    if not all(n in known for n in names):
        return False
    group = [g for g in site["GROUPS"].values() if names[0] in g["machines"] or names[1] in g["machines"]]
    if len(group) != 1:
        return False
    pos = _circuit_pos(site, names[0])
    (ra, ta), (rb, tb) = known[names[0]], known[names[1]]
    if not all(n in pos for n in (ra, ta, rb, tb)):
        return False
    return pos[ra] < pos[rb] < pos[tb] < pos[ta]


def waits(site, key: str) -> list[tuple[str, str, int]]:
    """[(nodeId, action id suffix, sequenceId)] of the waits of a valid key, in sequence order.
    One machine: ATT, MW, ME (section 2). A pair: ATT, then the node id itself. Swap machines (v1.3): ATT,
    then each swap stop by its node id, once however many machines it serves (v1.4)."""
    att = site["ATTACH"]
    names = key.split(PAIR_SEP)
    if is_swap(site, key):
        return [(att, "ATT", 2)] + [(nd, nd, 4 + 2 * i) for i, (nd, _at) in enumerate(swap_stops(site, key))]
    known = machines(site)
    if len(names) == 1:
        release, take = known[key]
        return [(att, "ATT", 2), (release, "MW", 4), (take, "ME", 6)]
    (ra, ta), (rb, tb) = known[names[0]], known[names[1]]
    return [(att, "ATT", 2), (ra, ra, 4), (rb, rb, 6), (tb, tb, 8), (ta, ta, 10)]


def canonical_order(site, machine: str, order_id: str) -> dict:
    """The exact nodes and edges of contract section 2 from the mission's home and attach. `machine` is a
    valid_key(). A swap wait carries `machines` unless it serves just its stop's own machine (v1.4)."""
    home = site["HOME"]
    node = lambda nid, seq, actions: {"nodeId": nid, "sequenceId": seq, "released": True, "actions": actions}  # noqa: E731
    edge = lambda a, b, seq: {"edgeId": f"{a}:{b}", "sequenceId": seq, "released": True, "actions": []}  # noqa: E731
    w = waits(site, machine)
    named = {}
    if is_swap(site, machine):
        at_stop = stop_machines(site)
        named = {nd: at for nd, at in swap_stops(site, machine) if at != at_stop[nd][:1]}
    end = w[-1][2] + 2
    nodes = [node(home, 0, [])]
    nodes += [node(nid, seq, [_wait(order_id, sfx, named.get(nid))]) for nid, sfx, seq in w]
    nodes.append(node(home, end, []))
    pairs = zip(nodes, nodes[1:], strict=False)
    edges = [edge(a["nodeId"], b["nodeId"], a["sequenceId"] + 1) for a, b in pairs]
    return {"nodes": nodes, "edges": edges}


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


def _named(node: dict):
    """The `machines` value of a node's first action: a list of names, None when there is no such parameter,
    or False when it is there but not a list of strings (the action check then refuses it)."""
    acts = node.get("actions")
    act = acts[0] if isinstance(acts, list) and acts and isinstance(acts[0], dict) else {}
    params = act.get("actionParameters")
    params = params if isinstance(params, list) else []
    found = [p for p in params if isinstance(p, dict) and p.get("key") == "machines"]
    if not found:
        return None
    value = found[0].get("value")
    ok = isinstance(value, list) and value and all(isinstance(v, str) for v in value)
    return list(value) if ok else False


def _swap_names(site, node: dict) -> list[str] | None:
    """The machines a swap wait names: its `machines` if readable, else the stop's own machine. None if the
    node is no swap stop, or `machines` names one not at it, or names only the own machine (contract
    section 10: VALIDATION_FAILURE)."""
    nid = node.get("nodeId")
    at = stop_machines(site).get(nid) if isinstance(nid, str) else None
    if not at:
        return None
    names = _named(node)
    if not names:  # absent, or unreadable: the own machine, and the action compare decides
        return [at[0]]
    if names == [at[0]] or not all(n in at for n in names):
        return None
    return names


def _find_machine(site, nodes, pairs: bool = True) -> str | None:
    """The machine key the nodes name, by their ids and the swap waits' `machines`: one MRU 5 nodes, an MRU
    pair 7, one BTU stop 4 (one machine, or two facing at it), two BTU stops 5. Two waits after ATT only with
    `pairs` (the second is mw2_status). The caller then compares every node and edge against canonical_order
    of it."""
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        return None
    ids = [n.get("nodeId") for n in nodes]
    known = machines(site)
    find = lambda rel, take: next((mc for mc, nodes_of in known.items() if nodes_of == (rel, take)), None)  # noqa: E731
    keyed = lambda names: PAIR_SEP.join(names) if valid_key(site, PAIR_SEP.join(names)) else None  # noqa: E731
    if len(nodes) == 4:
        names = _swap_names(site, nodes[2])
        return keyed(names) if names else None
    if len(nodes) == 5:
        one = find(ids[2], ids[3])
        if one or not pairs:
            return one
        a, b = _swap_names(site, nodes[2]), _swap_names(site, nodes[3])
        return keyed(a + b) if a and b and len(a) == len(b) == 1 else None
    if len(nodes) == 7 and pairs:
        a, b = find(ids[2], ids[5]), find(ids[3], ids[4])
        key = f"{a}{PAIR_SEP}{b}" if a and b else None
        return key if key and valid_key(site, key) else None
    return None


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
    pairs: bool = True,
) -> Result:
    """Contract checks 0 to 4, in order. The first failure ends it. pairs=False: a 7-node order is
    a SHAPE refusal (the OrderState in use cannot carry a pair's statuses)."""
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
        want = canonical_order(site, state_machine, order_id) if valid_key(site, state_machine) else None
        if want is not None and doc["nodes"] == want["nodes"] and doc["edges"] == want["edges"]:
            return Result(IGNORE, order_id=order_id)
        return Result(REFUSE, order_id=order_id, error=SAME_ORDER_UPDATE_ID, reason="CONTENT")
    # check 3
    if doc["orderUpdateId"] != 0:
        return bad("ORDER_UPDATE_ID")
    machine = _find_machine(site, doc["nodes"], pairs)
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
