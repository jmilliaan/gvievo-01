"""amr_base.drive_state: one reading of DriveStatus / WheelStates / OutputPaths (lean D30)."""

from amr_base import drive_state as ds


def test_torque_off_needs_both_not_operational_and_no_drive_enabled():
    assert ds.torque_off(False, "Switch on disabled", "Switch on disabled")
    assert not ds.torque_off(False, "Operation enabled", "Switch on disabled")  # feedback loss only
    assert not ds.torque_off(True, "Switch on disabled", "Switch on disabled")


def test_still_keeps_each_callers_comparison():
    assert ds.still(0.02, -0.02, 0.02) and not ds.still(0.02, 0.0, 0.02, inclusive=False)
    assert not ds.still(0.0, 0.0, 0.02, valid=False)


def test_field_clear_and_a_malformed_array():
    assert ds.field_clear([True, False], 0) is True and ds.field_clear([True, False], 1) is False
    assert ds.field_clear([True], 2) is None and ds.field_clear(None, 0) is None


def test_the_names_match_the_decoder_and_the_link():
    from agv_core.drivers.canbus import cia402

    names = {n for _, _, n in cia402.CIA402_STATES}
    assert {ds.OPERATION_ENABLED, ds.SWITCH_ON_DISABLED, *ds.STANDBY_STATES} <= names
    import pytest

    canopen = pytest.importorskip("amr_base.canopen")
    assert canopen.STANDBY == ds.LINK_STANDBY
    assert canopen.FAULT == ds.LINK_FAULT
