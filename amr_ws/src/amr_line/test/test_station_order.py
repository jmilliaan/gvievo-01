"""Station call plan P2, section 9: the one automatic departure. Pure, Inputs only."""

import ast
import pathlib

import pytest
from calling_world import HOLDOFF, SETTLE, calling, go_on, parked_at, settled, spin, to_stop
from site_fixture import graph, site
from test_mission_engine import PER_REV
from test_site_run import TripWorld, one_call

from amr_line import job as lj

HERE = pathlib.Path(__file__).parent
JOB = HERE.parent / "amr_line" / "job.py"
NODE = HERE.parent / "amr_line" / "line_follow_node.py"


def snap(w):
    return w.job.order_snapshot()


def test_off_an_order_is_refused_and_nothing_is_latched():
    w = one_call()
    ok, msg = w.job.order_request("O1", "M1")
    assert not ok and "calling is off" in msg
    assert w.job.order_cancel("O1", "c")[0] is False
    for _ in range(100):
        assert w.tick() == (0.0, 0.0)
        assert w.job.state == lj.IDLE and w.job.trip is None and w.job.order is None


def test_an_order_at_home_goes_through_armed_with_no_start_edge():
    w = settled()
    assert w.order() == (0.0, 0.0)
    assert w.job.state == lj.ARMED and snap(w)["order_id"] == "O1" and snap(w)["active"]
    w.drive(0.3)
    assert w.job.state == lj.ARMED, "the warning runs its time"
    assert w.until(lambda: w.job.state == lj.RUNNING, 1.0), w.job.reason
    assert snap(w)["departed"]


def test_an_order_arms_the_same_warning_as_a_start():
    w = settled()
    w.order()
    assert w.job.wants_power() and w.job._premove["kind"] == "start"
    while w.job.state == lj.ARMED:
        assert w.tick() == (0.0, 0.0) or w.job.state == lj.RUNNING


