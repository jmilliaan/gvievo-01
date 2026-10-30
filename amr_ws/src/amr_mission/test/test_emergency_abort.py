"""The executor and the panel's emergency state (emergency-suite plan §4.4, owner 2026-10-30).

An emergency ABORTS the run in any state, the pre-move warning included; Start and Load are
refused while it lasts, with no pre-move; physical Reset never resumes anything; a new Load +
Start after NORMAL runs through the warning as any run does. Built with __new__ like
test_auto_resume, whose helpers drive the clock, the wheels and the drive report."""

from types import SimpleNamespace

import pytest
from test_auto_resume import node, run_for, started, tick

from amr_interfaces.msg import PanelState
from amr_mission import route_executor_node as ren
from amr_mission import run_fsm as fsm


def emergency(n, state):
    n._panel.emergency = state
    n._panel.estop_ok = state == PanelState.EMG_NORMAL


def events(n):
    out = []
    n._event_pub = SimpleNamespace(publish=out.append)
    n._event_seq = 0
    return out


@pytest.mark.parametrize("where", ["ready", "premove", "executing", "paused", "blocked"])
def test_an_emergency_aborts_the_run_in_any_state(where):
    n = node(start=False) if where == "ready" else started() if where == "premove" else node()
    if where == "paused":
        n.fsm.pause()
    if where == "blocked":
        tick(n, torque=False, wheels=False, field=True)
        assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"  # the inference, first
    if where == "premove":
        assert n.phase == ren.PHASE_PREMOVE
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.IDLE and n.fsm.reason == "emergency stop"
    assert not n.drive_power() and n.goals.current is None


def test_the_abort_is_reported_with_the_estop_code():
    n = node()
    out = events(n)
    emergency(n, PanelState.EMG_ACTIVE)
    n._emergency_abort()
    n._event()
    assert out[-1].code == "ESTOP" and "emergency stop" in out[-1].text
    n._event()  # the next IDLE event is an ordinary one again
    assert out[-1].code == "MODE_CHANGE"


def test_the_panel_message_itself_aborts_without_waiting_for_a_tick():
    n = node()
    m = PanelState()
    m.valid, m.mode_auto, m.emergency = True, True, PanelState.EMG_ACTIVE
    n._on_panel(m)
    assert n.fsm.state == fsm.IDLE


def test_start_while_not_normal_is_refused_at_once_with_no_premove():
    n = node(start=False)
    for state in (PanelState.EMG_RESET_NEEDED, PanelState.EMG_RESETTING, PanelState.EMG_RESET_FAILED):
        emergency(n, state)
        n.fsm.state = fsm.READY  # as if it survived: Start must still refuse
        n._start_edge()
        assert n.fsm.state == fsm.READY and n.phase != ren.PHASE_PREMOVE
        assert "E-stop active" in n.fsm.reason and not n.drive_power()


def test_load_is_refused_while_not_normal():
    n = node(start=False)
    emergency(n, PanelState.EMG_RESET_NEEDED)
    res = n._srv_run(SimpleNamespace(mission_id="m1"), SimpleNamespace(accepted=None, message=""))
    assert not res.accepted and "E-stop active" in res.message


def test_reset_alone_never_resumes_and_a_new_start_runs_the_warning():
    n = node()
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.IDLE
    emergency(n, PanelState.EMG_NORMAL)  # released + Reset: the panel says NORMAL
    n._reset_edge()
    run_for(n, 3.0, torque=False, field=True)
    assert n.fsm.state == fsm.IDLE and not n.drive_power()
    n._start_edge()
    assert n.fsm.state == fsm.IDLE, "nothing to start: the route was cleared"
    # a deliberate Load + Start: the ordinary run with its pre-move warning
    assert n.fsm.load("m1", len(n.compiled.steps))
    n._pose, n.premove_s = (lambda: (0.0, 0.0, 0.0)), 2.0
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING and n.phase == ren.PHASE_PREMOVE and n.drive_power()


def test_a_stale_panel_falls_back_to_the_torque_inference():
    n = node()
    tick(n, torque=True, field=True)
    emergency(n, PanelState.EMG_ACTIVE)
    n.clock[0] += 1.0  # the panel image is now older than panel_age: it says nothing
    assert not n._emergency(n.clock[0])
    n.prereq_grace_s = 10.0  # the stale panel would fault later; here only the hold matters
    n.wheels(0.0, valid=True)
    n._on_drives(SimpleNamespace(operational=False, left_state="Switch on disabled", right_state="x"))
    n._tick()
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"
