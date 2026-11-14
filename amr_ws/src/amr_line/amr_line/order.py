"""One station order's progress, and the settle timers (manuals/station-call-plan.md P2). Pure.

An order is a record, not an authority: FollowJob alone decides, and this file holds what it
decided in the terms of the interface contract (the action statuses, the last node reached, how
the order ended). Nothing here starts, resumes or stops anything.

    OrderRequest  what the MQTT bridge handed in, for exactly one tick
    OrderRun      one accepted order, kept after it ends (the station reads how it ended)

A PAIR (contract v1.2 proposal, owner 2026-11-11): one order for two MRU machines, closer first, named
"a+b" on the wire between the bridge and the job. Its waits, by node sequence id:
ATT 2, MW-a 4, MW-b 6, ME-b 8, ME-a 10, HOME 12 (the trip goes to b before it turns, so a is met twice).
Status keys: att, mw (MW-a), mw2 (MW-b), me2 (ME-b), me (ME-a). One machine keeps att, mw, me.

A BTU LAP (contract v1.3, owner 2026-11-13): one or two swap machines, the closer first, no U-turn. Its waits:
ATT 2, swap-a 4[, swap-b 6], HOME 6 or 8. Status keys att, mw (swap-a), mw2 (swap-b): OrderState has no swap
fields, so the swaps reuse the release fields (no amr_interfaces change); me and me2 are not in the plan.
    Settle        SETTLING: 5 s after anything that may have just removed a block on a waiting call
"""

import dataclasses
import math

WAITING, RUNNING, FINISHED, FAILED = "WAITING", "RUNNING", "FINISHED", "FAILED"

# Node sequence ids of contract section 2.
SEQ_HOME, SEQ_ATT, SEQ_MW, SEQ_ME, SEQ_END = 0, 2, 4, 6, 8
PAIR_SEP = "+"      # "MRU1+MRU3": the closer machine first. vda_order.PAIR_SEP is the same

# Wheel travel that counts as "the AGV moved at HOME". A PLACEHOLDER: checked against encoder noise
# at rest on the vehicle (plan P8). A person must press At home again after any more than this.
HOME_STILL_M = 0.02

# errorType and reason values: the contract's strings (sections 6.3 and 8).
OTHER_ORDER_ACTIVE = "OTHER_ORDER_ACTIVE"
MOBILE_ROBOT_NOT_AVAILABLE = "MOBILE_ROBOT_NOT_AVAILABLE"
START_NODE_OUT_OF_RANGE = "START_NODE_OUT_OF_RANGE"
NO_ROUTE_TO_TARGET = "NO_ROUTE_TO_TARGET"
DEPARTURE_REFUSED = "DEPARTURE_REFUSED"
VALIDATION_FAILURE = "VALIDATION_FAILURE"
CANCEL_REFUSED = "CANCEL_REFUSED"
NO_ORDER_TO_CANCEL = "NO_ORDER_TO_CANCEL"

NOT_AUTO = "NOT_AUTO"
NOT_AT_HOME = "NOT_AT_HOME"
LOCALIZATION_NOT_READY = "LOCALIZATION_NOT_READY"
TAPE_NOT_SEEN = "TAPE_NOT_SEEN"
FAULT = "FAULT"
TORQUE_TIMEOUT = "TORQUE_TIMEOUT"
TROLLEY_PRESENT = "TROLLEY_PRESENT"
TROLLEY_UNKNOWN = "TROLLEY_UNKNOWN"
REAR_FIELD_NOT_CLEAR = "REAR_FIELD_NOT_CLEAR"
REAR_FIELD_UNKNOWN = "REAR_FIELD_UNKNOWN"
PREREQUISITE = "PREREQUISITE"
SITE_NOT_LIVE = "SITE_NOT_LIVE"
LOCAL_TRIP = "LOCAL_TRIP"
SETTLING = "SETTLING"
HOLDOFF = "HOLDOFF"
ROUTE = "ROUTE"
MACHINE = "MACHINE"

NO_TROLLEY = "NO_TROLLEY"
TROLLEY_STILL_ON = "TROLLEY_STILL_ON"
WARNING_CANCELLED = "WARNING_CANCELLED"


@dataclasses.dataclass(frozen=True)
class OrderRequest:
    order_id: str
    machine: str        # "MRU3", or a pair "MRU1+MRU3"

    @property
    def machines(self):
        return tuple(self.machine.split(PAIR_SEP))


