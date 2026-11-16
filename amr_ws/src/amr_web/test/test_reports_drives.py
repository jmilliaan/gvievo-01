"""amr_web.reports: the drives' alarm history in the report zip (unified plan WP-B4)."""

import zipfile

from amr_web import reports

DIAG = {
    "can/bus": {"values": {"link_state": "fault", "fault_code": "DRIVE_SILENT",
                           "fault_reason": "drive silent: [2]"}},
    "drive/left": {"hardware_id": "node 1", "values": {
        "state": "Operation enabled", "alarm_history_603F": "FF81h Network bus error",
        "error_history_1003": "8130h Heartbeat / node guarding error", "boot_up_age_s": ""}},
    "drive/right": {"hardware_id": "node 2", "values": {
        "state": "stale", "alarm": "0x8130 Heartbeat / node guarding error",
        "alarm_history_603F": "none", "error_history_1003": "empty", "boot_up_age_s": "3.2"}},
    "imu/mls": {"values": {"mode": "sdo"}},
}


def test_drive_history_names_the_link_fault_and_each_drives_history():
    text = reports.drive_history(DIAG)
    lines = text.splitlines()
    assert lines[0] == "link fault; fault: DRIVE_SILENT drive silent: [2]"
    assert lines[1].startswith("left (node 1): state Operation enabled; alarm none; ")
    assert "last alarm 603Fh FF81h Network bus error" in lines[1] and "boot-up" not in lines[1]
    assert "alarm 0x8130 Heartbeat" in lines[2] and "error history 1003h empty" in lines[2]
    assert lines[2].endswith("boot-up frame 3.2 s ago") and len(lines) == 3


def test_drive_history_without_drive_node_says_so():
    assert reports.drive_history({}) == "(no drive diagnostics received)\n"
    # an older drive_node (no history keys yet) still gives a readable line
    old = {"drive/left": {"hardware_id": "node 1", "values": {"state": "Switch on disabled"}}}
    assert "603Fh not read; error history 1003h not read" in reports.drive_history(old)


def test_the_report_zip_carries_drives_txt(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "_journal", lambda: "(journal)\n")
    name = reports.build(str(tmp_path), state={}, events=[], diagnostics=DIAG, event_files=[], note="x")
    with zipfile.ZipFile(reports.path_of(str(tmp_path), name)) as z:
        assert z.read("drives.txt").decode() == reports.drive_history(DIAG)
