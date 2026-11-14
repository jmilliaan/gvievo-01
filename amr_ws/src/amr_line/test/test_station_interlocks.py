"""Station call plan P2, section 9.6: the rear lidar's interlocks. Pure, Inputs only."""

import pytest
from agv_core import alarms
from calling_world import CallingWorld, calling, go_on, parked_at, settled, spin, to_stop, waiting_call
from site_fixture import graph, site, swap_graph, swap_site
from test_site_run import one_call

from amr_base import hold_policy
from amr_line import job as lj


def refused(w):
    s = w.job.order_snapshot()
    return s["start_refused_node"], s["start_refused_reason"]


def test_off_the_lidar_is_never_read():
    def run(trolley):
        w = one_call()
        rows = []
        real = w.inputs

        def inputs(**over):
            over.setdefault("trolley", trolley)
            over.setdefault("rear_clear", trolley == "absent")
            return real(**over)

        w.inputs = inputs
        w.job.trip_call("M1", w.t)
        w.start()
        for _ in range(200):
            rows.append((w.tick(), w.job.state, w.job.reason))
        return rows

    assert run("absent") == run("present") == run("unknown")
    w = one_call()
    w.job.payload.trip_ended()
    w.job.trip_call("M1", w.t)
    w.press_start()
    assert w.job.state == lj.IDLE and "confirm the trolleys are off" in w.job.reason


@pytest.mark.parametrize(
    "attr, value, needle",
    [
        ("trolley", "present", "trolley"),
        ("trolley", "unknown", "trolley"),
        ("rear_clear", False, "rear"),
        ("rear_clear", None, "rear"),
    ],
)
def test_on_a_local_trip_leaves_only_with_no_trolley_and_rear_clear(attr, value, needle):
    w = calling()
    setattr(w, attr, value)
    w.tick()
    waiting_call(w, "M1")
    w.press_start()
    assert w.job.state == lj.IDLE and needle in w.job.reason, w.job.reason
    assert [m for m, _t in w.job.calls.pending] == ["M1"], "the call waits"
    setattr(w, attr, {"trolley": "absent", "rear_clear": True}[attr])
    w.tick()
    w.press_start()
    assert w.job.state == lj.ARMED, w.job.reason


def test_on_a_local_trip_needs_no_settling():
    w = calling()
    waiting_call(w, "M1")
    w.press_start()
    assert w.job.state == lj.ARMED, "a person is at the panel"


def test_on_the_confirmations_are_refused():
    w = calling()
    assert w.job.confirm_off() == (False, "the rear lidar decides")
    waiting_call(w, "M1")
    w.start()
    assert w.job.confirm_released() == (False, "the rear lidar decides")


def test_on_a_local_call_is_refused_while_an_order_is_served():
    w = settled()
    w.order()
    ok, msg = w.job.trip_call("M2", w.t)
    assert not ok and "station buttons" in msg


@pytest.mark.parametrize("machine", ["M1", "M2", "S1", "S2"])
def test_on_run_calls_takes_no_new_call_of_any_group(machine):
    """One queue (owner 2026-11-13): with calling on every call comes from the station buttons, MRU or BTU.
    trip_call is the authority, not the page."""
    m = swap_site(trip_calls=1)
    w = CallingWorld(m, swap_graph(m))
    refused = (False, "station calling is on: calls come from the station buttons")
    assert w.job.trip_call(machine, w.t) == refused
    assert w.job.calls.pending == []


def test_on_a_call_already_waiting_stays_until_served_or_cancelled():
    """"If it's not yet served by the AGV, don't remove it" (owner): the change refuses only new calls."""
    w = settled()
    waiting_call(w, "M1")
    w.drive(1.0)
    assert [m for m, _t in w.job.calls.pending] == ["M1"], "never removed"
    w.order("O1", "M2")
    assert w.refusal() == ("OTHER_ORDER_ACTIVE", "LOCAL_TRIP"), "orders still wait for it"
    assert w.job.trip_cancel("M1")[0], "a person may still cancel it"
    assert w.job.calls.pending == []


def test_off_run_calls_takes_calls_as_before():
    w = one_call()
    assert w.job.trip_call("M1", w.t) == (True, "M1 called (M: 1 of 1)")


def _at(w, sid):
    w.order()
    to_stop(w, sid)
    return w


@pytest.mark.parametrize("value, reason", [("absent", "NO_TROLLEY"), ("unknown", "TROLLEY_UNKNOWN")])
def test_start_at_attach_needs_a_trolley(value, reason):
    w = _at(settled(), "ATT")
    w.trolley = value
    w.drive(0.1)
    w.press_start()
    assert w.job.hold_cause == "station" and w.job.state == lj.HOLD and refused(w) == ("ATT", reason)
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    assert refused(w) == ("", "")


@pytest.mark.parametrize("value, reason", [("absent", "NO_TROLLEY"), ("unknown", "TROLLEY_UNKNOWN")])
def test_start_at_take_needs_a_trolley(value, reason):
    w = _at(settled(), "ME-1")
    w.trolley = value
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.HOLD and refused(w) == ("ME-1", reason)


@pytest.mark.parametrize("value, reason", [("present", "TROLLEY_STILL_ON"), ("unknown", "TROLLEY_UNKNOWN")])
def test_start_at_release_needs_no_trolley(value, reason):
    w = _at(settled(), "MW-1")
    w.trolley = value
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.HOLD and refused(w) == ("MW-1", reason)


