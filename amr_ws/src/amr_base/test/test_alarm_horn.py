"""DO01 alarm horn (operator, 2026-10-02): AUTO RUNNING and (protective stop OR warning 1
OR warning 2). Running = tracked line RUNNING/HOLD or trackless EXECUTING/BLOCKED."""

from amr_base.panel_io import alarm_wanted

RUNNING, HOLD, ARMED, DONE = 2, 3, 1, 4  # LineState
EXECUTING, PAUSED, BLOCKED = 2, 3, 4  # RunState


def test_auto_run_with_a_field_occupied_sounds_it():
    for line, run in ((RUNNING, None), (HOLD, None), (None, EXECUTING), (None, BLOCKED)):
        assert alarm_wanted(True, line, run, True, True, True), (line, run)  # warning 1 or 2
        assert alarm_wanted(True, line, run, True, False, True), (line, run)  # protective stop


def test_no_field_no_alarm():
    assert not alarm_wanted(True, RUNNING, None, True, True, False)


def test_not_running_or_not_auto_is_silent():
    for line, run in ((ARMED, None), (DONE, None), (None, PAUSED), (None, None)):
        assert not alarm_wanted(True, line, run, True, False, True), (line, run)
    assert not alarm_wanted(False, RUNNING, None, True, False, True), "selector MANUAL"


def test_stale_field_data_does_not_sound_it():
    assert not alarm_wanted(True, RUNNING, None, False, False, True)
