"""DO01 alarm horn (operator, 2026-10-02): AUTO RUNNING and (protective stop OR warning 1
OR warning 2). Running = RunState EXECUTING/BLOCKED."""

from amr_base.panel_io import alarm_wanted, motion_outputs

IDLE, EXECUTING, PAUSED, BLOCKED, FAULT, DONE = 0, 2, 3, 4, 5, 6  # RunState


def test_auto_run_with_a_field_occupied_sounds_it():
    for run in (EXECUTING, BLOCKED):
        assert alarm_wanted(True, run, True, True, True), run  # warning 1 or 2
        assert alarm_wanted(True, run, True, False, True), run  # protective stop


def test_no_field_no_alarm():
    assert not alarm_wanted(True, EXECUTING, True, True, False)


def test_not_running_or_not_auto_is_silent():
    for run in (IDLE, PAUSED, FAULT, DONE, None):
        assert not alarm_wanted(True, run, True, False, True), run
    assert not alarm_wanted(False, EXECUTING, True, False, True), "selector MANUAL"


def test_the_pre_move_warning_sounds_it_whatever_the_fields_say():
    """2026-10-08: a Start under AUTO sounds the alarm horn before the vehicle moves - while
    RunState.premove - with no field data at all."""
    assert alarm_wanted(True, EXECUTING, False, True, False, run_premove=True)
    assert alarm_wanted(True, None, False, True, False, run_premove=True)
    assert not alarm_wanted(True, EXECUTING, True, True, False, run_premove=False)
    assert not alarm_wanted(False, EXECUTING, True, True, False, run_premove=True), "selector MANUAL"
    # nothing turns during it, so the movement horn stays off; once moving, it takes over
    assert motion_outputs(False, True, [0, 8], [0]) == {0: False, 8: False}
    assert motion_outputs(True, alarm_wanted(True, EXECUTING, True, True, False), [0, 8], [0]) == {
        0: True, 8: True
    }


def test_stale_field_data_does_not_sound_it():
    assert not alarm_wanted(True, EXECUTING, False, False, True)


def test_a_field_switches_the_movement_horn_to_the_alarm_horn():
    """Operator, 2026-10-07: on warning 1, warning 2 or protective the sound changes - DO00
    (movement horn) off while DO01 (alarm) sounds; DO08 keeps following the motors."""
    for run, protective_clear in ((EXECUTING, True), (BLOCKED, True), (EXECUTING, False)):
        alarm = alarm_wanted(True, run, True, protective_clear, True)
        assert alarm
        assert motion_outputs(True, alarm, [0, 8], [0]) == {0: False, 8: True}
    assert motion_outputs(True, False, [0, 8], [0]) == {0: True, 8: True}, "no field: movement horn"
    assert motion_outputs(False, False, [0, 8], [0]) == {0: False, 8: False}, "stopped: both off"
    assert motion_outputs(False, True, [0, 8], [0]) == {0: False, 8: False}, "stopped by protective: alarm only"
