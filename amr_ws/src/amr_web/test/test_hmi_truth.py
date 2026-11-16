"""HMI truthfulness (unified plan WP-H2, hardening plan H-P1-2, 2026-11-16): the standing list says
what the base lacks, what each device link is doing and what the scanners report, and the Home
headline says what its tile says. No ROS: the adapter's pure half is amr_web.health_view."""

import json
import os
import types
import zipfile

from agv_core import alarms as cat
from agv_core import health

from amr_web import alarms as view
from amr_web import health_view, reports

READY = {
    "mode": {"mode_name": "IDLE", "fault_code": "", "reason": "", "base_ready": True, "generation": 1,
             "base_missing": ""},
    "mode_age_s": 0.1,
    "panel": {"valid": True, "mode_auto": False, "age_s": 0.05},
    "drives": {"operational": True, "left": "Operation enabled", "right": "Operation enabled", "age_s": 0.05,
               "link": "armed", "fault_code": "", "fault_detail": ""},
    "mux": {"inhibited": False, "source": "none", "reason": "", "code": "NO_SOURCE", "age_s": 0.05},
    "run": None,
    "localization": None,
    "scan_age_s": 0.05,
    "up_s": 300.0,
}


def st(**over):
    s = json.loads(json.dumps(READY))
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


def codes(state):
    return [r["code"] for r in view.standing(state)]


def test_a_healthy_state_still_stands_nothing():
    assert view.standing(st()) == []


# ---- base_missing ----------------------------------------------------------------------------


def test_base_missing_is_a_named_row_never_the_vehicle_is_fine():
    s = st(mode={"base_missing": "mux, wheel feedback"})
    rows = view.standing(s)
    assert [r["code"] for r in rows] == ["BASE_NOT_READY"]
    assert rows[0]["detail"] == "missing: mux, wheel feedback"
    h = view.headline(s, rows)
    assert h["title"] != "The vehicle is fine." and h["code"] == "BASE_NOT_READY"


def test_base_missing_names_only_what_no_other_row_explains():
    s = st(mode={"base_missing": "panel"}, panel={"valid": False})
    assert codes(s) == ["PANEL_STALE"]
    s = st(mode={"base_missing": "drives, mux"},
           drives={"operational": False, "left": "Switch on disabled", "right": "Switch on disabled"})
    rows = view.standing(s)
    assert {r["code"] for r in rows} == {"BASE_NOT_READY", "SAFETY_RESET_NEEDED"}
    assert next(r for r in rows if r["code"] == "BASE_NOT_READY")["detail"] == "missing: mux"


def test_not_while_starting_and_the_headline_waits_instead():
    s = st(mode={"mode_name": "STARTING", "base_ready": False, "base_missing": "mux, wheel feedback"})
    assert "BASE_NOT_READY" not in codes(s)
    h = view.headline(st(mode={"mode_name": "STARTING", "base_ready": False, "base_missing": "mux"}), [])
    assert h["state"] == view.NOT_READY and h["title"] == "Starting up" and "mux" in h["detail"]


# ---- the LINE headline follows the tile ----------------------------------------------------------


def _line(state_name, **kw):
    return st(mode={"mode_name": "LINE"}, line=dict({"state_name": state_name, "code": "", "message": "",
                                                    "hold_cause": "", "auto_resume": False}, **kw))


def test_the_line_headline_says_what_the_tile_says():
    for name, big in (("RUNNING", view.RUNNING), ("ARMED", view.RUNNING)):
        s = _line(name)
        rows = view.standing(s)
        assert view.headline(s, rows)["state"] == big == view.home_tile(s, rows)["big"]
    s = _line("HOLD", code="FIELD_BLOCKED", hold_cause="field", auto_resume=True, message="field")
    rows = view.standing(s)
    assert view.headline(s, rows)["state"] == view.STOPPED_WILL_RESUME == view.home_tile(s, rows)["big"]
    s = _line("HOLD", code="PANEL_LINK_LOST", hold_cause="panel", auto_resume=False, message="panel")
    rows = view.standing(s)
    assert view.headline(s, rows)["state"] == view.STOPPED_NEEDS_YOU == view.home_tile(s, rows)["big"]
    s = _line("FAULT", code="TRACK_LOST", message="lost")
    rows = view.standing(s)
    assert view.headline(s, rows)["state"] == view.STOPPED_NEEDS_YOU == view.home_tile(s, rows)["big"]


