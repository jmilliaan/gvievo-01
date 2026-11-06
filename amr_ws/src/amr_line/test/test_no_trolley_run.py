"""station.no_trolley_run (owner's decision, 2026-11-06). With no rear scanner the trolley and rear field
are unknown: on, they no longer block. A sensor that reports a trolley or a violated field still does. Off,
the rear checks stand as before. Pure, Inputs only."""

from unittest import mock

import pytest
from calling_world import SETTLE, CallingWorld, calling, go_on, parked_at, settled, spin
from site_fixture import graph, site

from amr_line import job as lj
from amr_line import order

UNKNOWN = {"trolley": "unknown", "rear_clear": None}


class NoTrolleyWorld(CallingWorld):
    JOB_ARGS = {**CallingWorld.JOB_ARGS, "no_trolley_run": True}


def on(**rear):
    m = site(trip_calls=1)
    w = NoTrolleyWorld(m, graph(m))
    for attr, value in {**UNKNOWN, **rear}.items():
        setattr(w, attr, value)
    w.drive(SETTLE + 0.1)
    return w


def off(**rear):
    w = calling()
    for attr, value in {**UNKNOWN, **rear}.items():
        setattr(w, attr, value)
    w.drive(SETTLE + 0.1)
    return w


# -- on ------------------------------------------------------------------------------------------
def test_on_the_unknowns_are_not_listed():
    assert on().not_ready() == []


def test_on_a_call_runs_a_whole_trip_with_the_rear_state_unknown():
    w = on()
    w.order()
    assert w.job.state == lj.ARMED and w.job._order_active(), w.job.reason
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    parked_at(w, "ATT")
    go_on(w)
    parked_at(w, "MW-1")
    go_on(w)
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0), (w.job.reason, w.S)
    spin(w)
    parked_at(w, "ME-1")
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 120.0), w.job.reason
    assert "served" in w.job.result


@pytest.mark.parametrize("trolley", ["unknown", "absent", "present"])
@pytest.mark.parametrize("stop", ["ATT", "MW-1"])
def test_on_no_stop_refuses_start_for_a_trolley(stop, trolley):
    w = on()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    parked_at(w, "ATT")
    if stop == "MW-1":
        go_on(w)
        parked_at(w, "MW-1")
    w.trolley = trolley
    w.drive(0.1)
    go_on(w)
    assert w.job.order_snapshot()["start_refused_reason"] == ""


@pytest.mark.parametrize(
    "rear, reason",
    [({"trolley": "present"}, order.TROLLEY_PRESENT), ({"rear_clear": False}, order.REAR_FIELD_NOT_CLEAR)],
    ids=["trolley present", "rear field violated"],
)
def test_on_a_sensor_that_reports_still_refuses(rear, reason):
    w = on(**rear)
    assert reason in w.not_ready()
    w.order()
    assert w.job.state == lj.IDLE
    assert w.refusal() == (order.DEPARTURE_REFUSED, reason)


def test_on_a_reported_trolley_stops_a_pivot_and_unknown_does_not():
    w = on()
    w.tick()
    assert w.job._pivot_trolley(w.inputs()) == "absent"
    w.trolley = "present"
    assert w.job._pivot_trolley(w.inputs()) == "present"


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"panel_auto": False}, order.NOT_AUTO),
        ({"sensor": {"has_track": False, "tracks": [], "nlcp": 0, "track_level": 0}}, order.TAPE_NOT_SEEN),
        ({"loc_ready": False}, order.LOCALIZATION_NOT_READY),
    ],
    ids=["not auto", "no tape", "localization"],
)
def test_on_the_other_checks_stay(over, reason):
    w = on()
    w.tick(**over)
    assert reason in w.job.order_snapshot()["not_ready"]


def test_on_settling_and_holdoff_stay():
    m = site(trip_calls=1)
    w = NoTrolleyWorld(m, graph(m))
    w.trolley, w.rear_clear = "unknown", None
    w.tick()
    assert order.SETTLING in w.not_ready()
    w = on()
    w.job._holdoff_until = w.t + 100.0
    w.tick()
    assert order.HOLDOFF in w.not_ready()


def test_on_the_front_field_still_cancels_the_warning():
    w = on()
    w.order()
    assert w.job.state == lj.ARMED
    w.tick(field_clear=False)
    assert w.job.state == lj.IDLE


def test_the_switch_needs_calling():
    assert lj.FollowJob(mock.MagicMock(), calling=False, no_trolley_run=True).no_trolley_run is False


# -- off -----------------------------------------------------------------------------------------
def test_off_the_unknowns_are_listed_and_refuse():
    w = off()
    assert w.not_ready() == [order.TROLLEY_UNKNOWN, order.REAR_FIELD_UNKNOWN]
    w.order()
    assert w.job.state == lj.IDLE
    assert w.refusal() == (order.DEPARTURE_REFUSED, order.TROLLEY_UNKNOWN)
    w.press_start()
    assert w.job.state == lj.IDLE and "rear lidar" in w.job.reason


def test_off_a_stop_still_needs_its_trolley():
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    parked_at(w, "ATT")
    w.press_start()
    assert w.job.state == lj.HOLD
    assert w.job.order_snapshot()["start_refused_reason"] == order.NO_TROLLEY


def test_off_unknown_is_not_read_as_absent_at_a_pivot():
    w = off()
    assert w.job._pivot_trolley(w.inputs()) == "unknown"
