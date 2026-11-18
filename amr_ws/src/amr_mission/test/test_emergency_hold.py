"""The executor and the panel's emergency state (owner policy 2026-10-30; ported from kyb c36c8d2 for
gvievo-01 emergency-suite plan Part B E5, owner O-3 2026-11-16).

An emergency is a PHYSICAL stop, like the safety chain's: it never ends the run. A moving run
(the pre-move warning included) holds as `estop`, any other hold becomes `estop`, READY and
PAUSED keep their state. Start and Load are refused while it lasts, with no pre-move; physical
Reset never resumes anything; Start after NORMAL resumes the held run through the warning.
Built with __new__ like test_auto_resume, whose helpers drive the clock, the wheels and the
drive report. Needs rclpy and amr_interfaces, like test_auto_resume."""

from types import SimpleNamespace

import pytest
from test_auto_resume import node, run_for, started, tick

from amr_interfaces.msg import PanelState
from amr_mission import route_executor_node as ren
from amr_mission import run_fsm as fsm


@pytest.fixture(autouse=True)
def _estop_signal_read(monkeypatch):
    """These tests are the E-stop signal path (DI09 read). Both profiles bypass it for now
    (panel.estop_signal_enabled false, emergency-suite plan §9); the bypass has its own test."""
    from agv_core import config  # noqa: PLC0415

    monkeypatch.setattr(config, "PANEL_ESTOP_SIGNAL_ENABLED", True)


def emergency(n, state):
    n._panel.emergency = state
    n._panel.estop_ok = state == PanelState.EMG_NORMAL


@pytest.mark.parametrize("where", ["premove", "executing", "blocked"])
def test_an_emergency_holds_a_moving_or_held_run_as_estop(where):
    n = started() if where == "premove" else node()
    if where == "blocked":
        n._hold("controller", "collision ahead")  # a hold that would resume by itself
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"
    assert "emergency stop" in n.fsm.reason
    assert n.goals.current is None, "nothing is driven while held"


@pytest.mark.parametrize("where", ["ready", "paused"])
def test_an_emergency_leaves_a_stationary_run_untouched(where):
    n = node(start=False) if where == "ready" else node()
    if where == "paused":
        n.fsm.pause()
    before = n.fsm.state
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == before


def test_the_panel_message_itself_holds_without_waiting_for_a_tick():
    n = node()
    m = PanelState()
    m.valid, m.mode_auto, m.emergency = True, True, PanelState.EMG_ACTIVE
    n._on_panel(m)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"