# ---- panel and device health -----------------------------------------------------------------------


def test_panel_stale_names_the_io_island_from_the_profile():
    rows = view.standing(st(panel={"valid": False}, dio_ip="192.168.1.30"))
    assert rows[0]["code"] == "PANEL_STALE" and "192.168.1.30" in rows[0]["detail"]
    assert "192.168.1.30" not in cat.CATALOGUE["PANEL_STALE"].hint  # sourced, not hard-coded


def _health(**rows):
    fitted = health.configured(types.SimpleNamespace(REAR_SOURCE="none", STATION_ENABLED=False))
    got = {d: (r, 100.0) for d, r in rows.items()}
    for d in ("drive_left", "drive_right", "can_bus", "mls_track", "mls_gyro", "dio"):
        got.setdefault(d, (health.Row(d, health.OK), 100.0))
    return health_view.view(got, 100.5, fitted, 300.0)


def test_device_health_rows_stand_and_the_io_island_hides_panel_stale():
    dh = _health(dio=health.Row("dio", health.LOST, "IO_ISLAND_LOST", "no scan for 3.0 s: timeout"))
    rows = view.standing(st(panel={"valid": False}, device_health=dh))
    assert [r["code"] for r in rows] == ["IO_ISLAND_LOST"]
    assert "timeout" in rows[0]["detail"]


def test_a_shared_cause_is_one_row():
    lost = {d: health.Row(d, health.LOST, health.LOST_CODE[d], "gone") for d in ("drive_left", "drive_right",
                                                                              "mls_track")}
    rows = view.standing(st(device_health=_health(**lost)))
    assert codes(st(device_health=_health(**lost))) == ["CAN_BUS_LOST"] and "gone" in rows[0]["detail"]


def test_no_health_at_all_accuses_nothing_but_a_silent_owner_does():
    assert health_view.view({}, 100.0, {"dio": True}, 300.0) is None
    assert view.standing(st(device_health=None)) == []
    fitted = {d: d == "dio" or d.startswith("drive") for d in health.DEVICES}
    rows = {d: (health.Row(d, health.OK), 100.0) for d in ("drive_left", "drive_right")}
    dh = health_view.view(rows, 100.5, fitted, 300.0)
    assert dh["dio"]["state"] == health.LOST  # panel_node never reported
    assert "IO_ISLAND_LOST" in codes(st(device_health=dh))


def test_unfitted_devices_never_stand():
    fitted = health.configured(types.SimpleNamespace(REAR_SOURCE="none", STATION_ENABLED=False))
    assert not fitted["rear_scanner"] and not fitted["station_link"]
    dh = _health(rear_scanner=health.Row("rear_scanner", health.LOST, "REAR_SCANNER_SILENT", "x"))
    assert dh["rear_scanner"]["state"] == health.ABSENT and view.standing(st(device_health=dh)) == []


def test_row_from_msg_reads_the_wire_tables():
    m = types.SimpleNamespace(device=5, state=2, code="DIO_SCAN_RETRIED", detail="1 retried", age_s=0.02,
                              since_s=3.0, gaps=1, rejects=0, reconnects=0, timeouts=4)
    r = health_view.row_from_msg(m)
    assert (r.device, r.state, r.code, r.timeouts) == ("dio", health.DEGRADED, "DIO_SCAN_RETRIED", 4)
    assert health_view.row_from_msg(types.SimpleNamespace(device=99)) is None


# ---- drives -------------------------------------------------------------------------------------------


def test_drive_node_fault_code_wins_and_its_detail_is_the_row_detail():
    s = st(drives={"operational": False, "link": "fault", "left": "stale", "right": "Operation enabled",
                   "fault_code": "DRIVE_REBOOTED", "fault_detail": "left: boot-up frame after link-up"})
    rows = view.standing(s)
    assert rows[0]["code"] == "DRIVE_REBOOTED" and rows[0]["detail"] == "left: boot-up frame after link-up"
    s["mux"] = {"inhibited": True, "code": "DRIVES_NOT_READY", "reason": "x", "source": "none", "age_s": 0.1}
    assert "DRIVES_NOT_READY" not in codes(s)  # the named fault says it, and more


