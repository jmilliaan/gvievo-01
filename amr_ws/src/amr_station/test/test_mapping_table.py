"""Contract 6.1 coded as written, fed by a real simulated trip from the job: the same table the
station runs. Each call state in order, and the ways an order ends."""

from calling_world import go_on, parked_at, settled, spin
from contract import call_state

from amr_line import job as lj
from amr_station import vda_state as vs

TROLLEY = {"absent": 1, "present": 2, "unknown": 0}
ORDER_ID = "O1"


def body(w):
    o = dict(w.job.order_snapshot())
    o.update(
        driving=w.job.state == lj.RUNNING, trolley=TROLLEY[w.trolley], rear_field=1 if w.rear_clear else 0
    )
    line = dict(line_state=w.job.state, hold_cause=w.job.hold_cause, line_code="X")
    v = vs.StateView(
        order=o,
        mode=7,
        layer_ready=True,
        panel_valid=True,
        panel_auto=True,
        field_fresh=True,
        protective_clear=True,
        **line,
    )
    return vs.build_state(v, w.m)


class Log:
    def __init__(self, w):
        self.w, self.seen, real = w, [], w.job.tick

        def tick(i):
            out = real(i)
            state = call_state(body(w), ORDER_ID, shown=bool(self.seen))
            if not self.seen or self.seen[-1] != state:
                self.seen.append(state)
            return out

        w.job.tick = tick


def test_a_full_trip_passes_each_call_state_in_order():
    w = settled()
    log = Log(w)
    w.order(ORDER_ID)
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    parked_at(w, "MW-1")
    w.trolley = "absent"
    w.drive(0.1)
    go_on(w)
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
    spin(w)
    parked_at(w, "ME-1")
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    w.tick()
    assert log.seen == [
        "TO_PICKUP",
        "AT_PICKUP",
        "TO_MACHINE",
        "AT_RELEASE",
        "TURNING",
        "AT_ATTACH",
        "RETURNING",
        "Closed",
    ]


def test_a_refused_start_does_not_change_the_call_state():
    w = settled()
    log = Log(w)
    w.order(ORDER_ID)
    parked_at(w, "ATT")
    w.press_start()
    b = body(w)
    assert [e["errorType"] for e in b["errors"]] == ["START_REFUSED"]
    assert log.seen == ["TO_PICKUP", "AT_PICKUP"]


def test_a_field_stop_while_moving_does_not_change_the_call_state():
    w = settled()
    w.order(ORDER_ID)
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.drive(0.5)
    w.tick(field_clear=False)
    b = body(w)
    assert call_state(b, ORDER_ID, True) == "TO_PICKUP" and b["errors"][0]["errorType"] == "AGV_HOLD"


def test_a_cancelled_warning_is_row_4():
    w = settled()
    w.order(ORDER_ID)
    w.tick(field_clear=False)
    assert call_state(body(w), ORDER_ID, True) == "QUEUED_NEW_ID"


def test_an_abort_is_row_5():
    w = settled()
    w.order(ORDER_ID)
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.drive(0.5)
    w.tick(panel_auto=False)
    w.tick(panel_auto=False)
    assert call_state(body(w), ORDER_ID, True) == "Aborted"


def test_a_cancel_order_in_the_warning_empties_the_arrays_with_no_departure_cancelled():
    w = settled()
    w.order(ORDER_ID)
    w.job.order_cancel(ORDER_ID, "c")
    w.tick()
    b = body(w)
    assert b["nodeStates"] == [] and not [e for e in b["errors"] if e["errorType"] == "DEPARTURE_CANCELLED"]


def test_a_new_process_is_row_2():
    w = settled()
    b = body(w)
    assert (
        b["orderId"] == ""
        and call_state(b, ORDER_ID, shown=True) == "Aborted"
        and call_state(b, ORDER_ID, False) == "QUEUED"
    )
