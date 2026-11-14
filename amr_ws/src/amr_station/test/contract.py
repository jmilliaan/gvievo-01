"""The contract's own examples and call-state table, read from manuals/station-call-plan.md, so a
test cannot drift from the text both repos build to."""

import json
import os
import pathlib
import re

from agv_core import mission

ROOT = pathlib.Path(__file__).resolve().parents[4]
PLAN = (ROOT / "manuals" / "station-call-plan.md").read_text(encoding="utf-8")
HEADER = ("headerId", "timestamp", "version", "manufacturer", "serialNumber")
ORDER_ID = "MRU3-20261105T081530"


def examples() -> dict:
    """{title: message} for each state example of contract section 6.2."""
    part = PLAN.split("#### 6.2 State at each stage", 1)[1].split("#### 6.3 Errors", 1)[0]
    out = {}
    for title, body in re.findall(r"\*\*([^*\n]+?)\*\*\n\n```json\n(.*?)```", part, re.S):
        out[title.split(":")[0].split(" (")[0].strip()] = json.loads(body)
    return out


def contract_order() -> dict:
    part = PLAN.split("Order for MRU3:", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)```", part, re.S).group(1))


def contract_pair_order() -> dict:
    """The pair example of contract v1.2 section 2."""
    part = PLAN.split("Order for MRU1 and MRU3, a pair:", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)```", part, re.S).group(1))


def contract_btu_pair_order() -> dict:
    """The BTU pair example of contract v1.3 section 2."""
    part = PLAN.split("Order for BTU24 and BTU19, a BTU pair:", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)```", part, re.S).group(1))


def contract_cancel() -> dict:
    part = PLAN.split("### 4. instantActions", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)```", part, re.S).group(1))


def site():
    """site-103 under the home name the contract text uses. The vehicle's home moved to HOME-N2
    (right bay, 2026-11-06); the contract's examples, shared with the station side, still say HOME-N."""
    with open(os.path.join(mission.MISSION_DIR, "site-103.json")) as fh:
        return mission.parse_site(json.loads(fh.read().replace("HOME-N2", "HOME-N")))


def strip_header(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in HEADER}


def call_state(state: dict, order_id: str, shown: bool) -> str:
    """Contract 6.1 as written: the first matching row wins, one message only."""
    if state["orderId"] != order_id:
        return "Aborted" if shown else "QUEUED"
    actions = {a["actionId"]: a["actionStatus"] for a in state["actionStates"]}
    att, mw, me = (actions.get(f"{order_id}:{k}") for k in ("ATT", "MW", "ME"))
    if not state["nodeStates"]:
        if state["lastNodeSequenceId"] == 8:
            return "Closed"
        cancelled = any(
            e["errorType"] == "DEPARTURE_CANCELLED"
            and {"referenceKey": "orderId", "referenceValue": order_id} in e["errorReferences"]
            for e in state["errors"]
        )
        return "QUEUED_NEW_ID" if cancelled else "Aborted"
    return (
        "RETURNING"
        if me == "FINISHED"
        else "AT_ATTACH"
        if me == "RUNNING"
        else "TURNING"
        if mw == "FINISHED"
        else "AT_RELEASE"
        if mw == "RUNNING"
        else "TO_MACHINE"
        if att == "FINISHED"
        else "AT_PICKUP"
        if att == "RUNNING"
        else "TO_PICKUP"
    )