def test_only_the_first_stop_is_automatic():
    w = settled()
    w.order()
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(30.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "station", "time moves nothing"
    w.job.order_request("O2", "M1")
    w.drive(1.0)
    assert w.job.state == lj.HOLD and w.job.hold_cause == "station", "nor a second order"
    go_on(w)


def test_a_refused_order_does_not_run_later():
    w = settled()
    w.job.order_request("O1", "M1")
    w.tick(field_clear=False)
    assert w.job.state == lj.IDLE and w.refusal()[0] == "DEPARTURE_REFUSED"
    w.drive(20.0)
    assert w.job.state == lj.IDLE and w.job.trip is None and w.job.order is None


def test_a_request_lives_for_one_tick():
    w = settled()
    w.job.order_request("O1", "M1")
    w.tick(panel_auto=False)
    assert w.job.state == lj.IDLE
    w.drive(SETTLE + 1.0)
    assert w.job.state == lj.IDLE and w.job.order is None, "the latch was emptied by that one tick"


@pytest.mark.parametrize("after", ["finish", "cancel", "replay"])
def test_the_same_order_id_never_starts_twice(after):
    w = settled()
    w.order()
    if after == "cancel":
        w.job.order_cancel("O1", "c")
        w.tick()
        assert w.job.state == lj.IDLE
    elif after == "replay":
        w.job.order_request("O1", "M1")
        w.tick()
        assert w.job.state == lj.ARMED and w.refusal() == ("", "")
    else:
        to_stop(w, "ME-1")
        w.trolley = "present"
        w.drive(0.1)
        go_on(w)
        assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
        w.trolley = "absent"
    if after != "replay":
        w.drive(SETTLE + 0.2)
        before = w.job.order
        w.job.at_home_pressed()
        w.drive(0.1)
        w.job.order_request("O1", "M1")
        w.tick()
        assert w.job.state in (lj.IDLE, lj.DONE) and w.job.order is before, "dropped"


def _check_cases():
    return [
        ("other_order", lambda w: w.order("O0"), {}, "OTHER_ORDER_ACTIVE", "O0"),
        ("local_trip", lambda w: w.job.trip_call("M1", w.t), {}, "OTHER_ORDER_ACTIVE", "LOCAL_TRIP"),
        ("not_auto", lambda w: None, {"panel_auto": False}, "MOBILE_ROBOT_NOT_AVAILABLE", "NOT_AUTO"),
        ("stale_panel", lambda w: None, {"panel_valid": False}, "MOBILE_ROBOT_NOT_AVAILABLE", "NOT_AUTO"),
        ("no_lease", lambda w: None, {"lease_allowed": 0}, "MOBILE_ROBOT_NOT_AVAILABLE", "NOT_AUTO"),
        ("not_at_home", lambda w: setattr(w, "S", 9.0), {}, "START_NODE_OUT_OF_RANGE", "NOT_AT_HOME"),
        ("trolley", lambda w: setattr(w, "trolley", "present"), {}, "DEPARTURE_REFUSED", "TROLLEY_PRESENT"),
        (
            "trolley_unknown",
            lambda w: setattr(w, "trolley", "unknown"),
            {},
            "DEPARTURE_REFUSED",
            "TROLLEY_UNKNOWN",
        ),
        ("rear", lambda w: setattr(w, "rear_clear", False), {}, "DEPARTURE_REFUSED", "REAR_FIELD_NOT_CLEAR"),
        (
            "rear_unknown",
            lambda w: setattr(w, "rear_clear", None),
            {},
            "DEPARTURE_REFUSED",
            "REAR_FIELD_UNKNOWN",
        ),
        ("loc", lambda w: setattr(w, "loc_ready", False), {}, "DEPARTURE_REFUSED", "LOCALIZATION_NOT_READY"),
        (
            "tape",
            lambda w: None,
            {"sensor": {"tracks": [], "has_track": False, "nlcp": 0, "track_level": 0}},
            "DEPARTURE_REFUSED",
            "TAPE_NOT_SEEN",
        ),
        ("front", lambda w: None, {"field_clear": None}, "DEPARTURE_REFUSED", "PREREQUISITE"),
        ("drives", lambda w: None, {"drives_fresh": False}, "DEPARTURE_REFUSED", "PREREQUISITE"),
        ("machine", lambda w: None, {"machine": "NOPE"}, "VALIDATION_FAILURE", "MACHINE"),
    ]


@pytest.mark.parametrize(
    "name, setup, over, etype, reason", _check_cases(), ids=[c[0] for c in _check_cases()]
)
def test_each_contract_check_refuses_with_its_error(name, setup, over, etype, reason):
    w = settled()
    setup(w)
    over = dict(over)
    machine = over.pop("machine", "M1")
    w.job.order_request("O1", machine)
    w.tick(**over)
    assert w.refusal() == (etype, reason), name
    assert w.job.trip is None or name == "other_order", "nothing stored"
    assert snap(w)["refusal_order_id"] == "O1"


def test_a_route_that_does_not_compile_is_refused():
    m = site(trip_calls=1)
    from calling_world import CallingWorld

    w = CallingWorld(m, graph(m, skip=("UT-M1",)))
    w.drive(SETTLE + 0.1)
    w.order()
    assert w.refusal() == ("NO_ROUTE_TO_TARGET", "ROUTE") and w.job.state == lj.IDLE


def test_settling_and_holdoff_refuse_as_check_9():
    w = calling()
    w.order()
    assert w.refusal() == ("DEPARTURE_REFUSED", "SETTLING") and w.job.state == lj.IDLE


def _to_state(w, name):
    if name == "ARMED":
        w.job.trip_call("M1", w.t)
        w.press_start()
    elif name == "RUNNING":
        w.job.trip_call("M1", w.t)
        w.start()
    elif name == "FAULT":
        w.job.trip_call("M1", w.t)
        w.start()
        w.wrong = "wrong branch"
        w.tick()
        w.wrong = ""
    else:
        w.job.trip_call("M1", w.t)
        w.start()
        w.drive(0.5)
        cause = name.split(":")[1]
        w.tick(
            **{
                "field": {"field_clear": False},
                "estop": {"torque_off": True},
                "drives": {"drives_fresh": False},
            }[cause]
        )
    return w


@pytest.mark.parametrize("name", ["ARMED", "RUNNING", "FAULT", "HOLD:field", "HOLD:estop", "HOLD:drives"])
def test_an_order_is_refused_in_every_other_state(name):
    w = _to_state(settled(), name)
    before = w.job.state
    w.job.order_request("O1", "M1")
    w.tick(field_clear=False) if name == "HOLD:field" else w.tick()
    assert w.job.order is None and w.refusal()[0] in ("OTHER_ORDER_ACTIVE", "DEPARTURE_REFUSED"), name
    assert w.job.state == before or name == "ARMED" or name == "RUNNING"


def test_an_order_is_refused_at_a_station_hold():
    w = settled()
    w.order("O1")
    parked_at(w, "ATT")
    w.job.order_request("O2", "M1")
    w.tick()
    assert w.refusal() == ("OTHER_ORDER_ACTIVE", "O1")
    assert w.job.order.order_id == "O1" and w.job.hold_cause == "station"


@pytest.mark.parametrize(
    "cause, over",
    [("field", {"field_clear": False}), ("estop", {"torque_off": True}), ("drives", {"drives_fresh": False})],
)
def test_an_order_cannot_resume_a_hold_or_leave_a_stop(cause, over):
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.drive(0.5)
    w.tick(**over)
    assert w.job.state == lj.HOLD and w.job.hold_cause == cause
    for n in range(5):
        w.job.order_request(f"N{n}", "M1")
        assert w.tick(**over) == (0.0, 0.0)
        assert w.job.state == lj.HOLD and w.job.hold_cause == cause
    assert w.job.order.order_id == "O1"


def test_a_start_in_the_same_tick_refuses_the_order():
    w = settled()
    w.job.trip_call("M1", w.t)
    w.job.order_request("O1", "M1")
    w.press_start()
    assert w.job.state == lj.ARMED and w.job.order is None, "the press is handled"
    assert w.refusal() == ("DEPARTURE_REFUSED", "PREREQUISITE")
    assert w.job.trip.machines == ["M1"]


def test_a_reset_in_the_same_tick_refuses_the_order():
    w = settled()
    w.job.trip_call("M1", w.t)
    w.start()
    w.job.order_request("O1", "M1")
    w.tick(reset_edge=True)
    assert w.job.state == lj.IDLE and w.job.order is None
    assert w.refusal() == ("DEPARTURE_REFUSED", "PREREQUISITE")


def _cancel_cases():
    def web_clear(w):
        w.job.clear()

    return [
        ("front", {"field_clear": False}, None),
        ("rear", {"rear_clear": False}, None),
        ("trolley", {"trolley": "present"}, None),
        ("panel_link", {"panel_link_lost": True}, None),
        ("selector", {"panel_auto": False}, None),
        ("reset", {"reset_edge": True}, None),
        ("clear", {}, web_clear),
    ]


@pytest.mark.parametrize("name, over, act", _cancel_cases(), ids=[c[0] for c in _cancel_cases()])
def test_a_cancelled_warning_ends_the_order(name, over, act):
    w = settled()
    w.order()
    assert w.job.state == lj.ARMED
    if act:
        act(w)
    for _ in range(40):  # past the debounce, and the FAULT tick that ends the trip
        assert w.tick(**over) == (0.0, 0.0)
        over = {k: v for k, v in over.items() if k != "reset_edge"}
    s = snap(w)
    assert not s["active"] and not s["departed"] and s["cancelled_reason"], (name, s)
    assert (s["att_status"], s["mw_status"], s["me_status"]) == ("FAILED", "FAILED", "FAILED")
    assert s["last_node_id"] == "HOME" and s["last_node_seq"] == 0
    assert w.job.trip is None and w.job.state != lj.RUNNING
    w.tick()
    assert "HOLDOFF" in w.not_ready(), (name, w.not_ready())
    if name == "selector":
        assert w.job.state == lj.FAULT, "the fault itself stays and needs Reset (R1)"


def test_a_cancelled_order_restores_no_call():
    w = settled()
    w.order()
    w.tick(field_clear=False)
    assert w.job.calls.pending == []
    w.press_start()
    assert w.job.state == lj.IDLE, "no later Start can pick it up"


def _restart_cases():
    return [
        ("selector", lambda w: (w.drive(0.1, panel_auto=False), w.tick())),
        ("reset", lambda w: w.tick(reset_edge=True)),
        ("clear", lambda w: w.job.clear()),
        ("call_cancel", lambda w: (w.job.trip_call("M1", w.t), w.job.trip_cancel("M1"))),
        ("mission", lambda w: w.job.set_mission(w.m)),
        (
            "trolley",
            lambda w: (setattr(w, "trolley", "present"), w.tick(), setattr(w, "trolley", "absent"), w.tick()),
        ),
        (
            "rear",
            lambda w: (setattr(w, "rear_clear", False), w.tick(), setattr(w, "rear_clear", True), w.tick()),
        ),
        ("front", lambda w: (w.tick(field_clear=False), w.tick())),
    ]


@pytest.mark.parametrize("name, act", _restart_cases(), ids=[c[0] for c in _restart_cases()])
def test_settling_blocks_for_its_time_after_each_restart(name, act):
    w = settled()
    act(w)
    w.tick()
    assert "SETTLING" in w.not_ready(), (name, w.not_ready())
    w.order()
    assert w.job.state == lj.IDLE and w.refusal() == ("DEPARTURE_REFUSED", "SETTLING"), name
    w.drive(SETTLE - 0.3)
    assert "SETTLING" in w.not_ready()
    w.drive(0.4)
    assert "SETTLING" not in w.not_ready(), w.not_ready()
    w.order("O2")
    assert w.job.state == lj.ARMED, (name, w.job.reason, w.refusal())


def test_settling_restarts_on_arrival_and_after_a_cancel_order():
    w = settled()
    w.order()
    w.job.order_cancel("O1", "c")
    w.tick()
    assert "SETTLING" in w.not_ready() and "HOLDOFF" not in w.not_ready()
    w.drive(SETTLE + 0.1)
    w.order("O2")
    to_stop(w, "ME-1")
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    w.tick()
    assert {"SETTLING", "TROLLEY_PRESENT"} <= set(w.not_ready()), w.not_ready()


def test_holdoff_blocks_for_its_time():
    w = settled()
    w.order()
    w.tick(field_clear=False)
    w.drive(HOLDOFF - 0.5)
    assert w.not_ready() == ["HOLDOFF"], w.not_ready()
    w.drive(0.7)
    assert w.not_ready() == []


def test_settling_runs_from_start_up():
    w = calling()
    w.tick()
    assert "SETTLING" in w.not_ready()


def test_clear_in_fault_is_refused_with_calling_on():
    w = _to_state(settled(), "FAULT")
    w.tick()
    assert w.job.state == lj.FAULT
    w.job.clear()
    assert w.job.state == lj.FAULT, "press Reset on the panel"
    w.drive(1.0)
    assert w.job.state == lj.FAULT and "FAULT" in w.not_ready()
    w.tick(reset_edge=True)
    assert w.job.state == lj.IDLE


def test_clear_in_fault_unchanged_with_calling_off():
    w = one_call()
    w.job.trip_call("M1", w.t)
    w.start()
    w.wrong = "wrong branch"
    w.tick()
    w.tick()
    assert w.job.state == lj.FAULT
    w.job.clear()
    assert w.job.state == lj.IDLE


def test_a_torque_timeout_latches_until_a_reset_edge():
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state != lj.ARMED, 3.0, torque_off=True)
    s = snap(w)
    assert s["cancelled_reason"] == "TORQUE_TIMEOUT"
    w.drive(HOLDOFF + SETTLE + 1.0)
    assert w.not_ready() == ["TORQUE_TIMEOUT"], "one horn cycle only: it outlasts the hold-off"
    w.order("O2")
    assert w.job.state == lj.IDLE and w.refusal() == ("DEPARTURE_REFUSED", "TORQUE_TIMEOUT")
    w.tick(reset_edge=True)
    assert "TORQUE_TIMEOUT" not in w.not_ready() and "SETTLING" in w.not_ready()


