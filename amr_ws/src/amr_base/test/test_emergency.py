"""amr_base.emergency: the PC's emergency picture (emergency-suite plan §3, owner 2026-10-30).

Every transition, and the two ways the Flexi Soft may drive Q3 (bench question Q1): unlatched
(Q3 follows the button) and latched (Q3 active until the PLC is reset). Owner 2026-11-16: only
the safety controller's signal makes an emergency; a blind panel (DIO gap) changes nothing.
`estop=False` below means the signal is active (Inputs.estop_ok False)."""

import pytest

from amr_base import emergency as em
from amr_base.emergency import (
    ACTIVE,
    NORMAL,
    RESET_FAILED,
    RESET_NEEDED,
    RESETTING,
    Emergency,
    Inputs,
    sto_held,
)

T = 3.0  # panel.estop_reset_timeout_s


def tick(e, now, ok=True, estop=True, reset=False, sto=False):
    return e.step(now, Inputs(ok, estop, reset, sto))


def normal_at(now=0.0):
    e = Emergency(T)
    tick(e, now)
    assert e.state == NORMAL
    return e


def test_the_states_are_the_panel_state_contract():
    assert (NORMAL, ACTIVE, RESET_NEEDED, RESETTING, RESET_FAILED) == (0, 1, 2, 3, 4)
    PanelState = pytest.importorskip("amr_interfaces.msg").PanelState  # built only on the vehicle

    assert (PanelState.EMG_NORMAL, PanelState.EMG_ACTIVE, PanelState.EMG_RESET_NEEDED,
            PanelState.EMG_RESETTING, PanelState.EMG_RESET_FAILED) == (0, 1, 2, 3, 4)


def test_boot_is_normal_and_a_blind_panel_changes_nothing():
    """Owner 2026-11-16: a DIO gap or an invalid image is not an E-stop (it would stop the AGV
    at random). The state holds; PANEL_STALE / DIO_LINK_LOST report the link."""
    e = Emergency(T)
    assert e.state == NORMAL
    assert tick(e, 0.0, ok=False, estop=False) is None and e.state == NORMAL
    assert tick(e, 0.1, ok=False, estop=True, sto=True) is None and e.state == NORMAL


def test_drives_in_sto_alone_are_not_an_emergency():
    """Boot with the drives in Switch on disabled, or a field / safety-circuit stop: no signal,
    no banner. The run logic names those stops (field, chain)."""
    e = Emergency(T)
    tick(e, 0.0, sto=True)
    assert e.state == NORMAL


def test_the_signal_enters_at_once_from_every_state():
    for start in (NORMAL, RESET_NEEDED, RESETTING, RESET_FAILED):
        e = normal_at()
        e.state = start
        assert tick(e, 1.0, estop=False) is not None
        assert e.state == ACTIVE, start


@pytest.mark.parametrize("start", [NORMAL, ACTIVE, RESET_NEEDED, RESETTING, RESET_FAILED])
def test_an_invalid_or_stale_panel_holds_every_state(start):
    e = normal_at()
    e.state, e._deadline = start, 0.0
    for estop in (False, True):
        assert tick(e, 9.0, ok=False, estop=estop, reset=True, sto=False) is None
        assert e.state == start


def test_an_emergency_survives_a_dio_gap_and_still_needs_the_reset():
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    tick(e, 1.5, ok=False, estop=False, sto=True)  # DIO comms gap while pressed
    assert e.state == ACTIVE
    tick(e, 2.0, sto=True)  # image back, released meanwhile
    assert e.state == RESET_NEEDED


def test_unlatched_sequence_press_release_reset():
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    assert e.state == ACTIVE
    tick(e, 5.0, sto=True)  # released (DI09 HIGH, debounced by the adapter)
    assert e.state == RESET_NEEDED
    tick(e, 6.0, sto=True)  # no Reset: stays
    assert e.state == RESET_NEEDED
    tick(e, 7.0, reset=True, sto=True)
    assert e.state == RESETTING
    tick(e, 7.5, sto=True)
    assert e.state == RESETTING
    tick(e, 7.6, sto=False)  # drives left Switch on disabled
    assert e.state == NORMAL


def test_latched_sequence_one_reset_press_is_enough():
    """Q3 stays LOW until Reset: the edge lands while DI09 is LOW, DI09 rises after it."""
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    tick(e, 5.0, estop=False, sto=True)  # released, but Q3 latched: PC cannot tell
    assert tick(e, 6.0, estop=False, reset=True, sto=True) is None  # the edge does nothing visible
    assert e.state == ACTIVE
    tick(e, 6.4, sto=True)  # the PLC reset raised Q3
    assert e.state == RESETTING
    tick(e, 6.6, sto=False)
    assert e.state == NORMAL


def test_latched_reset_held_past_the_window_falls_back_to_reset_needed():
    e = normal_at()
    tick(e, 1.0, estop=False)
    tick(e, 2.0, estop=False, reset=True)
    tick(e, 2.0 + T + 0.1, sto=True)
    assert e.state == RESET_NEEDED


def test_a_reset_with_the_signal_active_does_nothing():
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    for t in (2.0, 2.1, 2.2):
        tick(e, t, estop=False, reset=True, sto=True)
        assert e.state == ACTIVE
    tick(e, 2.0 + T + 1.0, sto=True)  # released well after: the early Reset is forgotten
    assert e.state == RESET_NEEDED