def test_the_estop_hold_never_resumes_by_itself():
    n = node()
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    emergency(n, PanelState.EMG_NORMAL)  # released + Reset
    n._reset_edge()
    run_for(n, 5.0, torque=True, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"


def test_start_while_not_normal_is_refused_at_once_with_no_premove():
    n = node(start=False)
    for state in (PanelState.EMG_ACTIVE, PanelState.EMG_RESET_NEEDED, PanelState.EMG_RESETTING,
                  PanelState.EMG_RESET_FAILED):
        emergency(n, state)
        n._start_edge()
        assert n.fsm.state == fsm.READY and n.phase != ren.PHASE_PREMOVE
        assert "E-stop active" in n.fsm.reason and not n.drive_power()


def test_load_is_refused_while_not_normal():
    n = node(start=False)
    emergency(n, PanelState.EMG_RESET_NEEDED)
    res = n._srv_run(SimpleNamespace(mission_id="m1"), SimpleNamespace(accepted=None, message=""))
    assert not res.accepted and "E-stop active" in res.message


def test_start_after_normal_resumes_the_held_run_through_the_warning():
    n = node()
    step = (n.fsm.pass_index, n.fsm.step_index)
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.BLOCKED
    emergency(n, PanelState.EMG_NORMAL)
    run_for(n, 1.0, torque=False, field=True)
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING and n.phase == ren.PHASE_PREMOVE and n.drive_power()
    assert (n.fsm.pass_index, n.fsm.step_index) == step, "the route continues where it stopped"


def test_a_stale_panel_falls_back_to_the_torque_inference():
    n = node()
    tick(n, torque=True, field=True)
    emergency(n, PanelState.EMG_ACTIVE)
    n.clock[0] += 1.0  # the panel image is now older than panel_age: it says nothing
    assert not n._emergency(n.clock[0])
    n.prereq_grace_s = 10.0  # the stale panel would fault later; here only the hold matters
    n.wheels(0.0, valid=True)
    n._on_drives(SimpleNamespace(operational=False, left_state="Switch on disabled", right_state="stale"))
    n._tick()
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"


def test_a_field_hold_is_relabelled_estop_and_never_resumes_by_itself():
    """A hold that would resume by itself (the field) must not do so through an E-stop."""
    n = node()
    tick(n, field=False)
    tick(n, torque=False, wheels=False)
    assert n.hold_cause == "field" and n.drive_power()
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.hold_cause == "estop" and not n.drive_power()
    emergency(n, PanelState.EMG_NORMAL)
    run_for(n, 5.0, torque=True, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop"


def test_a_torque_loss_with_the_panel_normal_is_the_chain_not_the_estop():
    """WP-Y1 note / station-call O8: once DI09 exists a rear OSSD (or any other safety input) stop
    is not an E-stop. It waits for Start like one, with its own label."""
    n = node()
    tick(n, torque=True, field=True)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "chain" and not n.drive_power()
    assert "not the E-stop" in n.fsm.reason
    run_for(n, 5.0, torque=True, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "chain", "never by itself"
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING and n.phase == ren.PHASE_PREMOVE


def test_the_chain_hold_becomes_estop_when_di09_catches_up():
    """DI09 is filtered over estop_confirm_scans: the drive report can beat it."""
    n = node()
    tick(n, torque=True, field=True)
    tick(n, torque=False, wheels=False, field=True)
    assert n.hold_cause == "chain"
    emergency(n, PanelState.EMG_ACTIVE)
    tick(n, torque=False, wheels=False, field=True)
    assert n.hold_cause == "estop"


def test_the_chain_hold_becomes_the_field_when_the_field_is_reported_late():
    """Acceptance §7.8: a protective-field stop shows no banner and still resumes by itself, also
    when /output_paths arrives after the drive report."""
    n = node()
    tick(n, torque=True, field=True)
    tick(n, torque=False, wheels=False, field=True)
    assert n.hold_cause == "chain"
    tick(n, torque=False, wheels=False, field=False)  # 0.1 s later: the field was violated
    assert n.hold_cause == "field" and n.drive_power()
    run_for(n, 1.0, torque=False, wheels=False, field=False)
    run_for(n, 2.6, torque=True, field=True)
    assert n.fsm.state == fsm.EXECUTING, "the field hold resumed by itself"


def test_a_field_seen_after_the_race_window_leaves_the_chain_hold():
    n = node()
    tick(n, torque=True, field=True)
    tick(n, torque=False, wheels=False, field=True)
    run_for(n, 0.6, torque=False, wheels=False, field=True)
    tick(n, torque=False, wheels=False, field=False)
    assert n.hold_cause == "chain"


def test_an_invalid_panel_image_is_never_an_emergency_here():
    """A blind panel (valid False) publishes emergency ACTIVE; that is PANEL_STALE's story."""
    n = node()
    n._panel.valid = False
    emergency(n, PanelState.EMG_ACTIVE)
    assert not n._emergency(n.clock[0]) and n._panel_emergency(n.clock[0]) is None


def test_with_the_signal_bypassed_a_torque_loss_is_the_estop_guess_not_the_chain(monkeypatch):
    """emergency-suite plan §9 (owner 2026-11-17): panel.estop_signal_enabled false. The panel's
    emergency reads NORMAL, but it cannot be believed: the torque loss is labelled the old way,
    `estop` ("E-stop / safety chain"), never "not the E-stop". Start after it still resumes."""
    from agv_core import config  # noqa: PLC0415

    monkeypatch.setattr(config, "PANEL_ESTOP_SIGNAL_ENABLED", False)
    n = node()
    assert n._panel_emergency(n.clock[0]) is None
    tick(n, torque=True, field=True)
    tick(n, torque=False, wheels=False, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop" and not n.drive_power()
    assert "not the E-stop" not in n.fsm.reason
    run_for(n, 5.0, torque=True, field=True)
    assert n.fsm.state == fsm.BLOCKED and n.hold_cause == "estop", "never by itself"
    n._start_edge()
    assert n.fsm.state == fsm.EXECUTING and n.phase == ren.PHASE_PREMOVE