def test_a_press_refused_for_a_prerequisite_reports_it():
    w = _at(settled(), "ATT")
    w.trolley = "present"
    w.drive(0.1)
    w.job.tick(w.inputs(start_edge=True, start_edge_t=w.t, field_clear=None))
    assert refused(w) == ("ATT", "PREREQUISITE")


def test_a_refused_press_is_not_remembered():
    w = _at(settled(), "ATT")
    w.trolley = "absent"
    w.drive(0.1)
    w.press_start()
    w.trolley = "present"
    w.drive(10.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "station"


def test_a_start_refusal_clears_on_the_next_press():
    w = _at(settled(), "ATT")
    w.trolley = "absent"
    w.drive(0.1)
    w.press_start()
    assert refused(w)[1] == "NO_TROLLEY"
    w.drive(1.0)
    assert refused(w)[1] == "NO_TROLLEY", "until the next press"
    w.trolley = "unknown"
    w.drive(0.1)
    w.press_start()
    assert refused(w)[1] == "TROLLEY_UNKNOWN"
    w.trolley = "present"
    w.drive(0.1)
    w.press_start()
    assert refused(w) == ("", "")


def test_trolley_lost_in_the_station_warning_cancels_it():
    w = _at(settled(), "ATT")
    w.trolley = "present"
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.ARMED
    w.trolley = "absent"
    assert w.until(lambda: w.job.state != lj.ARMED, 1.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "station"
    assert refused(w) == ("ATT", "WARNING_CANCELLED")


def test_a_swap_stop_has_no_interlock():
    w = calling()
    waiting_call(w, "M1")
    w.start()
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    # A stop whose work is a swap (BTU): whatever the trolley reads, START passes.
    parked_at(w, "MW-1")
    w.job.trip.plan = [dict(p, work=[("M1", "swap")]) if p["id"] == "MW-1" else p for p in w.job.trip.plan]
    w.trolley = "unknown"
    w.drive(0.1)
    go_on(w)


@pytest.mark.parametrize("where", ["midline", "tapeend", "tapeend_stopping", "tape_ended"])
def test_no_pivot_unless_the_trolley_is_absent(where):
    if where == "midline":
        w = settled()
        w.order()
        to_stop(w, "MW-1")
        w.trolley = "absent"
        w.drive(0.1)
        go_on(w)
        w.trolley = "present"
        assert w.until(lambda: w.job.state == lj.HOLD, 60.0), w.job.reason
        assert w.job.hold_cause == "trolley" and w.job.tape.uturn_req is None, w.job.reason
        w.trolley = "absent"
        w.drive(0.1)
        go_on(w)
        spin(w)
        assert w.job.tape.phase == "back"
        return
    m = site(
        trip_calls=1,
        uturn_points={},
        groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"}}}},
    )
    w = CallingWorld(m, graph(m, skip=("UT-M1", "UT-M2")))
    w.drive(5.2)
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    parked_at(w, "MW-1")
    w.trolley = "absent"
    w.drive(0.1)
    go_on(w)
    if where == "tapeend":
        w.trolley = "present"
        assert w.until(lambda: w.job.state == lj.HOLD, 90.0), (w.job.reason, w.S)
        assert w.job.hold_cause == "trolley" and w.job.tape.uturn_req is None, w.job.reason
        w.trolley = "absent"
        w.drive(0.1)
        go_on(w)
        assert w.until(lambda: (w.job.tape.uturn_req or {}).get("phase") == "approach", 5.0), w.job.reason
    elif where == "tapeend_stopping":
        assert w.until(lambda: (w.job.tape.uturn_req or {}).get("phase") == "approach", 90.0), w.job.reason
        assert w.until(lambda: w.job.tape.uturn_req["phase"] == "stopping", 30.0), (w.job.reason, w.S)
        w.trolley = "present"
        w.still, w.integrate = True, False
        assert w.until(lambda: w.job.state == lj.HOLD, 3.0), w.job.reason
        assert w.job.hold_cause == "trolley" and w.job.tape.uturn is None, "no spin"
        assert w.job.tape.uturn_req is not None, "the U-turn stays asked for"
        w.trolley = "absent"
        w.drive(0.1)
        w.press_start()
        assert w.until(lambda: w.job.tape.uturn is not None, 3.0), w.job.reason
    else:
        # A U-turn strip's "tape ended" under a following AGV: faults instead, with no pivot.
        w.drive(0.5)
        w.job.tape.trolley = "present"
        w.job.tape.route.uturn["lead_m"] = 1000.0
        assert w.job.tape.tape_ended() is False
        assert w.job.tape.fault and "trolley" in w.job.tape.fault
        assert w.job.tape.uturn_req is None


def test_a_rear_stop_reads_as_estop_and_waits_for_start():
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.drive(0.5)
    w.tick(torque_off=True, rear_clear=False)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop"
    assert not w.until(lambda: w.job.state == lj.RUNNING, 5.0, rear_clear=True)
    assert hold_policy.AUTO_CAUSES == ("field",)


def test_the_trolley_hold_has_its_device_and_its_code():
    assert hold_policy.hold_device("trolley") == "rear_scanner"
    assert alarms.hold_code("trolley") == "TROLLEY_AT_PIVOT"
