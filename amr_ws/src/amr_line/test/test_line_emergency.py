"""LINE and the panel's emergency (emergency-suite plan Part B E5, owner O-3, 2026-11-16).

The E-stop is known from DI09 (PanelState.emergency, Inputs.emergency): it never ends a run. A
RUNNING run holds as `estop`, the warning is cancelled, a field/chain/panel hold becomes `estop`;
Start is refused at once while it is not NORMAL; the Reset after the release does not abort a run
held as `estop` (any other Reset outside IDLE still does); Start after NORMAL resumes through the
warning at NORMAL speed. With the panel saying NORMAL a torque loss is the `chain` hold, not the
E-stop (WP-Y1 note, station-call O8). Without a fresh panel (Inputs.emergency None) the old torque
guess and its field race stand (test_mission_engine). Also WP-P7: a new run is refused on a low
supply. No ROS: runs on the dev box.
"""
import pytest
from agv_core import config as vehicle
from calling_world import settled
from test_line_authority import inputs, make, run, start
from test_mission_engine import World, _at_high
from test_site_run import one_call

from amr_line import autopilot, order
from amr_line import job as lj

ACTIVE, RESET_NEEDED, RESETTING, RESET_FAILED = 1, 2, 3, 4


# ---- what the E-stop does to a run -----------------------------------------------------------------

def test_the_panel_emergency_holds_a_running_run_as_estop_before_any_torque_report():
    job = run(make())
    assert job.tick(inputs(now=102.0, emergency=ACTIVE)) == (0.0, 0.0)
    assert job.state == lj.HOLD and job.hold_cause == "estop" and "emergency stop" in job.reason
    assert not job.wants_power()


def test_a_torque_loss_with_the_panel_normal_is_the_chain_and_waits_for_start():
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, emergency=0))
    assert job.state == lj.HOLD and job.hold_cause == "chain" and "not the E-stop" in job.reason
    for k in range(1, 200):
        job.tick(inputs(now=102.0 + 0.02 * k, emergency=0))
    assert job.state == lj.HOLD and job.hold_cause == "chain", "never by itself (station-call O8)"
    job.tick(inputs(now=106.1, emergency=0, start_edge=True, start_edge_t=106.05))
    assert job.state in (lj.ARMED, lj.RUNNING)


def test_the_chain_hold_becomes_estop_when_di09_catches_up():
    """DI09 is filtered over panel.estop_confirm_scans: the drive report can beat it."""
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, emergency=0))
    assert job.hold_cause == "chain"
    job.tick(inputs(now=102.02, torque_off=True, emergency=ACTIVE))
    assert job.hold_cause == "estop"


def test_the_chain_hold_becomes_the_field_when_the_field_is_reported_late():
    """Acceptance §7.8: a protective-field stop raises no banner and still resumes by itself."""
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, emergency=0))
    job.tick(inputs(now=102.02, torque_off=True, emergency=0))
    job.tick(inputs(now=102.1, torque_off=True, field_clear=False, emergency=0))
    assert job.hold_cause == "field" and job.auto_resume()
    t = 102.2
    while t < 106.0 and job.state == lj.HOLD:
        job.tick(inputs(now=t, emergency=0))
        t += 0.02
    assert job.state == lj.RUNNING, job.reason


def test_a_field_after_the_race_window_leaves_the_chain_hold():
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, emergency=0))
    job.tick(inputs(now=102.02, torque_off=True, emergency=0))
    job.tick(inputs(now=102.7, torque_off=True, field_clear=False, emergency=0))
    assert job.hold_cause == "chain"


def test_a_field_hold_is_relabelled_estop_and_never_resumes_by_itself():
    job = run(make())
    job.tick(inputs(now=102.0, torque_off=True, field_clear=False, emergency=0))
    assert job.hold_cause == "field" and job.wants_power()
    job.tick(inputs(now=102.1, torque_off=True, emergency=ACTIVE))
    assert job.hold_cause == "estop" and not job.wants_power()
    for k in range(200):
        job.tick(inputs(now=103.0 + 0.02 * k, emergency=0))
    assert job.state == lj.HOLD and job.hold_cause == "estop"


@pytest.mark.parametrize("emg", [ACTIVE, RESET_NEEDED, RESETTING, RESET_FAILED])
def test_start_is_refused_at_once_while_not_normal(emg):
    job = make()
    start(job, emergency=emg)
    assert job.state == lj.IDLE, "no warning, no ARMED"
    assert job.reason == f"Start refused: {lj.ESTOP_ACTIVE}" and job.refused == lj.ESTOP_ACTIVE
    job.tick(inputs(now=101.5, emergency=emg))
    assert job.reason == f"not ready: {lj.ESTOP_ACTIVE}"


def test_the_warning_is_cancelled_at_once_and_from_idle_takes_no_hold():
    w = World(None)
    w.press_start()
    assert w.job.state == lj.ARMED
    w.tick(emergency=ACTIVE)
    assert w.job.state == lj.IDLE and "E-stop active" in w.job.reason and not w.job.wants_power()