def test_an_order_cancels_at_its_own_torque_wait():
    w = settled()
    w.order()
    assert not w.until(lambda: w.job.state != lj.ARMED, 1.9, torque_off=True)
    assert w.until(lambda: w.job.state != lj.ARMED, 0.3, torque_off=True), "at 2.0 s, not 8 s"
    w.drive(1.0)  # torque arriving after the wait moves nothing
    assert w.job.state == lj.IDLE and w.job.order.departed is False


def test_a_physical_start_keeps_the_premove_timeout():
    w = settled()
    w.job.trip_call("M1", w.t)
    w.press_start()
    assert not w.until(lambda: w.job.state != lj.ARMED, 3.0, torque_off=True), "the 8 s default"
    assert w.job.state == lj.ARMED


def test_a_station_warning_in_an_order_keeps_the_premove_timeout():
    w = settled()
    w.order()
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.ARMED
    assert not w.until(lambda: w.job.state != lj.ARMED, 3.0, torque_off=True)


def test_at_home_needs_a_fresh_ready():
    w = settled()
    w.loc_ready = False
    w.job.at_home_pressed()
    w.tick()
    assert w.not_ready() == ["LOCALIZATION_NOT_READY"]
    w.order()
    assert w.job.state == lj.IDLE and w.refusal() == ("DEPARTURE_REFUSED", "LOCALIZATION_NOT_READY")
    assert not w.job.wants_power(), "no horn"
    w.loc_ready = True
    w.tick()
    assert w.not_ready() == []


