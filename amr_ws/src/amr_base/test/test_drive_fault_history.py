"""Unified plan WP-B4 (H-P0-5), the 2026-11-16 open parts: the drive's own alarm history
(603Fh, 1003h) read by preflight into the fault detail, the boot-up frame as a `rebooted`
input to decide(), and the fault code DriveStatus reports chosen by decide(), not by text."""

import can
from test_canopen import FakeBus, _arm, _link, _Node2CanDie

from amr_base import canopen
from amr_base.canopen import ARMED, DISARMED, FAULT, STANDBY, decide


def _history(bus, node, last, errors):
    bus.objects[(node, 0x603F, 0)] = last
    bus.objects[(node, 0x1003, 0)] = len(errors)
    for i, e in enumerate(errors, start=1):
        bus.objects[(node, 0x1003, i)] = e


def test_preflight_reads_603f_and_1003h_into_the_report_and_writes_nothing():
    bus = FakeBus()
    _history(bus, 1, 0xFF81, [0x8130, 0xFF81])  # left: heartbeat lost, then network bus error
    link = _link(bus)  # right: 603Fh/1003h answer with an abort (an empty 1003h reads :00 = 0)
    ok, report = link.preflight()
    assert ok and bus.writes == []
    assert link.preflight_history[1] == {"603F": 0xFF81, "1003": [0x8130, 0xFF81]}
    assert link.preflight_history[2] == {"603F": None, "1003": None}
    left = next(r for r in report if r.startswith("node 1") and "603Fh" in r)
    assert "FF81h Network bus error" in left and "8130h Heartbeat" in left
    reads = [(m.data[1] | m.data[2] << 8, m.data[3]) for m in bus.sent if m.arbitration_id == 0x601]
    assert (0x603F, 0) in reads and (0x1003, 0) in reads and (0x1003, 2) in reads and (0x1003, 3) not in reads


def test_an_empty_error_list_reads_no_entries_and_a_dead_drive_is_not_asked():
    bus = _Node2CanDie()
    bus.dead2 = True  # node 2 answers nothing: preflight's "not responding"
    _history(bus, 1, 0, [])
    link = _link(bus)
    ok, report = link.preflight()
    assert not ok
    assert link.preflight_history == {1: {"603F": 0, "1003": []}}
    assert any("last alarm 603Fh none; error history 1003h empty" in r for r in report)
    asked = {m.data[1] | m.data[2] << 8 for m in bus.sent if m.arbitration_id == 0x602}
    assert 0x603F not in asked and 0x1003 not in asked


def test_a_drive_in_fault_at_link_up_is_reported_with_its_history_in_the_failure():
    """The usual state after a PC crash: 8130h on the drive, preflight refuses. The refusal (the
    'arm' edge detail) and DriveStatus now name the cause the power cycle will erase from 1003h."""
    bus = FakeBus(statusword=0x0008)  # Fault
    _history(bus, 1, 0xFF81, [0x8130])
    link = _link(bus)
    try:
        link.prepare(20, None, 0, 30.0, False, False)
        raise AssertionError("prepare linked a faulted drive")
    except RuntimeError as e:
        assert "8130h" in str(e) and "603Fh" in str(e)
    assert link.state == DISARMED and link.preflight_faulted == [1, 2]
    code, detail = link.reported_fault()
    assert code == "DRIVE_FAULT"
    assert detail.startswith("a drive is in fault at link-up; left: last alarm 603Fh FF81h")
    assert "; right: " in detail