def test_the_held_run_is_held_until_normal_then_start_resumes_through_the_warning():
    w = World(None)
    w.start()
    w.drive(1.0)
    w.tick(emergency=ACTIVE)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop"
    w.drive(0.5, emergency=RESET_NEEDED, torque_off=True)
    # the E-stop released but not reset: Start refused, nothing sounds
    w.tick(emergency=RESET_NEEDED, torque_off=True, start_edge=True, start_edge_t=w.t)
    assert w.job.state == lj.HOLD and "E-stop active" in w.job.reason
    w.drive(0.2, emergency=0, torque_off=True)
    w.press_start()
    assert w.job.state == lj.ARMED, w.job.reason
    assert w.until(lambda: w.job.state == lj.RUNNING, 1.0), w.job.reason


def test_an_estop_during_the_resume_warning_goes_back_to_the_estop_hold():
    w = World(None)
    w.start()
    w.drive(0.5)
    w.tick(emergency=ACTIVE)
    w.drive(0.2, emergency=0)
    w.press_start()
    assert w.job.state == lj.ARMED
    w.tick(emergency=ACTIVE)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop"


# ---- O-3: the Reset after the release ----------------------------------------------------------------

def test_reset_in_an_estop_hold_keeps_the_trip_and_start_continues_it():
    """Owner O-3 (2026-11-16), overriding station-call O13 for this case: release, Reset, Start, and the
    trip goes on. test_site_run.test_reset_mid_trip_aborts_it keeps the other cases."""
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.drive(1.0)
    w.tick(emergency=ACTIVE)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop"
    w.tick(emergency=RESET_NEEDED, torque_off=True)
    w.tick(emergency=RESET_NEEDED, torque_off=True, reset_edge=True)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop" and w.job.trip is not None
    assert "ABORTED" not in w.job.trip_note
    w.drive(0.3, emergency=0, torque_off=True)
    w.press_start()
    assert w.until(lambda: w.job.state == lj.RUNNING, 1.0), w.job.reason
    assert w.job.trip is not None


def test_reset_during_the_resume_warning_goes_back_to_the_estop_hold():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.drive(1.0)
    w.tick(emergency=ACTIVE)
    w.drive(0.2, emergency=0)
    w.press_start()
    assert w.job.state == lj.ARMED
    w.tick(reset_edge=True)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop" and w.job.trip is not None


def test_reset_in_any_other_hold_still_aborts_the_trip():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.drive(1.0)
    w.tick(drives_fresh=False)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "drives"
    w.tick(reset_edge=True)
    assert w.job.state == lj.IDLE and w.job.trip is None and "ABORTED (reset)" in w.job.trip_note


def test_a_station_hold_stays_station_through_an_estop():
    """Station-call plan, E-stop during an order: parked at a stop the hold stays `station`."""
    job = run(make())
    job._hold("station", "parked")
    job.tick(inputs(now=102.0, emergency=ACTIVE))
    assert job.state == lj.HOLD and job.hold_cause == "station"


_ORDER_KEYS = ("order_id", "active", "departed", "att_status", "mw_status", "me_status", "last_node_id",
               "last_node_seq", "aborted_reason", "cancelled_reason")


def test_an_estop_hold_and_its_reset_keep_the_station_order_as_it_was():
    """For the station (gvievo-sta map_state, 2026-11-16): through the E-stop hold and the Reset the
    order keeps its id, stays active and departed, and no ATT/MW/ME status or node moves - so the
    station's Aborted row (empty nodeStates) never fires. Start then carries on with the same order."""
    w = settled()
    w.order("O1", "M1")
    assert w.until(lambda: w.job.state == lj.RUNNING, 3.0), w.job.reason
    w.drive(1.0)
    before = {k: w.job.order_snapshot()[k] for k in _ORDER_KEYS}
    assert before["active"] and before["departed"], before
    w.tick(emergency=ACTIVE)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "estop"
    w.tick(emergency=RESET_NEEDED, torque_off=True)
    w.tick(emergency=RESET_NEEDED, torque_off=True, reset_edge=True)
    w.drive(0.3, emergency=0, torque_off=True)
    assert {k: w.job.order_snapshot()[k] for k in _ORDER_KEYS} == before
    w.press_start()
    assert w.until(lambda: w.job.state == lj.RUNNING, 1.0), w.job.reason
    s = w.job.order_snapshot()
    assert s["order_id"] == "O1" and s["active"] and not s["aborted_reason"]