def test_no_tape_refuses_an_order():
    w = settled()
    no = {"tracks": [], "has_track": False, "nlcp": 0, "track_level": 0}
    w.tick(sensor=no)
    assert "TAPE_NOT_SEEN" in w.not_ready()


def test_no_sensor_sample_yet_is_no_tape_and_no_crash():
    w = settled()
    w.tick(sensor=None, sensor_age_s=None)
    assert "TAPE_NOT_SEEN" in w.not_ready()


def test_no_tape_or_readiness_check_on_a_physical_start():
    w = settled()
    w.loc_ready = False
    w.job.trip_call("M1", w.t)
    w.press_start()
    assert w.job.state == lj.ARMED, w.job.reason


@pytest.mark.parametrize("how", ["jog", "pivot", "after_arrival", "no_counts"])
def test_any_wheel_movement_clears_at_home_for_orders(how):
    w = settled()
    if how == "jog":
        w.move(0.1)
    elif how == "pivot":
        S = w.S
        turn = int(PER_REV * 0.1)
        w.counts = (w.counts[0] + turn, w.counts[1] + turn)  # a pivot: opposite wheels, same driver sign
        w.tick()
        w.S = S
    elif how == "no_counts":
        w.tick(counts=None)
        assert "NOT_AT_HOME" in w.not_ready()
        w.tick()
        assert "NOT_AT_HOME" not in w.not_ready(), "dropped counts alone do not need At home again"
        w.tick(counts=None)
        w.counts = (w.counts[0] + int(PER_REV * 0.1), w.counts[1])
        w.tick()
    else:
        w.order()
        to_stop(w, "ME-1")
        w.trolley = "present"
        w.drive(0.1)
        go_on(w)
        w.still = False
        assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
        w.tick()
        assert "NOT_AT_HOME" in w.not_ready(), "until the wheels have come to rest"
        w.still = True
        w.tick()
        assert "NOT_AT_HOME" not in w.not_ready()
        w.move(0.1)
    w.tick()
    assert "NOT_AT_HOME" in w.not_ready(), w.not_ready()
    w.job.at_home_pressed()
    w.tick()
    assert "NOT_AT_HOME" not in w.not_ready()


