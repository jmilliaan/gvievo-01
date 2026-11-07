"""The operator's action for a base that did not come up: a drive fault is not the safety chain."""

import types

from amr_bringup import readiness as rd


def snap(left, right):
    s = rd.Snapshots()
    s.on_drives(
        types.SimpleNamespace(operational=False, link_state="disarmed", left_state=left, right_state=right)
    )
    return s


def test_a_drive_fault_says_power_cycle_not_reset():
    a = rd.base_actions(snap("FAULT", "FAULT"))
    assert "off and on" in a["wheel feedback"] and "off and on" in a["drives"]
    assert "safety reset" not in a["wheel feedback"]


def test_one_faulted_drive_is_enough():
    assert "off and on" in rd.base_actions(snap("Ready to switch on", "Fault reaction active"))["drives"]


def test_the_safety_chain_still_says_reset():
    for s in (rd.Snapshots(), snap("Switch on disabled", "Switch on disabled"), snap("-", "-")):
        assert "safety reset" in rd.base_actions(s)["wheel feedback"]