def wait_plan(attach, recs):
    """[(node, status key, sequence id)] of an order's waits, in sequence order. recs: the machine
    records ({"release", "take"}, or {"swap"} for a BTU lap) in the order's order, the closer first."""
    if all("swap" in r for r in recs):
        keys = ("mw", "mw2")[: len(recs)]
        swaps = [(r["swap"], key, SEQ_MW + 2 * k) for k, (r, key) in enumerate(zip(recs, keys, strict=True))]
        return [(attach, "att", SEQ_ATT)] + swaps
    if len(recs) == 1:
        return [(attach, "att", SEQ_ATT), (recs[0]["release"], "mw", SEQ_MW), (recs[0]["take"], "me", SEQ_ME)]
    a, b = recs
    return [(attach, "att", 2), (a["release"], "mw", 4), (b["release"], "mw2", 6),
            (b["take"], "me2", 8), (a["take"], "me", 10)]


class OrderRun:
    """One accepted order. HOME-node reached on acceptance; the waits as the trip goes."""

    def __init__(self, req, home, attach, recs):
        self.order_id, self.machine = req.order_id, req.machine
        self.active, self.departed = True, False
        self.home = home
        self.last_node_id, self.last_node_seq = home, SEQ_HOME
        plan = wait_plan(attach, recs)
        # node -> (key into status, sequence id). Contract section 2 (one machine) or the pair rows.
        self._nodes = {node: (key, seq) for node, key, seq in plan}
        self.status = {key: WAITING for _node, key, _seq in plan}
        self.seq_end = plan[-1][2] + 2
        self.cancelled_reason = self.cancelled_text = ""
        self.aborted_reason = self.aborted_text = ""

    @property
    def live_in_warning(self):
        return self.active and not self.departed

    def action(self, sid):
        """The action key of a node ("att", "mw", "me"; a pair also "mw2", "me2"), or "" elsewhere."""
        return self._nodes[sid][0] if sid in self._nodes else ""

    def at_rest(self, sid):
        """Stopped at an order node: the wait is RUNNING, and this is the last node reached."""
        if sid in self._nodes:
            key, seq = self._nodes[sid]
            self.status[key] = RUNNING
            self.last_node_id, self.last_node_seq = sid, seq

    def left(self, sid):
        """The warning ended and the AGV moves off: FINISHED, not at the press."""
        if sid in self._nodes:
            self.status[self._nodes[sid][0]] = FINISHED

    def reached_home(self):
        self.last_node_id, self.last_node_seq = self.home, self.seq_end
        self.active = False

    def fail(self):
        """The order ended before its waits were done."""
        for key, value in self.status.items():
            if value != FINISHED:
                self.status[key] = FAILED
        self.active = False


class Settle:
    """SETTLING. The window restarts on each event that may have just removed a block: the selector
    entering AUTO, a Reset edge, the trolley going absent, the rear or front field going clear (all
    seen here, from the inputs), and a web Clear, a local call cancel, a mission selection, arrival
    at home, a warning ended by a cancel or cancelOrder (FollowJob calls restart()). It also runs from
    the first tick, because the selector's history is unknown then. Clock-fed: monotonic seconds."""

    def __init__(self, settle_s):
        self.settle_s = float(settle_s)
        self.until = math.inf  # before the first tick: settling
        self._seen = False
        self._auto = self._front = self._rear = self._trolley = None

    def restart(self, now):
        if now is None:  # before the first tick: it restarts there anyway
            return
        self.until = float(now) + self.settle_s

    def update(self, now, auto, reset_edge, trolley, rear_clear, field_clear):
        hit = (
            not self._seen
            or reset_edge
            or (auto and not self._auto)
            or (trolley == "absent" and self._trolley != "absent")
            or (rear_clear is True and self._rear is not True)
            or (field_clear is True and self._front is not True)
        )
        self._seen = True
        self._auto, self._trolley, self._rear, self._front = auto, trolley, rear_clear, field_clear
        if hit:
            self.restart(now)

    def settling(self, now):
        return now < self.until


def wheels_moved(counts, base, counts_per_rev, wheel_dia_m, limit_m=HOME_STILL_M):
    """True if ANY wheel's count is more than limit_m of wheel travel from `base`. Per wheel, not a
    mean of signed travel: a pivot adds about nothing to the distance along the tape, and is exactly
    what this must catch."""
    per_count = math.pi * wheel_dia_m / counts_per_rev
    return any(abs(c - b) * per_count > limit_m for c, b in zip(counts, base, strict=True))