def test_a_clean_link_reports_no_fault_and_a_latched_fault_reports_decides_code():
    bus = FakeBus(statusword=0x1637)  # speed zero: the disarm below does not wait 4 s
    _history(bus, 2, 0xFF25, [])
    link = _link(bus)
    link.prepare(20, None, 0, 30.0, False, False)
    assert link.state == STANDBY and link.reported_fault() == ("", "")
    d = decide(STANDBY, True, False, 0.0, 0.0, [2], [], [])
    link.fault(d.reason, d.code)
    code, detail = link.reported_fault()
    assert code == "DRIVE_SILENT" and detail.startswith("drive silent: [2]; left: ")
    assert "right: last alarm 603Fh FF25h Undervoltage" in detail
    link.telemetry[1].alarm = {"hex": "8130h", "name": "Heartbeat / node guarding error"}
    assert "left: EMCY 8130h Heartbeat / node guarding error; last alarm" in link.reported_fault()[1]
    link.disarm()
    link.prepare(20, None, 0, 30.0, False, False)
    assert link.fault_code is None and link.reported_fault() == ("", "")


def test_decide_names_the_code_and_puts_a_reboot_first():
    assert decide(STANDBY, True, False, 0, 0, [1], [], []).code == "DRIVE_SILENT"
    assert decide(ARMED, True, True, 0, 0, [], [], [2]).code == "DRIVE_FAULT"
    d = decide(ARMED, True, True, 0, 0, [1], [], [], rebooted=[1])
    assert d.action == "fault" and d.code == "DRIVE_REBOOTED" and "rebooted: [1]" in d.reason
    assert "1016h" in d.reason
    assert decide(STANDBY, True, False, 0, 0, [], [], [], rebooted=[2]).action == "fault"
    # never links, unlinks or re-faults on it by itself
    assert decide(DISARMED, True, False, 10.0, 10.0, [], [], [], rebooted=[1]).action == "prepare"
    assert decide(FAULT, True, True, 0, 0, [], [], [], rebooted=[1]).action == "none"
    assert decide(STANDBY, False, False, 0, 0, [], [], [], rebooted=[1]).action == "disarm"
    assert decide(ARMED, True, True, 0, 0, [], [], []).code == ""  # only a fault carries one


def _frame(cob, data):
    return can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=False)


def test_a_boot_up_frame_after_link_up_marks_the_drive_rebooted():
    bus = FakeBus(statusword=0x1637)
    link = _link(bus)
    bus.rx.append(_frame(0x701, [0x00]))  # booted before we linked: not a reboot under us
    link.router.pump(0.01)
    link.telemetry[1].t_boot -= 1.0  # (a coarse dev-box clock would tie it with t_armed)
    _arm(link, 20, None, 0, 30.0, False, False)
    assert link.state == ARMED and link.rebooted_nodes() == []
    link.t_armed -= 0.5
    bus.rx.append(_frame(0x702, [0x05]))  # an ordinary heartbeat (Operational)
    link.router.pump(0.01)
    assert link.rebooted_nodes() == []
    bus.rx.append(_frame(0x702, [0x00]))
    link.router.pump(0.01)
    assert link.rebooted_nodes() == [2] and link.telemetry[2].nmt == "Boot-up"
    d = decide(link.state, True, True, 0, 0, [], [], [], rebooted=link.rebooted_nodes())
    assert d.action == "fault"
    link.fault(d.reason, d.code)
    assert link.reported_fault()[0] == "DRIVE_REBOOTED" and "rebooted" in link.reported_fault()[1]


def test_history_text_spells_every_case():
    assert canopen.history_text(None) == "alarm history not read"
    assert canopen.history_text({"603F": None, "1003": None}) == (
        "last alarm 603Fh unread; error history 1003h unread")
    assert canopen.alarm_code_text(0x1234).startswith("1234h unknown alarm")
    # a 1003h entry's high word is "additional information" (unused by the BLV-R): ignored
    assert "8130h" in canopen.history_text({"603F": 0, "1003": [0xABCD8130]})


def test_the_fault_code_is_never_read_back_from_the_reason_text():
    """drive_node's substring map (_fault_code) is retired: the code comes from decide()."""
    import pathlib

    src = (pathlib.Path(canopen.__file__).parent / "drive_node.py").read_text(encoding="utf-8")
    assert "_fault_code(" not in src
    assert "link.fault(d.reason, d.code)" in src
    assert 'if hasattr(m, "fault_code")' in src  # publishes before amr_interfaces is rebuilt
