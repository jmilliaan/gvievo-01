"""DO01 alarm horn (operator, 2026-10-02): AUTO RUNNING and (protective stop OR warning 1
OR warning 2). Running = tracked line RUNNING/HOLD or trackless EXECUTING/BLOCKED."""

from amr_base.hold_policy import CALL_CAUSES
from amr_base.panel_io import alarm_wanted, call_phase, call_wanted, motion_outputs

RUNNING, HOLD, ARMED, DONE = 2, 3, 1, 4  # LineState
EXECUTING, PAUSED, BLOCKED = 2, 3, 4  # RunState


def test_auto_run_with_a_field_occupied_sounds_it():
    for line, run in ((RUNNING, None), (HOLD, None), (None, EXECUTING), (None, BLOCKED)):
        assert alarm_wanted(True, line, run, True, True, True), (line, run)  # warning 1 or 2
        assert alarm_wanted(True, line, run, True, False, True), (line, run)  # protective stop


def test_no_field_no_alarm():
    assert not alarm_wanted(True, RUNNING, None, True, True, False)


def test_not_running_or_not_auto_is_silent():
    for line, run in ((DONE, None), (None, PAUSED), (None, None)):
        assert not alarm_wanted(True, line, run, True, False, True), (line, run)
    assert not alarm_wanted(False, RUNNING, None, True, False, True), "selector MANUAL"


def test_the_pre_move_warning_sounds_it_whatever_the_fields_say():
    """2026-10-08: a Start under AUTO sounds the alarm horn before the vehicle moves - tape
    in LineState ARMED, trackless while RunState.premove - with no field data at all."""
    assert alarm_wanted(True, ARMED, None, False, True, False)
    assert alarm_wanted(True, None, EXECUTING, False, True, False, run_premove=True)
    assert not alarm_wanted(True, None, EXECUTING, True, True, False, run_premove=False)
    assert not alarm_wanted(False, ARMED, None, True, True, False), "selector MANUAL"
    # nothing turns during it, so the movement horn stays off; once moving, it takes over
    assert motion_outputs(False, True, [0, 8], [0]) == {0: False, 8: False}
    assert motion_outputs(True, alarm_wanted(True, RUNNING, None, True, True, False), [0, 8], [0]) == {
        0: True, 8: True
    }


def test_stale_field_data_does_not_sound_it():
    assert not alarm_wanted(True, RUNNING, None, False, False, True)


def test_a_field_switches_the_movement_horn_to_the_alarm_horn():
    """Operator, 2026-10-07: on warning 1, warning 2 or protective the sound changes - DO00
    (movement horn) off while DO01 (alarm) sounds; DO08 keeps following the motors."""
    for line, run, protective_clear in ((RUNNING, None, True), (None, EXECUTING, True), (RUNNING, None, False)):
        alarm = alarm_wanted(True, line, run, True, protective_clear, True)
        assert alarm
        assert motion_outputs(True, alarm, [0, 8], [0]) == {0: False, 8: True}
    assert motion_outputs(True, False, [0, 8], [0]) == {0: True, 8: True}, "no field: movement horn"
    assert motion_outputs(False, False, [0, 8], [0]) == {0: False, 8: False}, "stopped: both off"
    assert motion_outputs(False, True, [0, 8], [0]) == {0: False, 8: False}, "stopped by protective: alarm only"


# ---- the stop call (manuals/stop-call-alarm-plan.md, owner 2026-11-13) ----


def test_a_stop_waiting_for_attach_or_release_calls_in_auto():
    assert CALL_CAUSES == ("station", "payload", "trolley")
    for cause in CALL_CAUSES:
        assert call_wanted(True, HOLD, cause, True), cause


def test_no_call_in_manual_on_stale_line_state_or_for_other_holds():
    assert not call_wanted(False, HOLD, "station", True), "selector MANUAL"
    assert not call_wanted(True, HOLD, "station", False), "line layer gone quiet"
    for cause in ("estop", "field", "rfid", "markers", "position", "prereq", "authority", "drive_fault", ""):
        assert not call_wanted(True, HOLD, cause, True), cause
    # a Start took it to ARMED; a Reset or the end of the run to IDLE / DONE
    for state in (0, ARMED, RUNNING, DONE, 5, None):
        assert not call_wanted(True, state, "station", True), state


def test_the_call_pulses_from_the_start_of_the_hold():
    on = [call_phase(t / 10, 0.0, 1.0, 2.0) for t in range(0, 61)]
    assert on[0] and on[9] and not on[10] and not on[29] and on[30] and on[39] and not on[40]
    assert call_phase(100.5, 100.0, 1.0, 2.0) and not call_phase(101.5, 100.0, 1.0, 2.0)


def test_off_time_zero_is_continuous_and_on_time_zero_is_silent():
    assert all(call_phase(t / 10, 0.0, 1.0, 0.0) for t in range(100))
    assert not any(call_phase(t / 10, 0.0, 0.0, 2.0) for t in range(100))


def test_a_field_at_a_stop_keeps_the_alarm_continuous():
    """panel_node sounds hazard OR (call AND phase): in the call's off phase a field still sounds."""
    hazard = alarm_wanted(True, HOLD, None, True, True, True)
    off_beat = call_wanted(True, HOLD, "station", True) and call_phase(1.5, 0.0, 1.0, 2.0)
    assert hazard and not off_beat and (hazard or off_beat)
