"""Emergency-suite plan Part B E5 (2026-11-16): mode admission reads the panel's emergency FIRST
(kyb `panel_emergency` / `Snapshots.emergency()`), ahead of the torque guess. Pure: no rclpy."""

import types

from amr_bringup import mode_fsm as fsm
from amr_bringup.readiness import Snapshots


def _cond(**kw):
    base = dict(now=100.0, wheels_t=100.0, wheels_still_since=90.0, panel_t=100.0, panel_valid=True)
    base.update(kw)
    return fsm.Conditions(**base)


def test_every_mode_request_is_refused_while_the_emergency_is_not_normal():
    for emg in (1, 2, 3, 4):
        for state, req in ((fsm.IDLE, fsm.REQ_LINE), (fsm.IDLE, fsm.REQ_NAVIGATION),
                           (fsm.NAVIGATION, fsm.REQ_IDLE), (fsm.IDLE, fsm.REQ_SURVEY_START)):
            d = fsm.admit(state, req, _cond(emergency=emg))
            assert not d.ok and "E-stop active" in d.reason, (emg, req, d.reason)


def test_the_panel_reason_wins_over_the_torque_guess():
    d = fsm.admit(fsm.IDLE, fsm.REQ_LINE, _cond(emergency=1, drives_ok=False))
    assert "E-stop active" in d.reason
    d = fsm.admit(fsm.IDLE, fsm.REQ_LINE, _cond(emergency=0, drives_ok=False))
    assert not d.ok and "no torque" in d.reason, "NORMAL panel: the torque check still stands"


def test_normal_admits_as_before():
    assert fsm.admit(fsm.IDLE, fsm.REQ_LINE, _cond()).ok


def test_snapshots_carry_the_emergency_only_from_a_fresh_panel():
    s = Snapshots()
    assert s.emergency(0.0) == 0, "no panel image yet"
    s.on_panel(types.SimpleNamespace(valid=True, mode_auto=False, emergency=2))
    now = s.panel_t
    assert s.emergency(now) == 2 and s.conditions(now, 0, False).emergency == 2
    assert s.emergency(now + 1.5) == 0 and s.conditions(now + 1.5, 0, False).emergency == 0
    assert s.emergency(now - 0.5) == 0, "a future stamp is not fresh"
    old = types.SimpleNamespace(valid=True, mode_auto=False)  # a PanelState built before the field
    s.on_panel(old)
    assert s.emergency(s.panel_t) == 0