def test_no_site_gives_only_site_not_live():
    from test_mission_engine import World

    class Plain(World):
        JOB_ARGS = {"calling": True}

    w = Plain(None)
    w.drive(0.1)
    assert w.job.order_snapshot()["not_ready"] == ["SITE_NOT_LIVE"]
    w.job.order_request("O1", "M1")
    w.tick()
    s = w.job.order_snapshot()
    assert (s["refusal_type"], s["refusal_reason"]) == ("DEPARTURE_REFUSED", "SITE_NOT_LIVE")


def test_a_stale_panel_gives_not_auto():
    w = settled()
    w.tick(panel_valid=False, panel_auto=False)
    assert w.not_ready()[0] == "NOT_AUTO" and "PREREQUISITE" not in w.not_ready()


def test_cancel_in_the_warning():
    w = settled()
    w.order()
    w.job.order_cancel("O1", "cancel-O1")
    assert w.tick() == (0.0, 0.0)
    s = snap(w)
    assert w.job.state == lj.IDLE and not s["active"] and w.job.trip is None
    assert (s["cancel_action_id"], s["cancel_status"], s["cancel_error"]) == ("cancel-O1", "FINISHED", "")
    assert s["cancelled_reason"] == "" and s["att_status"] == "FAILED" and s["cancel_seq"] == 1
    assert "HOLDOFF" not in w.not_ready() and "SETTLING" in w.not_ready()