def test_a_premature_reset_then_a_quick_release_ends_in_reset_failed():
    """Unlatched Q3, Reset with the E-stop still in (Q4: the PLC ignores it), released inside
    the window: the PC goes RESETTING, the drives never leave STO, so 'press Reset again'."""
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    tick(e, 2.0, estop=False, reset=True, sto=True)
    tick(e, 2.5, sto=True)
    assert e.state == RESETTING
    tick(e, 2.5 + T, sto=True)
    assert e.state == RESET_FAILED
    tick(e, 9.0, reset=True, sto=True)  # Reset again
    assert e.state == RESETTING
    tick(e, 9.2, sto=False)
    assert e.state == NORMAL


def test_the_timeout_reaches_reset_failed_and_a_late_reset_still_clears():
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    tick(e, 2.0, sto=True)
    tick(e, 3.0, reset=True, sto=True)
    tick(e, 3.0 + T - 0.01, sto=True)
    assert e.state == RESETTING
    note = tick(e, 3.0 + T, sto=True)
    assert e.state == RESET_FAILED and "STO" in note
    tick(e, 8.0, sto=None)  # unobservable is not proof
    assert e.state == RESET_FAILED
    tick(e, 8.5, sto=False)  # the drives came out after all
    assert e.state == NORMAL


def test_unobservable_drives_take_the_reset_at_face_value():
    """No fresh DriveStatus (no bus, sim): nothing can be powered and nothing can be checked."""
    e = normal_at()
    tick(e, 1.0, estop=False, sto=None)
    tick(e, 2.0, sto=None)
    tick(e, 3.0, reset=True, sto=None)
    assert e.state == RESETTING
    tick(e, 3.02, sto=None)
    assert e.state == NORMAL


def test_the_signal_returning_during_the_reset_is_a_new_emergency():
    e = normal_at()
    tick(e, 1.0, estop=False, sto=True)
    tick(e, 2.0, sto=True)
    tick(e, 3.0, reset=True, sto=True)
    tick(e, 3.1, estop=False, sto=True)
    assert e.state == ACTIVE


def test_reset_in_normal_and_drives_leaving_sto_in_reset_needed_change_nothing():
    e = normal_at()
    assert tick(e, 1.0, reset=True) is None and e.state == NORMAL
    tick(e, 2.0, estop=False, sto=True)
    tick(e, 3.0, sto=True)
    tick(e, 4.0, sto=False)  # physical Reset only: no auto-clear
    assert e.state == RESET_NEEDED


def test_transitions_report_once_and_carry_the_names():
    e = normal_at()
    note = tick(e, 1.0, estop=False)
    assert note.startswith("emergency NORMAL -> EMERGENCY") and e.since == 1.0
    assert tick(e, 1.02, estop=False) is None


def test_sto_held_reads_only_fresh_linked_drive_reports():
    sod, ready = em.STO_STATE, "Ready to switch on"
    assert sto_held(sod, sod, "standby", 0.1) is True
    assert sto_held(sod, ready, "standby", 0.1) is True  # one still held: not finished
    assert sto_held(ready, ready, "standby", 0.1) is False
    assert sto_held("Operation enabled", "Operation enabled", "armed", 0.1) is False
    assert sto_held(sod, sod, "standby", 0.6) is None  # stale
    assert sto_held(sod, sod, "standby", None) is None
    assert sto_held(sod, sod, "no bus", 0.1) is None
    assert sto_held(sod, sod, "disarmed", 0.1) is None
    assert sto_held("", "", "standby", 0.1) is None


def test_reading_is_none_whenever_the_panel_cannot_say():
    """emergency.reading(): the hold-labelling readers' one view of PanelState.emergency. None =
    "cannot say" = the torque guess (cause estop). Bypassed (plan §9), stale, invalid, no field."""
    from types import SimpleNamespace  # noqa: PLC0415

    p = SimpleNamespace(valid=True, emergency=em.NORMAL)
    assert em.reading(p, True, enabled=True) == em.NORMAL
    assert em.reading(SimpleNamespace(valid=True, emergency=em.ACTIVE), True, enabled=True) == em.ACTIVE
    assert em.reading(p, True, enabled=False) is None  # bypassed: NORMAL would claim the E-stop is out
    assert em.reading(p, False, enabled=True) is None  # not fresh
    assert em.reading(SimpleNamespace(valid=False, emergency=em.NORMAL), True, enabled=True) is None
    assert em.reading(SimpleNamespace(valid=True), True, enabled=True) is None  # msg without the field
    assert em.reading(None, True, enabled=True) is None
    from agv_core import config  # noqa: PLC0415

    assert em.reading(p, True) is (None if not config.PANEL_ESTOP_SIGNAL_ENABLED else em.NORMAL)


def test_every_hold_labelling_reader_goes_through_reading():
    """The line node, the route executor and the station bridge: no inline PanelState.emergency
    read that would skip the bypass."""
    import pathlib  # noqa: PLC0415

    src = pathlib.Path(em.__file__).resolve().parents[2]
    for rel in ("amr_line/amr_line/line_follow_node.py", "amr_mission/amr_mission/route_executor_node.py",
                "amr_station/amr_station/station_bridge_node.py"):
        text = (src / rel).read_text(encoding="utf-8")
        assert "emergency.reading(" in text, rel
        assert 'getattr(self._panel, "emergency", None) if' not in text, rel