# ---- scanners, disk, event record ------------------------------------------------------------------


def _scanner_state(level=0, **values):
    return {"sick_safetyscanners2_node: State": {
        "name": "sick_safetyscanners2_node: State", "hardware_id": "192.168.3.10", "level": level,
        "message": "", "age_s": 0.5,
        "values": {k.replace("_", " ").capitalize(): v for k, v in values.items()}}}


def test_scanner_diagnosis_stands_on_a_fresh_scan_only():
    diag = _scanner_state(2, contamination_error="True")
    assert "SCANNER_CONTAMINATED" in codes(st(diagnostics=diag))
    assert "SCANNER_CONTAMINATED" not in codes(st(diagnostics=diag, scan_age_s=30.0))  # SCANNER_STALE says it
    rows = codes(st(diagnostics=_scanner_state(0), scanner_overview={"front": {"config_state": 3,
                                                                                "error_info_code": 0}}))
    assert rows == ["SCANNER_CONFIG_UNVERIFIED"]
    assert view.standing(st(diagnostics=_scanner_state(0))) == []


def test_a_read_only_disk_and_a_failing_event_record_stand():
    disk = {"free_mb": 9000, "level": "ok", "path": "/", "readonly": "/home"}
    assert "DISK_READONLY" in codes(st(disk=disk))
    rec = {"eventlog/recorder": {"name": "eventlog/recorder", "level": 2, "message": "write failing",
                                 "hardware_id": "/s/logs/recorded_events.jsonl", "values": {}, "age_s": 1.0}}
    assert codes(st(diagnostics=rec)) == ["EVENTLOG_WRITE_FAILED"]
    rec["eventlog/recorder"]["age_s"] = 30.0  # a dead recorder's last status is not a reading
    assert view.standing(st(diagnostics=rec)) == []


def test_statuses_keeps_only_what_standing_reads():
    diag = dict(_scanner_state(0), **{"drive/left": {}, "eventlog/recorder": {}, "can/bus": {}})
    assert set(health_view.statuses(diag)) == {"sick_safetyscanners2_node: State", "eventlog/recorder"}


def test_status_overview_is_asked_on_a_level_change_and_retried_until_answered():
    p = health_view.OverviewPoll(retry_s=30.0)
    assert not p.want(0.0)  # no State seen yet
    p.level(0)
    assert p.want(1.0) and not p.want(2.0)  # asked; a retry waits
    assert p.want(32.0)  # no answer: asked again
    p.answered()
    p.level(0)
    assert not p.want(40.0)  # same level, answered: not asked again
    p.level(2)
    assert p.want(41.0)
    assert health_view.overview_of(types.SimpleNamespace(config_state=5)) == {"config_state": 5,
                                                                              "error_info_code": 0}


def test_supply_limits_come_from_the_monitor_block():
    th = {"bus_v": {"warn_low": 46.0, "trip_low": 44.0, "warn": 56.0}}
    assert health_view.supply_limits(th) == {"warn_low": 46.0, "trip_low": 44.0, "warn_high": 56.0}
    assert health_view.supply_limits({"bus_v": {}}) == {}


def test_the_report_carries_the_recorded_events(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    for n in ("recorded_events.jsonl", "recorded_events.jsonl.1", "events.jsonl", "base.log"):
        (logs / n).write_text("x\n")
    names = {os.path.basename(p) for p in reports._role_logs(str(tmp_path))}
    assert {"recorded_events.jsonl", "recorded_events.jsonl.1", "base.log"} <= names
    assert "events.jsonl" not in names  # the web's own file goes in as event_files


def test_the_report_zip_has_them(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "recorded_events.jsonl").write_text('{"code": "X"}\n')
    monkeypatch.setattr(reports, "_journal_of", lambda unit: "")
    name = reports.build(str(tmp_path), {}, [], {}, [], note="t")
    with zipfile.ZipFile(os.path.join(reports._dir(str(tmp_path)), name)) as z:
        assert "logs/recorded_events.jsonl" in z.namelist()
