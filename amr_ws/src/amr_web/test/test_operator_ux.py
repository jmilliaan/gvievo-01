"""The operator surface: one catalogue, one standing list, one button (plan phases 0-3).

These tests exist because every page used to derive "what is wrong" in its own
JavaScript, in its own words, with no action attached. The contract now is:
`/api/alarms` decides, the pages render. So the assertions here are about wording
and about which button the operator is offered - not about internals.
"""

import json
import os
import zipfile

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
    st = merged(drives={"operational": False, "left": "Switch on disabled",
                        "right": "Switch on disabled", "age_s": 0.05})
    rows = view.standing(st)
    assert rows[0]["code"] == "SAFETY_RESET_NEEDED"
    assert "reset" in rows[0]["action"].lower()


def test_a_disarmed_drive_at_idle_is_not_an_alarm():
    st = merged(drives={"operational": False, "left": "Ready to switch on",
                        "right": "Ready to switch on", "age_s": 0.05})
    assert view.standing(st) == []


def test_a_field_stop_says_it_resumes_by_itself_and_offers_no_button():
    st = merged(run={"state_name": "BLOCKED", "hold_cause": "field", "fault_code": "FIELD_BLOCKED",
                     "auto_resume": True, "reason": "safety stop", "mission_id": "m1", "step_index": 2})
    rows = view.standing(st)
    h = view.headline(st, rows)
    assert rows[0]["code"] == "FIELD_BLOCKED"
    assert h["state"] == view.STOPPED_WILL_RESUME and h["button"] == ""


def test_an_estop_hold_tells_the_operator_to_press_start():
    st = merged(run={"state_name": "BLOCKED", "hold_cause": "estop", "fault_code": "ESTOP",
                     "auto_resume": False, "reason": "safety stop", "mission_id": "m1", "step_index": 0})
    h = view.headline(st, view.standing(st))
    assert h["state"] == view.STOPPED_NEEDS_YOU and "Start" in h["action"]


def test_an_executor_fault_offers_acknowledge():
    st = merged(run={"state_name": "FAULT", "fault_code": "EXEC_OFF_PATH", "reason": "cross-track"})
    h = view.headline(st, view.standing(st))
    assert h["button"] == "Acknowledge" and h["code"] == "EXEC_OFF_PATH"


def test_a_dead_base_offers_restart_and_says_needs_service():
    st = merged(mode={"mode_name": "FAULT", "fault_code": "BASE_EXITED", "reason": "base died",
                      "base_ready": False, "generation": 1})
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


def test_the_worst_alarm_is_first_and_a_code_is_never_repeated():
    st = merged(
        panel={"valid": False, "mode_auto": False, "age_s": 0.05},
        mux={"inhibited": True, "source": "none", "reason": "no panel authority",
             "code": "PANEL_STALE", "age_s": 0.05},
    )
    rows = view.standing(st)
    assert [r["code"] for r in rows] == ["PANEL_STALE"]
    assert rows[0]["level"] == "error"


def test_every_standing_row_carries_an_action_the_operator_can_perform():
    st = merged(
        mode={"mode_name": "FAULT", "fault_code": "MUX_ACK_TIMEOUT", "reason": "no ack",
              "base_ready": True, "generation": 1},
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


def test_events_carry_the_catalogue_title(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    rows = client.get("/api/events").get_json()
    assert rows[0]["title"] == cat.CATALOGUE["ESTOP"].title


def test_the_home_page_is_the_operators_landing_page(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    assert client.get("/").headers["Location"].endswith("/home")
    body = client.get("/home").get_data(as_text=True)
    assert 'id="home-primary"' in body
    # the operator's nav: no Params, no Monitor, no Commission
    assert "/params" not in body and "/monitor" not in body
    assert "/run" in body and "/alarms" in body


def test_the_engineer_pin_opens_the_engineering_nav(tmp_path):
    client, _ = app_for(merged(), tmp_path)
    assert client.post("/api/role", json={"role": "engineer", "pin": "0000"}).status_code == 403
    assert client.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN}).status_code == 200
    body = client.get("/status").get_data(as_text=True)
    assert "/params" in body and "/commissioning" in body
    # and the way back is always open: a guard you cannot leave is a trap
    assert client.post("/api/role", json={"role": "operator"}).status_code == 200
    assert "/params" not in client.get("/home").get_data(as_text=True)


def test_the_pin_lives_outside_the_repository_and_can_be_overridden(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    assert role.pin(state_dir) == role.DEFAULT_PIN
    written = tmp_path / "state" / "web.json"
    assert written.exists() and oct(os.stat(written).st_mode)[-3:] == "600"
    monkeypatch.setenv("AMR_WEB_ENGINEER_PIN", "4242")
    assert role.pin(state_dir) == "4242" and role.check(state_dir, "4242")


def test_restart_is_refused_while_the_wheels_turn(tmp_path):
    st = merged(mux={"inhibited": False, "source": "manual", "reason": "", "code": "",
                     "left_rad_s": 1.2, "right_rad_s": 1.2, "age_s": 0.05})
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


def test_a_half_written_line_is_skipped_not_raised(tmp_path):
    path = tmp_path / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"code":"ESTOP","text":"good"}\n{"code":"EST')  # power cut mid-append
    assert [e["text"] for e in EventLog(str(path)).tail()] == ["good"]


@pytest.mark.parametrize("code", sorted(cat.CATALOGUE))
def test_every_catalogue_row_renders_for_the_operator(code):
    row = cat.describe(code, "detail")
    assert row["title"] and row["action"] and row["level"] in ("info", "warn", "error")
    assert cat.BUTTON[row["clears_by"]] in ("", "Acknowledge", "Recover", "Restart", "Set position")