def test_cancel_after_departure_is_refused():
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.job.order_cancel("O1", "c")
    w.tick()
    s = snap(w)
    assert (s["cancel_status"], s["cancel_error"]) == ("FAILED", "CANCEL_REFUSED")
    assert s["active"] and w.job.state == lj.RUNNING


@pytest.mark.parametrize("active", [False, True])
def test_cancel_with_no_order(active):
    w = settled()
    if active:
        w.order()
    w.job.order_cancel("OTHER", "c")
    w.tick()
    s = snap(w)
    assert (s["cancel_status"], s["cancel_error"]) == ("FAILED", "NO_ORDER_TO_CANCEL")
    assert w.job.state == (lj.ARMED if active else lj.IDLE)


def test_action_states_follow_the_trip():
    w = settled()
    w.order()
    st = lambda: tuple(snap(w)[k] for k in ("att_status", "mw_status", "me_status"))  # noqa: E731
    assert st() == ("WAITING", "WAITING", "WAITING")
    parked_at(w, "ATT")
    assert st() == ("RUNNING", "WAITING", "WAITING")
    assert (snap(w)["last_node_id"], snap(w)["last_node_seq"]) == ("ATT", 2)
    w.trolley = "present"
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.ARMED and st()[0] == "RUNNING", (
        "FINISHED when the warning ends, not at the press"
    )
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    assert st() == ("FINISHED", "WAITING", "WAITING")
    parked_at(w, "MW-1")
    assert st() == ("FINISHED", "RUNNING", "WAITING")
    assert (snap(w)["last_node_id"], snap(w)["last_node_seq"]) == ("MW-1", 4)
    w.trolley = "absent"
    w.drive(0.1)
    go_on(w)
    assert st() == ("FINISHED", "FINISHED", "WAITING")
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
    spin(w)
    parked_at(w, "ME-1")
    assert st() == ("FINISHED", "FINISHED", "RUNNING")
    assert (snap(w)["last_node_id"], snap(w)["last_node_seq"]) == ("ME-1", 6)
    w.trolley = "present"
    w.drive(0.1)
    go_on(w)
    assert st() == ("FINISHED", "FINISHED", "FINISHED")
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    s = snap(w)
    assert (s["last_node_id"], s["last_node_seq"], s["active"]) == ("HOME", 8, False)


def test_a_cancelled_warning_at_a_stop_keeps_the_action_running():
    w = settled()
    w.order()
    parked_at(w, "ATT")
    w.trolley = "present"
    w.drive(0.1)
    w.press_start()
    assert w.job.state == lj.ARMED
    w.tick(field_clear=False)
    s = snap(w)
    assert w.job.hold_cause == "station" and s["att_status"] == "RUNNING" and s["active"]
    assert (s["start_refused_node"], s["start_refused_reason"]) == ("ATT", "WARNING_CANCELLED")