def test_an_estop_in_an_order_s_warning_cancels_the_departure_without_the_torque_latch():
    """With DI09 read, an E-stop during the order's pre-move warning cancels it at once
    (DEPARTURE_CANCELLED, reason PREREQUISITE) - no full horn cycle, no TORQUE_TIMEOUT latch. That latch
    is now the chain / stale-panel case: torque never came with the panel NORMAL or unknown."""
    w = settled()
    w.order("O1", "M1")
    assert w.job.state == lj.ARMED, w.job.reason
    w.tick(emergency=ACTIVE)
    s = w.job.order_snapshot()
    assert s["cancelled_reason"] == order.PREREQUISITE and lj.ESTOP_ACTIVE in s["cancelled_text"], s
    w.drive(0.5, emergency=ACTIVE)
    assert order.PREREQUISITE in w.not_ready() and order.TORQUE_TIMEOUT not in w.not_ready(), w.not_ready()


def test_a_low_supply_refuses_an_order_up_front():
    """WP-P7 for orders: NOT_READY PREREQUISITE, so the order is refused, not accepted and then
    cancelled in its warning (the physical Start is refused the same way)."""
    w = settled()
    low = (vehicle.MON_BUS_V_TRIP_LOW - 1.0, vehicle.MON_BUS_V_TRIP_LOW + 2.0)
    w.tick(supply_v=low)
    assert order.PREREQUISITE in w.not_ready(), w.not_ready()
    assert w.job.order_request("O1", "M1")[0]
    w.tick(supply_v=low)
    assert w.job.order is None and w.refusal() == (order.DEPARTURE_REFUSED, order.PREREQUISITE)
    assert w.job.state == lj.IDLE


def test_an_order_is_refused_while_not_normal():
    w = settled()
    assert w.job.order_request("O1", "M1")[0]
    w.tick(emergency=RESET_NEEDED)
    assert w.job.order is None and w.refusal() == (order.DEPARTURE_REFUSED, order.PREREQUISITE)
    assert w.job.state == lj.IDLE


# ---- speed and the ramp ------------------------------------------------------------------------------

def test_a_panel_estop_at_high_resumes_normal_even_with_the_field_seen_late():
    """The race (_estop_was_field) is only the stale-panel guess: with DI09 it is the E-stop."""
    w = _at_high()
    w.tick(emergency=ACTIVE, torque_off=True)
    assert w.job.hold_cause == "estop"
    w.drive(0.1, emergency=ACTIVE, torque_off=True, field_clear=False)
    w.drive(0.5, emergency=0, torque_off=True)
    w.tick(start_edge=True, start_edge_t=w.t)
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0), w.job.reason
    assert not w.job.tape.speed.high and "E-stop" in w.job.tape.speed.reason


def test_the_estop_hold_restarts_the_ramp_from_zero_acceleration():
    """The open no_jerk residual (autopilot._ramp keeps an acceleration when a step lands exactly on
    target): the hold path zeroes speed AND acceleration, so the resume builds from a = 0."""
    w = World(None)
    w.start()
    w.drive(1.0)
    w.job.f._a_rpm_s = 123.0  # a residual left by the ramp
    w.tick(emergency=ACTIVE)
    assert w.job.f._a_rpm_s == 0.0 and w.job.f._v_rpm == 0.0
    w.drive(0.2, emergency=0, torque_off=True)
    w.press_start()
    assert w.until(lambda: w.job.state == lj.RUNNING, 1.0)
    jerk_step = autopilot.config.RAMP_JERK_RPM_S2 * 0.02
    assert 0.0 <= w.job.f._a_rpm_s <= jerk_step + 1e-9, "built from zero at the jerk limit"


# ---- start-up refusal and the supply (WP-P7) ---------------------------------------------------------

def test_auto_resume_estop_true_is_refused():
    assert "refused" in lj.auto_resume_estop_refusal(True)
    assert lj.auto_resume_estop_refusal(False) == ""


def test_a_new_run_is_refused_on_a_low_supply():
    low = vehicle.MON_BUS_V_TRIP_LOW
    job = make()
    start(job, supply_v=(low - 1.0, low + 2.0))
    assert job.state == lj.IDLE and "battery too low" in job.reason and job.refused
    job = make()
    start(job, supply_v=(None, low + 2.0))  # one drive not read: no refusal on a missing reading
    assert job.state != lj.IDLE
    job = make()
    start(job, supply_v=())
    assert job.state != lj.IDLE


def test_a_low_supply_does_not_stop_a_running_vehicle():
    job = run(make())
    low = vehicle.MON_BUS_V_TRIP_LOW
    job.tick(inputs(now=102.0, supply_v=(low - 2.0, low - 2.0)))
    assert job.state == lj.RUNNING, "report and refusal only: the drives carry their own undervoltage"


def test_drive_status_bus_voltage_maps_to_supply_v():
    """NaN (not read) and 0 (a publisher that does not set the field: the sim, an older drive_node)
    are no reading, so they never refuse a run."""
    assert lj.bus_volts(48.25) == 48.25
    for v in (float("nan"), 0.0, -1.0, None, float("inf"), "x"):
        assert lj.bus_volts(v) is None, v
