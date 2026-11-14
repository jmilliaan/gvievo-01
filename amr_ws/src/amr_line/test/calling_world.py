"""TripWorld with station calling on (station call plan P2): the fake for the rear lidar lives here,
a test sets `trolley` and `rear_clear` directly. Starts at HOME, At home pressed, nothing in the way."""

from site_fixture import graph, site
from test_site_run import TripWorld, go_on, parked_at, spin

from amr_line import job as lj

__all__ = ["CallingWorld", "calling", "go_on", "parked_at", "settled", "spin", "to_stop", "waiting_call",
           "SETTLE", "HOLDOFF"]

SETTLE, HOLDOFF = 5.0, 15.0


class CallingWorld(TripWorld):
    JOB_ARGS = {"calling": True, "settle_s": SETTLE, "holdoff_s": HOLDOFF, "order_torque_wait_s": 2.0}

    def __init__(self, m, g):
        self.trolley, self.rear_clear, self.loc_ready = "absent", True, True
        super().__init__(m, g)
        self.still = True
        self.job.at_home_pressed()

    def inputs(self, **over):
        over.setdefault("trolley", self.trolley)
        over.setdefault("rear_clear", self.rear_clear)
        over.setdefault("loc_ready", self.loc_ready)
        return super().inputs(**over)

    def order(self, order_id="O1", machine="M1"):
        """One order and the tick that takes it."""
        assert self.job.order_request(order_id, machine)[0]
        return self.tick()

    def refusal(self):
        s = self.job.order_snapshot()
        return s["refusal_type"], s["refusal_reason"]

    def not_ready(self):
        return list(self.job.order_snapshot()["not_ready"])


def calling(**over):
    over.setdefault("trip_calls", 1)
    m = site(**over)
    return CallingWorld(m, graph(m))


def settled(**over):
    """A world past its start-up SETTLING: an order is accepted at once."""
    w = calling(**over)
    w.drive(SETTLE + 0.1)
    assert w.not_ready() == [], w.not_ready()
    return w


def waiting_call(w, machine="M1"):
    """A call already waiting on Run → Calls. With calling on, trip_call takes no new call (one queue, owner
    2026-11-13), but a call that was waiting is never removed: it is put straight into the queue here."""
    ok, msg = w.job.calls.call(machine, w.t)
    assert ok, msg


def to_stop(w, sid):
    """From an accepted order or trip, on to `sid`: START at each stop before it, trolley as needed."""
    order = ["ATT", "MW-1", "ME-1"]
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    for stop in order:
        if stop == "ME-1":
            assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
            spin(w)
        parked_at(w, stop)
        if stop == sid:
            return
        w.trolley = "present" if stop in ("ATT", "ME-1") else "absent"
        w.drive(0.1)
        go_on(w)
    raise AssertionError(sid)