@pytest.mark.parametrize("how", ["selector", "tape", "branch", "clear"])
def test_an_abort_after_departure_reports_trip_aborted(how):
    w = settled()
    w.order()
    assert w.until(lambda: w.job.state == lj.RUNNING, 2.0)
    w.drive(0.5)
    if how == "selector":
        w.tick(panel_auto=False)
        w.tick(panel_auto=False)
    elif how == "branch":
        w.wrong = "wrong branch at J-B"
        w.tick()
        w.tick()
    elif how == "clear":
        w.job.clear()
    else:
        no = {"tracks": [], "has_track": False, "nlcp": 0, "track_level": 0}
        assert w.until(lambda: not snap(w)["active"], 30.0, sensor=no), w.job.reason
    s = snap(w)
    assert not s["active"] and s["aborted_reason"] and s["aborted_text"] and s["cancelled_reason"] == ""
    assert w.job.trip is None
    assert s["att_status"] == "FAILED"


def test_an_order_to_the_tape_end_machine():
    m = site(
        trip_calls=1,
        uturn_points={},
        groups={"M": {"circuit": "C-M", "machines": {"M1": {"release": "MW-1", "take": "ME-1"}}}},
    )
    from calling_world import CallingWorld

    w = CallingWorld(m, graph(m, skip=("UT-M1", "UT-M2")))
    w.drive(SETTLE + 0.1)
    w.order()
    assert w.job.state == lj.ARMED and w.job.trip.uturn()["mode"] == "tapeend"


@pytest.mark.parametrize("machine", ["unknown", "swap"])
def test_a_machine_with_no_release_is_refused(machine):
    if machine == "unknown":
        w = settled()
        name = "NOPE"
    else:
        w = settled(
            groups={
                "M": {
                    "circuit": "C-M",
                    "machines": {
                        "M1": {"release": "MW-1", "take": "ME-1", "uturn": "UT-M1"},
                        "M2": {"release": "MW-2", "take": "ME-2", "uturn": "UT-M2"},
                    },
                },
            }
        )
        w.job.site = dict(w.job.site)
        w.job.site["GROUPS"] = {
            "M": {
                **w.job.site["GROUPS"]["M"],
                "machines": {**w.job.site["GROUPS"]["M"]["machines"], "S1": {"swap": "MW-1"}},
            }
        }
        w.job.site["MACHINES"] = {**w.job.site["MACHINES"], "S1": "M"}
        name = "S1"
    w.job.order_request("O1", name)
    w.tick()
    assert w.refusal() == ("VALIDATION_FAILURE", "MACHINE")


# -- the static pin (plan section 16) ---------------------------------------------------------
def _functions(tree):
    return {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}


def _calls(node, attr):
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == attr
    ]


def test_the_order_entry_has_one_call_site():
    tree = ast.parse(JOB.read_text())
    funcs = _functions(tree)
    where = [name for name, f in funcs.items() if _calls(f, "_order_start")]
    assert where == ["tick"]
    assert len(_calls(funcs["tick"], "_order_start")) == 1
    guarded = [n for n in ast.walk(funcs["tick"]) if isinstance(n, ast.If) and _calls(n, "_order_start")]
    assert any("(IDLE, DONE)" in ast.unparse(n.test) for n in guarded)
    begins = {name for name, f in funcs.items() if _calls(f, "_begin_premove")}
    assert begins == {"_start", "_order_start", "_hold_tick", "_station_tick"}
    arg = _calls(funcs["_order_start"], "_begin_premove")[0].args[1]
    assert isinstance(arg, ast.Constant) and arg.value == "start"
    reads = [
        name
        for name, f in funcs.items()
        for n in ast.walk(f)
        if isinstance(n, ast.Attribute) and n.attr == "_order_req" and isinstance(n.ctx, ast.Load)
    ]
    assert set(reads) == {"_order_take"}
    node = ast.parse(NODE.read_text())
    inputs = _functions(node)["_inputs"]
    kw = [k for c in ast.walk(inputs) if isinstance(c, ast.Call) for k in c.keywords if k.arg == "start_edge"]
    assert len(kw) == 1 and ast.unparse(kw[0].value) == "start_edge_t is not None"
    assert NODE.read_text().count("start_edge=") == 1


def test_trip_world_is_the_plain_one_with_calling_off():
    w = TripWorld(site(trip_calls=1), graph(site(trip_calls=1)))
    assert w.job.calling is False
