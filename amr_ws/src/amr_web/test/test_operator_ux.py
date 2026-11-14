"""The operator surface: one catalogue, one standing list, one button (plan phases 0-3).

These tests exist because every page used to derive "what is wrong" in its own
JavaScript, in its own words, with no action attached. The contract now is:
`/api/alarms` decides, the pages render. So the assertions here are about wording
and about which button the operator is offered - not about internals.
"""

import json
import os
import re
import zipfile
from pathlib import Path

import pytest
from agv_core import alarms as cat
from amr_web.eventlog import EventLog
from amr_web.server import create_app

from amr_web import alarms as view
from amr_web import reports, role


class Stub:
    def __init__(self, state=None):
        self._state = state or {}
        self.emitted = []
        self.calls = []

    def state(self):
        return self._state

    def events(self, since=0):
        return [{"n": 1, "t": 0.0, "source": "x", "level": "warn", "code": "ESTOP", "text": "t", "seq": 1}]

    def diagnostics(self):
        return {}

    def event_log_files(self):
        return []

    def emit(self, level, code, text, source="amr_web"):
        self.emitted.append((level, code, text))

    def __getattr__(self, name):
        def fn(*a):
            self.calls.append((name, a))
            return True, f"{name} ok"

        return fn


def app_for(state, tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    stub = Stub(state)
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    return app.test_client(), stub


READY_STATE = {
    "mode": {"mode_name": "IDLE", "fault_code": "", "reason": "", "base_ready": True, "generation": 1},
    "mode_age_s": 0.1,
    "panel": {"valid": True, "mode_auto": False, "age_s": 0.05},
    "drives": {"operational": True, "left": "Operation enabled", "right": "Operation enabled", "age_s": 0.05},
    "mux": {"inhibited": False, "source": "none", "reason": "", "code": "NO_SOURCE", "age_s": 0.05},
    "run": None,
    "localization": None,
}


def merged(**over):
    st = json.loads(json.dumps(READY_STATE))
    st.update(over)
    return st


# ---- the standing list ----------------------------------------------------------


def test_a_healthy_vehicle_stands_nothing_and_offers_no_button():
    rows = view.standing(merged())
    assert rows == []
    h = view.headline(merged(), rows)
    assert h["state"] == view.READY and h["button"] == ""


def test_no_supervisor_is_the_only_thing_reported():
    """Without ModeState nothing else can be trusted, so one row, not six."""
    rows = view.standing({"mode": None})
    assert [r["code"] for r in rows] == ["SUPERVISOR_DOWN"]
    assert view.headline({"mode": None}, rows)["button"] == "Restart"


def test_switch_on_disabled_reads_as_the_cabinet_reset_not_a_broken_drive():
    """The 2026-09-22 case: the safety chain holds STO, the drives are fine."""
    st = merged(
        drives={
            "operational": False,
            "left": "Switch on disabled",
            "right": "Switch on disabled",
            "age_s": 0.05,
        }
    )
    rows = view.standing(st)
    assert rows[0]["code"] == "SAFETY_RESET_NEEDED"
    assert "reset" in rows[0]["action"].lower()


def test_a_disarmed_drive_at_idle_is_not_an_alarm():
    st = merged(
        drives={
            "operational": False,
            "left": "Ready to switch on",
            "right": "Ready to switch on",
            "age_s": 0.05,
        }
    )
    assert view.standing(st) == []


def test_a_field_stop_says_it_resumes_by_itself_and_offers_no_button():
    st = merged(
        run={
            "state_name": "BLOCKED",
            "hold_cause": "field",
            "fault_code": "FIELD_BLOCKED",
            "auto_resume": True,
            "reason": "safety stop",
            "mission_id": "m1",
            "step_index": 2,
        }
    )
    rows = view.standing(st)
    h = view.headline(st, rows)
    assert rows[0]["code"] == "FIELD_BLOCKED"
    assert h["state"] == view.STOPPED_WILL_RESUME and h["button"] == ""


def test_an_estop_hold_tells_the_operator_to_press_start():
    st = merged(
        run={
            "state_name": "BLOCKED",
            "hold_cause": "estop",
            "fault_code": "ESTOP",
            "auto_resume": False,
            "reason": "safety stop",
            "mission_id": "m1",
            "step_index": 0,
        }
    )
    h = view.headline(st, view.standing(st))
    assert h["state"] == view.STOPPED_NEEDS_YOU and "Start" in h["action"]


def test_an_executor_fault_offers_acknowledge():
    st = merged(run={"state_name": "FAULT", "fault_code": "EXEC_OFF_PATH", "reason": "cross-track"})
    h = view.headline(st, view.standing(st))
    assert h["button"] == "Acknowledge" and h["code"] == "EXEC_OFF_PATH"


def test_a_dead_base_offers_restart_and_says_needs_service():
    st = merged(
        mode={
            "mode_name": "FAULT",
            "fault_code": "BASE_EXITED",
            "reason": "base died",
            "base_ready": False,
            "generation": 1,
        }
    )
    h = view.headline(st, view.standing(st))
    assert h["state"] == view.NEEDS_SERVICE and h["button"] == "Restart"


def test_lost_localisation_sends_the_operator_to_the_run_page():
    st = merged(
        mode={"mode_name": "NAVIGATION", "fault_code": "", "reason": "", "base_ready": True, "generation": 1},
        localization={"state_name": "LOST", "code": "LOC_SCAN_MISMATCH", "reason": "beams through walls"},
    )
    rows = view.standing(st)
    assert rows[0]["code"] == "LOC_SCAN_MISMATCH"
    assert view.headline(st, rows)["button"] == "Set position"


def test_localisation_is_not_the_operators_problem_outside_navigation():
    st = merged(localization={"state_name": "UNLOCALIZED", "code": "LOC_NOT_SET", "reason": "no pose"})
    assert view.standing(st) == []


def test_an_unplugged_scanner_is_reported_at_all():
    """It reports nothing itself: the driver is an optional launch member, so the
    supervisor stays IDLE, the drives still jog, and before 2026-09-22 the operator had
    no way to learn the lidar was unplugged."""
    st = merged(scan_age_s=None, up_s=120.0)
    rows = view.standing(st)
    assert [r["code"] for r in rows] == ["SCANNER_SILENT"]
    assert "hand" in rows[0]["action"]  # manual driving is unaffected, and says so
    assert view.headline(st, rows)["state"] == view.READY  # a warning, not a stop


def test_a_scanner_that_dies_mid_run_is_reported_separately():
    st = merged(scan_age_s=30.0, up_s=300.0)
    assert [r["code"] for r in view.standing(st)] == ["SCANNER_STALE"]
    assert view.standing(merged(scan_age_s=0.1, up_s=300.0)) == []


def test_a_page_loaded_during_boot_does_not_accuse_the_scanner():
    assert view.standing(merged(scan_age_s=None, up_s=3.0)) == []


def test_a_low_disk_warns_and_a_full_one_is_an_error():
    warn = merged(disk={"free_mb": 800, "level": "warn", "path": "/home"})
    rows = view.standing(warn)
    assert [r["code"] for r in rows] == ["DISK_LOW"] and rows[0]["level"] == "warn"
    full = merged(disk={"free_mb": 100, "level": "stop", "path": "/home"})
    rows = view.standing(full)
    assert rows[0]["code"] == "DISK_FULL" and rows[0]["level"] == "error"
    assert "already running" in rows[0]["action"]  # a moving vehicle is not stopped
    assert view.standing(merged(disk={"free_mb": 9000, "level": "ok", "path": "/home"})) == []


def test_the_worst_alarm_is_first_and_a_code_is_never_repeated():
    st = merged(
        panel={"valid": False, "mode_auto": False, "age_s": 0.05},
        mux={
            "inhibited": True,
            "source": "none",
            "reason": "no panel authority",
            "code": "PANEL_STALE",
            "age_s": 0.05,
        },
    )
    rows = view.standing(st)
    assert [r["code"] for r in rows] == ["PANEL_STALE"]
    assert rows[0]["level"] == "error"


def test_every_standing_row_carries_an_action_the_operator_can_perform():
    st = merged(
        mode={
            "mode_name": "FAULT",
            "fault_code": "MUX_ACK_TIMEOUT",
            "reason": "no ack",
            "base_ready": True,
            "generation": 1,
        },
        run={"state_name": "FAULT", "fault_code": "EXEC_PREREQ_LOST", "reason": "wheels"},
    )
    for row in view.standing(st):
        assert row["title"] and row["action"].endswith(".")
        assert row["clears_by"] in cat.CLEARS


def test_since_is_kept_while_an_alarm_stands_and_dropped_when_it_clears():
    tracker = view.StandingTracker()
    st = merged(panel=None)
    rows = tracker.apply(view.standing(st), 100.0)
    assert rows[0]["since"] == 100.0
    rows = tracker.apply(view.standing(st), 130.0)
    assert rows[0]["since"] == 100.0 and rows[0]["for_s"] == 30.0
    tracker.apply(view.standing(merged()), 140.0)
    rows = tracker.apply(view.standing(st), 150.0)
    assert rows[0]["since"] == 150.0  # it cleared in between: the clock restarts


# ---- the endpoints ---------------------------------------------------------------


def test_api_alarms_serves_the_list_and_the_headline(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    d = client.get("/api/alarms").get_json()
    assert d["alarms"] == [] and d["headline"]["state"] == view.READY
    assert d["tile"]["kind"] == "ready" and d["tile"]["level"] == view.TILE_OK


def test_events_carry_the_catalogue_title(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    rows = client.get("/api/events").get_json()
    assert rows[0]["title"] == cat.CATALOGUE["ESTOP"].title


def test_a_fresh_session_lands_on_the_engineer_view(tmp_path):
    """2026-10-24: Status merged into Home; both roles land there, the engineer with More open."""
    client, _ = app_for(merged(), tmp_path)
    assert client.get("/").headers["Location"].endswith("/home")
    assert client.get("/api/role").get_json()["role"] == role.ENGINEER
    body = client.get("/home").get_data(as_text=True)
    assert '<details class="home-more" open>' in body and 'id="home-ready"' in body
    assert client.get("/status").status_code == 404


def test_the_home_page_is_the_operators_landing_page(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    assert client.get("/").headers["Location"].endswith("/home")
    body = client.get("/home").get_data(as_text=True)
    assert 'id="home-primary"' in body
    # the panel drawing carries every button the tile may ask for
    assert 'id="home-press"' in body
    assert all(f'data-b="{b}"' in body for b in view.PANEL_BUTTONS)
    # the operator's nav: no Params, no Monitor, no Commission
    assert "/params" not in body and "/monitor" not in body
    assert "/run" in body and "/alarms" in body


def test_the_engineer_pin_opens_the_engineering_nav(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    assert client.post("/api/role", json={"role": "engineer", "pin": "0000"}).status_code == 403
    assert client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN}).status_code == 200
    body = client.get("/home").get_data(as_text=True)
    assert "/params" in body and "/monitor" in body
    # 2026-10-24: no Status tab (merged into Home) and no Commission page at all
    assert 'href="/status"' not in body and "/commissioning" not in body
    assert client.get("/commissioning").status_code == 404
    assert client.get("/api/commissioning").status_code == 404
    # and the way back is always open: a guard you cannot leave is a trap
    assert client.post("/api/role", json={"role": "operator"}).status_code == 200
    assert "/params" not in client.get("/home").get_data(as_text=True)


def test_only_the_engineer_gets_an_unconditional_restart_button(tmp_path):
    """The operator gets Restart on Home only when an alarm says the base cannot be
    rebuilt; an engineer restarts for other reasons (a rebuilt overlay, a changed env).
    Since 2026-10-24 the engineer's block (readiness, idle/recover/restart) is on Home."""
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    home = client.get("/home").get_data(as_text=True)
    assert 'id="btn-restart"' not in home and 'id="home-ready"' not in home
    assert '<details class="home-more">' in home, "the operator's More stays closed"
    client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN})
    home = client.get("/home").get_data(as_text=True)
    for i in ("btn-restart", "btn-recover", "btn-line", "home-ready"):
        assert f'id="{i}"' in home, i


def test_the_pin_lives_outside_the_repository_and_can_be_overridden(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    assert role.pin(state_dir) == role.DEFAULT_PIN
    written = tmp_path / "state" / "web.json"
    assert written.exists() and oct(os.stat(written).st_mode)[-3:] == "600"
    monkeypatch.setenv("AMR_WEB_ENGINEER_PIN", "4242")
    assert role.pin(state_dir) == "4242" and role.check(state_dir, "4242")


def test_restart_is_refused_while_the_wheels_turn(tmp_path):
    st = merged(
        mux={
            "inhibited": False,
            "source": "manual",
            "reason": "",
            "code": "",
            "left_rad_s": 1.2,
            "right_rad_s": 1.2,
            "age_s": 0.05,
        }
    )
    client, _ = app_for(st, tmp_path)
    r = client.post("/api/service/restart")
    assert r.status_code == 409 and "turning" in r.get_json()["message"]


def test_restart_is_refused_while_a_run_is_live(tmp_path):
    st = merged(run={"state_name": "EXECUTING", "mission_id": "m1", "step_index": 1})
    client, _ = app_for(st, tmp_path)
    assert client.post("/api/service/restart").status_code == 409


def test_a_page_error_becomes_an_event(tmp_path):
    client, stub = app_for(merged(), tmp_path)
    client.post("/api/page-error", json={"where": "/run", "what": "x is not defined"})
    assert stub.emitted and stub.emitted[0][1] == "WEB_BUG"


def test_an_unhandled_bug_answers_json_with_a_reference(tmp_path):
    client, stub = app_for(merged(), tmp_path)

    @client.application.get("/api/boom")
    def boom():
        raise RuntimeError("kaboom")

    r = client.get("/api/boom")
    assert r.status_code == 500
    body = r.get_json()
    assert body["code"] == "WEB_BUG" and len(body["ref"]) == 8
    assert "kaboom" not in r.get_data(as_text=True)  # never a stack trace on the panel
    assert stub.emitted[-1][1] == "WEB_BUG"


def test_a_report_packages_the_evidence(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    r = client.post("/api/report", json={"note": "it stopped"})
    assert r.status_code == 200
    name = r.get_json()["name"]
    listing = client.get("/api/reports").get_json()
    assert listing[0]["name"] == name
    blob = client.get(f"/api/report/{name}")
    assert blob.status_code == 200
    path = reports.path_of(str(tmp_path / "state"), name)
    with zipfile.ZipFile(path) as z:
        assert {"note.txt", "state.json", "events.json", "journal.txt"} <= set(z.namelist())
        assert z.read("note.txt").decode() == "it stopped"


def test_a_report_carries_the_profile_this_process_loaded(tmp_path, monkeypatch):
    """Lean plan D149: the loaded profile, not a hard-coded agv-01 path."""
    from agv_core import config  # noqa: PLC0415

    prof = tmp_path / "agv-77.json"
    prof.write_text("{}")
    monkeypatch.setattr(config, "PROFILE_PATH_LOADED", str(prof), raising=False)
    client, _ = app_for(merged(), tmp_path)
    name = client.post("/api/report", json={"note": ""}).get_json()["name"]
    with zipfile.ZipFile(reports.path_of(str(tmp_path / "state"), name)) as z:
        assert "agv-77.json" in z.namelist()


def test_a_report_name_from_a_url_cannot_escape_the_reports_directory(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    assert reports.path_of(str(tmp_path), "../../etc/passwd") is None
    assert client.get("/api/report/..%2F..%2Fetc%2Fpasswd").status_code in (404, 308)


# ---- the event log on disk -------------------------------------------------------


def test_the_event_log_survives_a_restart_and_rotates(tmp_path):
    path = str(tmp_path / "logs" / "events.jsonl")
    log = EventLog(path, max_bytes=400, keep=2)
    for i in range(40):
        log.append({"t": i, "code": "ESTOP", "text": f"event {i}", "level": "warn"})
    assert os.path.exists(path + ".1")  # it rotated rather than growing without bound
    tail = log.tail(100)
    assert tail[-1]["text"] == "event 39"
    assert len(EventLog(path, max_bytes=400, keep=2).tail(100)) == len(tail)  # reread = same history


def test_an_error_event_is_forced_to_the_platter(tmp_path, monkeypatch):
    """W4: after a cut the line you need is the last error, so that one is synced and
    the chatty info events are not."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    log = EventLog(str(tmp_path / "logs" / "events.jsonl"))
    log.append({"level": "info", "code": "MUX_SOURCE", "text": "t"})
    assert synced == []
    log.append({"level": "error", "code": "DRIVE_SILENT", "text": "t"}, sync=True)
    assert len(synced) == 1
    assert len(log.tail()) == 2  # both are in the file either way


def test_the_role_file_is_written_atomically(tmp_path):
    """A cut during the first run must not leave a half-written PIN file."""
    state = str(tmp_path / "state")
    role.ensure(state)
    assert sorted(p.name for p in (tmp_path / "state").iterdir()) == ["web.json"]  # no .tmp left
    assert role.check(state, role.DEFAULT_PIN)


def test_a_half_written_line_is_skipped_not_raised(tmp_path):
    path = tmp_path / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"code":"ESTOP","text":"good"}\n{"code":"EST')  # power cut mid-append
    assert [e["text"] for e in EventLog(str(path)).tail()] == ["good"]


@pytest.mark.parametrize("code", sorted(cat.CATALOGUE))
def test_every_catalogue_row_renders_for_the_operator(code):
    """Only the button labels here: they pin home.html's ACTIONS. Row well-formedness is
    tests/test_alarms.py (lean plan D136)."""
    row = cat.describe(code, "detail")
    assert cat.BUTTON[row["clears_by"]] in ("", "Acknowledge", "Recover", "Restart", "Set position")


def test_the_engineer_pin_is_typed_on_an_on_page_keypad(tmp_path):
    """The kiosk has no on-screen keyboard, so prompt() cannot be typed into on the panel."""
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    body = client.get("/home").get_data(as_text=True)
    assert 'id="pin-pad"' in body
    assert all(f'data-k="{d}"' in body for d in "0123456789")
    js = client.get("/static/amr.js").get_data(as_text=True)
    assert "prompt(" not in js


def test_the_manual_page_shows_the_line_reading_above_the_pad(tmp_path):
    """The MLS reading is read in every mode; the engineer jogs over tape and watches LCP1..3."""
    client, _ = app_for(merged(), tmp_path)
    body = client.get("/manual").get_data(as_text=True)
    assert 'id="line-track"' in body and 'id="lt-lcps"' in body
    assert body.index('id="line-track"') < body.index('id="jog"')


def test_rfid_tags_show_on_the_manual_and_run_pages(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    for page in ("/manual", "/run"):
        body = client.get(page).get_data(as_text=True)
        assert 'id="rf-status"' in body and 'id="rf-tags"' in body, page
        assert "rfidTags(st.rfid)" in body, page
    # the last tag, large for the HMI: Run only (operator, 2026-10-07)
    assert 'id="rf-last"' in client.get("/run").get_data(as_text=True)
    assert 'id="rf-last"' not in client.get("/manual").get_data(as_text=True)


def test_home_shows_mode_speed_and_line_tiles_and_loads_no_mission(tmp_path):
    """2026-10-08: setting a mission is not a Home thing. 2026-11-12: the live row is the selector's
    mode (big), speed and the line sensor; no RFID tile (RFID dropped) and no marker tile for the operator."""
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    body = client.get("/home").get_data(as_text=True)
    live = body[body.index('class="home-live"'):body.index('class="home-more"')]
    assert [m for m in re.findall(r'id="(live-[a-z]+)"', live)] == ["live-mode", "live-speed", "live-line"]
    assert "live-rfid" not in body and 'id="live-marker"' not in body
    assert "home-mission" not in body and "/api/mission/run" not in body
    assert "/static/linetrack.js" in body, "the line and marker readings are shared, not copied"
    client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN})
    assert 'id="live-marker"' in client.get("/home").get_data(as_text=True)


def test_home_shows_the_job_small_inside_the_status_tile_and_cannot_set_it(tmp_path):
    """2026-11-12: no job tile; the job is one small line in the full-width status tile. Set on Run."""
    client, _ = app_for(merged(), tmp_path)
    body = client.get("/home").get_data(as_text=True)
    tile = body.index('id="home-tile"')
    assert tile < body.index('id="home-line"') < body.index('id="home-job"') < body.index('id="home-primary"')
    assert body.index('id="home-primary"') < body.index('class="home-live"')
    assert "home-top" not in body
    assert "/api/line/mission" not in body and "<select" not in body


def test_the_adapter_reports_measured_wheel_speed_as_body_speed(monkeypatch):
    """/wheel_states_ui is the measured 606Ch feedback; v is the mean of the two rims."""
    import threading
    from types import SimpleNamespace

    from amr_web import adapter as ad

    monkeypatch.setattr(ad, "WHEEL_RADIUS_M", 0.1)
    a = ad.RosAdapter.__new__(ad.RosAdapter)
    a._lock = threading.Lock()
    a._now = lambda: 5.0

    def msg(left, right, valid=True):
        return SimpleNamespace(
            left_vel_rad_s=left, right_vel_rad_s=right, left_valid=valid, right_valid=valid
        )

    a._on_wheels(msg(5.0, 3.0))
    assert a._wheels["v_mps"] == pytest.approx(0.4)
    assert (a._wheels["left_mps"], a._wheels["right_mps"]) == (pytest.approx(0.5), pytest.approx(0.3))
    a._on_wheels(msg(-2.0, -2.0))
    assert a._wheels["v_mps"] == pytest.approx(-0.2), "reverse is negative"
    a._on_wheels(msg(9.0, 9.0, valid=False))
    assert a._wheels["valid"] is False and a._wheels["v_mps"] is None


def test_the_adapter_keeps_the_rfid_link_and_the_last_tag_passes():
    """Heartbeats set the link; each encounter is one pass, newest first, at most RFID_RECENT."""
    import threading
    from types import SimpleNamespace

    from amr_web import adapter as ad

    a = ad.RosAdapter.__new__(ad.RosAdapter)
    a._lock = threading.Lock()
    a._rfid, a._rfid_t = None, 0.0
    import collections

    a._rfid_tags = collections.deque(maxlen=ad.RFID_RECENT)
    clock = [100.0]
    a._now = lambda: clock[0]

    def msg(**kw):
        base = dict(heartbeat=False, rfid_tag="", encounter_seq=0, generation=0, comms_ok=True,
                    rx_age_s=0.1, tag_age_s=-1.0,
                    rssi_dbm=0.0, channel=-1, freq_mhz=0.0, reader="", config_mismatch=[])
        base.update(kw)
        return SimpleNamespace(**base)

    assert a._rfid_state(100.0) == {"link": None, "tags": []}
    a._on_rfid(msg(heartbeat=True, encounter_seq=0))
    for n in range(1, ad.RFID_RECENT + 3):
        clock[0] += 1.0
        a._on_rfid(msg(rfid_tag=f"{n:04X}", encounter_seq=n))
    a._on_rfid(msg(heartbeat=False, rfid_tag="", encounter_seq=99))  # no tag: not a pass
    st = a._rfid_state(clock[0] + 0.5)
    assert st["link"]["comms_ok"] and st["link"]["age_s"] == pytest.approx(ad.RFID_RECENT + 2 + 0.5)
    assert [t["tag"] for t in st["tags"]][:2] == [f"{ad.RFID_RECENT + 2:04X}", f"{ad.RFID_RECENT + 1:04X}"]
    assert len(st["tags"]) == ad.RFID_RECENT and st["tags"][0]["age_s"] == pytest.approx(0.5)
    assert st["link"]["rssi_dbm"] is None and st["tags"][0]["rssi_dbm"] is None  # no read yet: not 0 dBm

    # Read quality and the reader's configuration ride along for display.
    mism = ["region: reader 1, profile expects 0"]
    a._on_rfid(msg(heartbeat=True, rssi_dbm=-74.0, channel=0,
                   reader="active RS232 US 902.75-927.25 MHz 30 dBm", config_mismatch=mism))
    a._on_rfid(msg(rfid_tag="0020", encounter_seq=200, rssi_dbm=-72.5, channel=3))
    st = a._rfid_state(clock[0])
    assert (st["link"]["rssi_dbm"], st["link"]["channel"]) == (-74.0, 0)
    assert st["link"]["reader"].startswith("active") and st["link"]["config_mismatch"] == mism
    assert st["tags"][0]["tag"] == "0020" and st["tags"][0]["rssi_dbm"] == -72.5


def _product_app(product, tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    stub = Stub(merged())
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"), product=product)
    app.config["TESTING"] = True
    return app.test_client(), stub


def test_run_mapping_and_teach_tabs(tmp_path):
    """2026-10-28: Run is the tape product, Mapping holds the survey and the AMCL position (no
    sub-tabs, no routes), Guide is part of Teach. Mapping is in the operator's nav: Home's
    "Set position" lands on its Position tab; its Survey tab is the engineer's."""
    client, _ = _product_app("both", tmp_path)
    body = client.get("/home").get_data(as_text=True)
    nav = body.split('<nav>')[1].split('</nav>')[0]
    assert '>Run<' in nav and '>Mapping<' in nav and '>Teach<' in nav
    for gone in ("Run tracked", "Run trackless", "/guide", "/maps", "/editor"):
        assert gone not in nav, gone
    assert "/mapping?tab=pose" in body
    page = client.get("/mapping").get_data(as_text=True)
    assert 'class="subnav"' not in page and 'data-tab="survey"' in page and 'id="btn-survey-start"' in page
    client.post("/api/role", json={"role": "operator"})
    nav = client.get("/home").get_data(as_text=True).split('<nav>')[1].split('</nav>')[0]
    assert '>Mapping<' in nav and '>Teach<' not in nav
    page = client.get("/mapping?tab=survey").get_data(as_text=True)
    assert 'data-tab="survey"' not in page and 'id="btn-survey-start"' not in page
    assert 'class="tab on" type="button" data-tab="pose"' in page and 'id="tool-initialpose"' in page


def test_a_product_the_profile_does_not_carry_is_404_not_hidden(tmp_path):
    client, _ = _product_app("slam", tmp_path)
    nav = client.get("/home").get_data(as_text=True).split('<nav>')[1].split('</nav>')[0]
    assert '>Run<' not in nav and '>Teach<' not in nav and '>Mapping<' in nav
    for path in ("/run", "/run-tracked", "/teach", "/guide"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/line/clear").status_code == 404
    client, _ = _product_app("tape", tmp_path)
    for path in ("/mapping", "/maps", "/survey-continue", "/run-trackless"):
        assert client.get(path).status_code == 404, path
    assert client.get("/run").status_code == 200


def test_line_apis_reach_the_layer_and_never_move_anything(tmp_path):
    client, stub = _product_app("both", tmp_path)
    listing = client.get("/api/line/missions").get_json()
    assert "line-a" in listing["missions"] and "empty" not in listing["missions"]
    assert listing["destinations"]["line-a"] == ["MRU1", "MRU2", "MRU3", "MRU4"], "offered as a list"
    # 2026-10-23: the picker notes each job's branch and speed rule, the "none" entry included.
    assert {"basic-right", "basic-high-left", "basic-high-right"} <= set(listing["missions"])
    assert listing["notes"]["empty"] == "always branch left · normal speed"
    assert listing["notes"]["basic-high-right"] == "always branch right · HIGH zones (markers 2→1)"
    assert client.post("/api/line/mission", json={"name": "line-a", "destination": "MRU2"}).status_code == 200
    assert client.post("/api/line/clear").status_code == 200
    assert stub.calls == [("line_mission", ("line-a", "MRU2")), ("line_clear", ())]


def test_run_has_no_arm_button_and_no_arm_api(tmp_path):
    """2026-10-07: the physical Start runs from IDLE; motor arming is drive_node's."""
    client, _ = _product_app("tape", tmp_path)
    assert "btn-line-arm" not in client.get("/run").get_data(as_text=True)
    assert client.post("/api/line/arm").status_code in (404, 405)


def test_run_picks_by_tiles_and_keeps_the_follower_beside_the_rail(tmp_path):
    """2026-10-24: missions and destinations are touch tiles (no drop-down on the HMI), Set job
    and Clear sit on top, and the follower readout renders inside the rail, before the log."""
    client, _ = _product_app("tape", tmp_path)
    page = client.get("/run").get_data(as_text=True)
    assert "<select" not in page
    assert 'id="lt-mission" class="pick-grid"' in page and 'id="lt-dest" class="pick-grid small"' in page
    assert page.index('id="btn-line-select"') < page.index('id="lt-mission"')
    rail = page[page.index('id="telemetry"'):page.index('id="log"')]
    assert 'id="follower"' in rail and 'id="lt-state"' in rail and 'id="rf-last"' in rail
    assert 'id="follower"' not in client.get("/manual").get_data(as_text=True)


def test_home_has_no_navigation_switch_and_line_is_the_engineers(tmp_path):
    """2026-10-29: no Tracked/Idle switch on Home - the supervisor returns to LINE by itself
    after a survey and after Recover - and no Return to idle. The one mode button is the
    engineer's Restart tape layer (More), only on a vehicle with the tape product; /api/mode
    takes LINE only, from the engineer only. No Pause/Abort: the web runs no trackless mission."""
    for product in ("both", "tape", "slam"):
        (tmp_path / product).mkdir()
        client, _ = _product_app(product, tmp_path / product)
        client.post("/api/role", json={"role": "operator"})
        home = client.get("/home").get_data(as_text=True)
        assert 'id="nav-tracked"' not in home and 'id="nav-idle"' not in home, product
        assert 'id="btn-line"' not in home, product  # the operator's Home
        assert client.post("/api/mode", json={"target": "line"}).status_code == 403
        client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN})
        home = client.get("/home").get_data(as_text=True)
        for gone in ("btn-idle", "home-pause", "home-abort"):
            assert f'id="{gone}"' not in home, (product, gone)
        assert ('id="btn-line"' in home) == (product != "slam"), product
        if product != "slam":
            assert 'btn-to-line' not in client.get("/mapping").get_data(as_text=True)
    tracked = client.get("/run").get_data(as_text=True)
    assert "btn-line-mode" not in tracked and "btn-line-idle" not in tracked


def test_ipc_temperature_reads_coretemp_package_and_hottest_core(tmp_path):
    from amr_web.adapter import read_ipc_temp

    h = tmp_path / "hwmon" / "hwmon0"
    h.mkdir(parents=True)
    (tmp_path / "thermal").mkdir()
    (h / "name").write_text("coretemp\n")
    for i, (label, milli) in enumerate((("Package id 0", 66000), ("Core 0", 64000), ("Core 1", 71000)), 1):
        (h / f"temp{i}_label").write_text(label)
        (h / f"temp{i}_input").write_text(str(milli))
    assert read_ipc_temp(str(tmp_path)) == {"package_c": 66.0, "core_max_c": 71.0}
    assert read_ipc_temp(str(tmp_path / "missing")) is None


def test_supply_and_temperature_chips_sit_beside_net_on_every_page(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    for page in ("/home", "/alarms", "/manual"):
        body = client.get(page).get_data(as_text=True)
        net = body.index('id="net"')
        assert net < body.index('id="supply"') < body.index('id="ipc-temp"'), page


# ---- MLS markers on Home (mls-marker-plan 6.1, 2026-10-09) ----------------------------


def _home(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    app = create_app(Stub(merged()), str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    return app.test_client().get("/home").get_data(as_text=True)


def test_the_marker_reading_is_the_engineers_and_not_behind_a_profile_switch(tmp_path):
    """2026-10-23: markers are always on. 2026-11-12: the tile moved into the engineer's More (the
    default session is the engineer's), the operator's live row is mode, speed and line."""
    body = _home(tmp_path)
    more = body.index('class="home-more"')
    assert more < body.index('id="live-marker"'), "the marker tile lives in More"
    assert "markerReading(" in body, "the marker rule is shared in linetrack.js, not copied"


def test_the_adapter_keeps_the_marker_status_and_the_last_markers():
    import collections
    import threading
    from types import SimpleNamespace

    from amr_web import adapter as ad

    a = ad.RosAdapter.__new__(ad.RosAdapter)
    a._lock = threading.Lock()
    a._marker, a._marker_t, a._marker_gen = None, 0.0, None
    a._marker_reads = collections.deque(maxlen=ad.RFID_RECENT)
    clock = [100.0]
    a._now = lambda: clock[0]

    def msg(**kw):
        base = dict(heartbeat=False, seq=0, generation=0, code=0, raw=0, direction=0, lcp2_mm=0,
                    nlcp=2, line_good=True, markers_ok=True, status="ok", rejects=0, aborts=0)
        base.update(kw)
        return SimpleNamespace(**base)

    assert a._marker_state(100.0) == {"link": None, "events": []}
    a._on_marker(msg(heartbeat=True))
    clock[0] += 1.0
    a._on_marker(msg(seq=1, code=2, raw=4, lcp2_mm=-3))
    clock[0] += 1.0
    a._on_marker(msg(seq=2, code=1, raw=2, lcp2_mm=5, aborts=1))
    st = a._marker_state(clock[0] + 0.5)
    assert [e["code"] for e in st["events"]] == [1, 2] and st["events"][0]["age_s"] == pytest.approx(0.5)
    assert st["link"]["count"] == 2 and st["link"]["aborts"] == 1 and st["link"]["markers_ok"]
    a._on_marker(msg(heartbeat=True, generation=1, seq=0, status="misconfigured: 2028h:03 = 0 (want 1)",
                     markers_ok=False))
    st = a._marker_state(clock[0])
    assert st["events"] == [] and st["link"]["status"].startswith("misconfigured")


def test_the_adapter_never_assigns_one_attribute_twice_in_init():
    """2026-10-09: the marker deque was named `_markers`, and the route-marker publisher
    created later in __init__ took the name - /api/state answered 500 on the vehicle while
    every unit test (which skips __init__) passed."""
    import ast
    import pathlib

    from amr_web import adapter as ad

    tree = ast.parse(pathlib.Path(ad.__file__).read_text())
    init = next(f for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "RosAdapter"
                for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "__init__")
    names = []
    for node in ast.walk(init):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
            node, ast.AnnAssign) else []
        for t in targets:
            for e in (t.elts if isinstance(t, ast.Tuple) else [t]):
                if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self":
                    names.append(e.attr)
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, f"assigned twice in RosAdapter.__init__: {dup}"


def test_pages_carry_the_freshness_limit_the_server_judges_by(tmp_path):
    """Lean plan D62: amr.js reads FRESH_S from base.html instead of restating 0.5."""
    from amr_web import alarms as alarmview  # noqa: PLC0415

    client, _ = app_for(merged(), tmp_path)
    html = client.get("/home").get_data(as_text=True)
    assert f'data-fresh-s="{alarmview.FRESH_S}"' in html


def test_home_places_the_lcp_dots_through_the_shared_helper(tmp_path):
    """Lean plan D130: one dot placement and freshness rule (linetrack.js) for Home and the strip."""
    client, _ = app_for(merged(), tmp_path)
    html = client.get("/home").get_data(as_text=True)
    assert "placeLcpDots(" in html and "lineFresh(" in html


def test_recover_is_the_engineers(tmp_path):
    """WP-B4 (owner, 2026-10-25): Recover, which also acknowledges a drive-link fault after
    the power cycle, needs the engineer view (PIN)."""
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    r = client.post("/api/recover")
    assert r.status_code == 403 and "engineer view" in r.get_json()["message"]
    client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN})
    assert client.post("/api/recover").status_code != 403


def test_a_drive_link_fault_is_a_drive_row_and_hides_drives_not_ready():
    """WP-B4: link FAULT with cached 'Operation enabled' used to show only DRIVES_NOT_READY."""
    from amr_web import alarms as web_alarms

    fault = {"operational": False, "left": "Operation enabled", "right": "Operation enabled", "link": "fault"}
    assert web_alarms._drive_code(fault) == "DRIVE_FAULT"
    assert web_alarms._drive_code(dict(fault, left="stale")) == "DRIVE_SILENT"
    assert web_alarms._drive_code(dict(fault, link="standby", left="Ready to switch on",
                                       right="Ready to switch on")) is None


def test_every_button_has_a_style_class():
    """2026-10-29: a <button> without a class renders as the browser's native grey button
    (Teach had a dozen). Every button names one: big, tool, danger, tab, pick, dir, ui-size;
    the PIN pad's keys (data-k) are styled by `dialog.pin-pad button`."""
    pkg = Path(__file__).resolve().parents[1] / "amr_web"
    bare = []
    for f in sorted([*pkg.glob("templates/*.html"), *pkg.glob("static/*.js")]):
        for tag in re.findall(r"<button\b[^>]*>", f.read_text()):
            if "class=" not in tag and "data-k=" not in tag:
                bare.append(f"{f.name}: {tag}")
    assert not bare, bare


def test_at_home_with_no_station_link_stands_without_stopping_anything():
    st = merged()
    assert "STATION_LINK_HOME" not in {r["code"] for r in view.standing(st)}
    st["station_link_home"] = "at home with no link to 192.168.2.5:1883"
    rows = view.standing(st)
    row = next(r for r in rows if r["code"] == "STATION_LINK_HOME")
    assert row["level"] == "warn" and row["clears_by"] == "auto"
    assert view.headline(st, rows)["state"] != view.STOPPED_NEEDS_YOU


# ---- the position row on Home (manuals/home-auto-confirm-plan.md) --------------------


def _pos(line=None, loc="READY", auto=False, reason="", calling=True, mode="LINE"):
    ln = {"state_name": "IDLE", "at_home": True, "home_detail": "", "trip": "", **(line or {})}
    st = {"mode": {"mode_name": mode}, "line": ln, "panel": {"valid": True, "mode_auto": auto},
          "localization": {"state_name": loc, "reason": reason}}
    if calling:
        st["order"] = {}
    return view.home_position(st)


@pytest.mark.parametrize(
    "kw, status, enabled",
    [
        ({"loc": "UNLOCALIZED"}, "Position not set", True),
        ({"loc": "UNLOCALIZED", "auto": True}, "Position not set", False),
        ({"line": {"home_detail": "Checking position: waiting for AMCL"}},
         "Checking position: waiting for AMCL", False),
        ({}, "Position OK", True),
        ({"line": {"home_detail": "Position check failed: tape not seen"}, "loc": "CHECKING"},
         "Position check failed: tape not seen", True),
        ({"line": {"home_detail": "Position lost, rechecking at home"}, "loc": "LOST", "auto": True},
         "Position lost, rechecking at home", False),
        ({"loc": "LOST", "reason": "scan passes"}, "Position lost: scan passes", True),
        ({"line": {"at_home": False}}, "Away from home", False),
        ({"line": {"state_name": "RUNNING"}, "loc": "LOST"}, "On a trip", False),
        ({"line": {"state_name": "HOLD"}}, "On a trip", False),
        ({"line": {"trip": "MRU: MRU1"}}, "On a trip", False),
        ({"line": {"state_name": "FAULT"}}, "Job in fault", False),
        ({"loc": "CHECKING"}, "Checking position set by hand", True),
    ],
)
def test_the_position_row(kw, status, enabled):
    p = _pos(**kw)
    assert p["show"] and p["status"] == status and p["enabled"] is enabled


def test_at_home_needs_manual_only_with_calling_on():
    assert _pos(auto=True)["why"] == "turn the selector to MANUAL"
    assert _pos(auto=True, calling=False)["enabled"] is True


def test_the_position_row_shows_only_in_line_mode():
    assert _pos(mode="MAPPING")["show"] is False


def test_the_position_and_at_home_sit_small_in_the_status_tile_and_home_has_no_scan_view(tmp_path):
    """2026-11-12 (owner): Position OK / At home at the right of the status tile, small, for every role.
    The panel's Reset + Start does the same; the server keeps its refusals."""
    client, _ = app_for(merged(), tmp_path)
    client.post("/api/role", json={"role": "operator"})
    body = client.get("/home").get_data(as_text=True)
    tile, pos, live = (body.index(k) for k in ('id="home-tile"', 'id="home-pos"', 'class="home-live"'))
    assert tile < body.index('id="home-primary"') < pos < body.index('id="btn-at-home"') < live
    assert 'id="btn-at-home" class="tool run"' in body, "small, not a big button"
    assert "/api/line/at_home" in body and "<canvas" not in body
    d = client.get("/api/alarms").get_json()
    assert "position" in d and "tile" in d


# ---- the status tile on Home (manuals/emergency-suite-plan.md Part A) -----------------

STANDBY = {"operational": False, "left": "Ready to switch on", "right": "Ready to switch on",
           "link": "standby", "age_s": 0.05}
STO = {"operational": False, "left": "Switch on disabled", "right": "Switch on disabled", "link": "standby",
       "age_s": 0.05}
IDLE_MUX = {"inhibited": True, "source": "none", "reason": "drives not operational or stale",
            "code": "DRIVES_NOT_READY", "age_s": 0.05}
LINE_MODE = {"mode_name": "LINE", "fault_code": "", "reason": "", "base_ready": True, "generation": 1}


def _line(loc="READY", auto=False, **line):
    ln = {"state_name": "IDLE", "at_home": True, "home_detail": "", "trip": "", "code": "", **line}
    return merged(mode=LINE_MODE, line=ln, panel={"valid": True, "mode_auto": auto, "age_s": 0.05},
                  localization={"state_name": loc, "reason": ""})


def _tile(st):
    return view.home_tile(st, view.standing(st))


@pytest.mark.parametrize(
    "st, kind, level, big",
    [
        (merged(), "ready", "ok", view.READY),
        # powered on demand: DRIVES_NOT_READY stands at every idle and must not turn the tile yellow
        (merged(drives=STANDBY, mux=IDLE_MUX), "ready", "ok", view.READY),
        (_line(), "ready", "ok", view.READY),
        (_line(at_home=False), "ready", "ok", view.READY),
        (_line(state_name="RUNNING", loc="LOST"), "running", "ok", view.RUNNING),
        (merged(run={"state_name": "EXECUTING", "mission_id": "m", "step_index": 0}),
         "running", "ok", view.RUNNING),
        (merged(run={"state_name": "BLOCKED", "hold_cause": "field", "fault_code": "FIELD_BLOCKED",
                     "auto_resume": True, "reason": ""}), "stopped", "warn", view.STOPPED_WILL_RESUME),
        (_line(state_name="HOLD", auto_resume=False, code="ESTOP", message="safety stop"),
         "stopped", "warn", view.STOPPED_NEEDS_YOU),
        (_line(loc="UNLOCALIZED"), "lost", "warn", view.NOT_LOCALIZED),
        (_line(loc="LOST"), "lost", "warn", view.NOT_LOCALIZED),
        (_line(loc="CHECKING", home_detail="Position check failed: tape not seen"), "lost", "warn",
         view.NOT_LOCALIZED),
        (_line(loc="LOST", home_detail="Position lost, rechecking at home"),
         "lost", "warn", view.NOT_LOCALIZED),
        (_line(loc="UNLOCALIZED", home_detail="Checking position: waiting for AMCL"), "checking", "warn",
         view.CHECKING_POSITION),
        (_line(loc="CHECKING"), "checking", "warn", view.CHECKING_POSITION),
        (merged(mode={**LINE_MODE, "mode_name": "NAVIGATION"},
                localization={"state_name": "LOST", "code": "LOC_LOST", "reason": "x"}), "lost", "warn",
         view.NOT_LOCALIZED),
        (merged(panel={"valid": False, "mode_auto": False, "age_s": 0.05}),
         "fault", "error", view.STOPPED_NEEDS_YOU),
        (merged(run={"state_name": "FAULT", "fault_code": "EXEC_OFF_PATH", "reason": "x"}), "fault", "error",
         view.STOPPED_NEEDS_YOU),
        (merged(mode={"mode_name": "FAULT", "fault_code": "BASE_EXITED", "reason": "x", "base_ready": False,
                      "generation": 1}), "fault", "error", view.NEEDS_SERVICE),
        (merged(mode={**LINE_MODE, "mode_name": "STARTING", "base_ready": False}),
         "starting", "off", view.NOT_READY),
        (merged(scan_age_s=None, up_s=120.0), "attention", "warn", view.ATTENTION),
    ],
)
def test_the_status_tile(st, kind, level, big):
    t = _tile(st)
    assert (t["kind"], t["level"], t["big"]) == (kind, level, big)
    assert t["blink"] is (kind == "lost")
    assert bool(t["press"]) is (kind == "lost" and bool(t["steps"]))


def test_an_estop_without_the_q3_wire_is_never_green_and_never_red():
    """Part B (the E-stop signal) is postponed: the PC sees only what the E-stop causes. At rest that is
    SAFETY_RESET_NEEDED, in a run an estop hold - both yellow, with the catalogue's words."""
    at_rest = _tile(merged(drives=STO, mux=IDLE_MUX))
    assert (at_rest["kind"], at_rest["level"]) == ("attention", "warn")
    assert at_rest["code"] == "SAFETY_RESET_NEEDED"
    assert "Reset" in at_rest["action"]
    hold = {"state_name": "BLOCKED", "hold_cause": "estop", "fault_code": "ESTOP", "auto_resume": False,
            "reason": ""}
    in_run = _tile(merged(drives=STO, mux=IDLE_MUX, run=hold))
    assert (in_run["kind"], in_run["level"]) == ("stopped", "warn")
    assert "E-stop" in in_run["action"] and "Start" in in_run["action"]


def test_not_localized_walks_through_the_panel_press_ticking_the_selector():
    auto = _tile(_line(loc="UNLOCALIZED", auto=True))
    assert [s["text"] for s in auto["steps"]] == list(view.LOCALIZE_STEPS)
    assert [(s["done"], s["now"]) for s in auto["steps"]] == [(False, True), (False, False), (False, False)]
    manual = _tile(_line(loc="UNLOCALIZED", auto=False))
    assert [(s["done"], s["now"]) for s in manual["steps"]] == [(True, False), (False, True), (False, False)]
    assert manual["button"] == "" and manual["title"] == "Position not set"
    assert "RESET" in view.LOCALIZE_STEPS[2] and "START" in view.LOCALIZE_STEPS[2]
    # the page rings these two on its panel drawing, whatever the selector says
    assert auto["press"] == manual["press"] == ["reset", "start"]
    assert manual["press_text"] == "Press together, 1 s"
    assert set(manual["press"]) <= set(view.PANEL_BUTTONS)


def test_a_stop_waiting_for_attach_or_release_rings_start():
    """The stop call (manuals/stop-call-alarm-plan.md C4): the panel pulses the alarm until Start, and
    the Home drawing rings START. A fault-type hold that also waits for Start does not."""
    for cause in ("station", "payload", "trolley"):
        t = _tile(_line(state_name="HOLD", hold_cause=cause, auto_resume=False, code="",
                        message="at MW-1: press Start to go on", auto=True))
        assert (t["kind"], t["press"], t["press_text"]) == ("stopped", ["start"], "Press to go on"), cause
    estop = _tile(_line(state_name="HOLD", hold_cause="estop", auto_resume=False, code="ESTOP",
                        message="safety stop", auto=True))
    assert estop["press"] == [] and estop["press_text"] == ""


def test_navigation_not_localized_offers_set_position():
    t = _tile(merged(mode={**LINE_MODE, "mode_name": "NAVIGATION"},
                     localization={"state_name": "LOST", "code": "LOC_LOST", "reason": "x"}))
    assert t["button"] == "Set position" and t["steps"] == [] and t["press"] == []


def test_the_live_vehicle_idle_is_green():
    """The vehicle as seen on 2026-11-12: LINE, AUTO, drives in standby (power on demand), localized at
    HOME, the mux holding DRIVES_NOT_READY. That is a normal idle, not an attention."""
    st = _line(auto=True)
    st.update(drives=STANDBY, mux=IDLE_MUX)
    assert _tile(st)["kind"] == "ready"
