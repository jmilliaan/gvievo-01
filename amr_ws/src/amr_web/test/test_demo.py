"""The DEMO page (manuals/plans/2026-09-23-demo-page.md).

The contract is about what a visitor can and cannot see or do: five sentences and
four numbers, no fault vocabulary, no way to command the vehicle, and open to both
roles without a PIN.
"""

import json
import os
import re

from agv_core import alarms as cat
from amr_web.server import create_app

from amr_web import demo, role

WEB = os.path.join(os.path.dirname(__file__), "..", "amr_web")

OK_DRIVES = {"operational": True, "left": "Operation enabled", "right": "Operation enabled", "age_s": 0.05}


def st(run=None, line=None, mode="NAVIGATION", drives=OK_DRIVES, mux=None, **extra):
    s = {
        "mode": {"mode_name": mode, "fault_code": "", "reason": "", "generation": 1} if mode else None,
        "drives": drives,
        "mux": mux or {"left_rad_s": 0.0, "right_rad_s": 0.0, "age_s": 0.05, "code": "NO_SOURCE"},
        "run": run,
        "run_stale": False,
        "line": line,
    }
    s.update(extra)
    return s


def run(name, cause="", **kw):
    d = {
        "state_name": name,
        "hold_cause": cause,
        "reason": "cross-track +0.14 m exceeds 0.10 m",
        "fault_code": "PATH_BLOCKED",
        "age_s": 0.1,
    }
    d.update(kw)
    return d


def line(name, cause="", **kw):
    d = {
        "state_name": name,
        "hold_cause": cause,
        "message": "0x8130 heartbeat",
        "code": "DRIVE_ALARM",
        "age_s": 0.1,
    }
    d.update(kw)
    return d


class Stub:
    def __init__(self, state):
        self.state_ = state

    def state(self):
        return self.state_

    def events(self, since=0):
        return []

    def diagnostics(self):
        return {}

    def event_log_files(self):
        return []

    def emit(self, *a, **k):
        pass

    def __getattr__(self, name):
        def fn(*a):
            raise AssertionError(f"the demo page must not call {name}")

        return fn


def client_for(state, tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    app = create_app(Stub(state), str(maps), state_dir=str(tmp_path / "state"), wheel_radius_m=0.09)
    app.config["TESTING"] = True
    return app.test_client()


# ---- the vocabulary -------------------------------------------------------------


def test_every_row_of_the_status_table():
    cases = [
        (st(run=run("EXECUTING")), demo.DRIVING),
        (st(line=line("RUNNING"), mode="LINE"), demo.DRIVING),
        (st(run=run("BLOCKED", "field")), demo.WAITING),
        (st(line=line("HOLD", "field"), mode="LINE"), demo.WAITING),
        (st(run=run("READY")), demo.READY),
        (st(line=line("ARMED"), mode="LINE"), demo.READY),
        (st(run=run("PAUSED")), demo.PAUSED),
        (st(run=run("DONE")), demo.PAUSED),
        (st(run=run("BLOCKED", "controller")), demo.PAUSED),
        (st(line=line("HOLD", "track"), mode="LINE"), demo.PAUSED),
        (st(run=run("FAULT")), demo.STANDBY),
        (st(line=line("FAULT"), mode="LINE"), demo.STANDBY),
        (st(run=run("EXECUTING"), drives={"operational": False, "age_s": 0.1}), demo.STANDBY),
        (st(run=run("EXECUTING"), drives=None), demo.STANDBY),
        (st(mode=None), demo.STANDBY),
        (st(mode="IDLE"), demo.STANDBY),
        (st(run=run("EXECUTING"), run_stale=True), demo.STANDBY),
        (st(line=line("RUNNING", age_s=9.0), mode="LINE"), demo.STANDBY),
    ]
    for state, want in cases:
        assert demo.status(state) == want, (state, want)


def test_a_person_in_the_field_is_explained_even_with_torque_off():
    """The field trips STO; the visitor should still hear why it stopped."""
    s = st(run=run("BLOCKED", "field"), drives={"operational": False, "age_s": 0.1})
    assert demo.status(s) == demo.WAITING


def test_no_fault_vocabulary_ever_reaches_the_page():
    codes = set(cat.CATALOGUE)
    faults = [
        st(run=run("FAULT")),
        st(line=line("FAULT"), mode="LINE"),
        st(run=run("BLOCKED", "estop")),
        st(mode="FAULT"),
        st(drives={"operational": False, "left": "Fault", "right": "Fault", "age_s": 0.1}),
    ]
    for s in faults:
        body = json.dumps(demo.view(s, 0.09, demo.Counters(), 1.0))
        assert not re.search(r"0x[0-9A-Fa-f]+|\b[0-9A-F]{4}h\b", body), body
        for word in ("PATH_BLOCKED", "DRIVE_ALARM", "cross-track", "heartbeat", "estop", "FAULT", *codes):
            assert word not in body, (word, body)
    assert set(demo.SENTENCES) == {demo.DRIVING, demo.WAITING, demo.READY, demo.PAUSED, demo.STANDBY}


def test_the_mode_tile_names_the_product_in_plain_words():
    assert demo.view(st(mode="LINE"), 0.09, demo.Counters(), 0)["mode"] == "Tape guided"
    assert demo.view(st(mode="NAVIGATION"), 0.09, demo.Counters(), 0)["mode"] == "Tape-free"
    assert demo.view(st(mode="MAPPING"), 0.09, demo.Counters(), 0)["mode"] == "Standing by"


# ---- the numbers ----------------------------------------------------------------


def moving(v_rad_s=10.0, state="EXECUTING", **kw):
    return st(run=run(state), mux={"left_rad_s": v_rad_s, "right_rad_s": v_rad_s, "age_s": 0.05}, **kw)


def test_speed_and_distance_from_the_commanded_wheels():
    c = demo.Counters()
    d = demo.view(moving(), 0.09, c, 0.0)
    assert d["speed_mps"] == 0.9
    for t in (1.0, 2.0, 3.0):
        d = demo.view(moving(), 0.09, c, t)
    assert abs(d["distance_m"] - 2.7) < 1e-6


def test_a_pivot_reads_as_zero_speed():
    s = st(run=run("EXECUTING"), mux={"left_rad_s": -5.0, "right_rad_s": 5.0, "age_s": 0.05})
    assert demo.view(s, 0.09, demo.Counters(), 0)["speed_mps"] == 0.0


def test_a_gap_between_polls_adds_no_distance():
    c = demo.Counters()
    demo.view(moving(), 0.09, c, 0.0)
    demo.view(moving(), 0.09, c, 5.0)  # nobody polled for 5 s
    assert c.distance_m == 0.0


def test_speed_is_zero_unless_driving_and_when_the_mux_is_stale():
    assert demo.view(moving(state="PAUSED"), 0.09, demo.Counters(), 0)["speed_mps"] == 0.0
    stale = st(run=run("EXECUTING"), mux={"left_rad_s": 10.0, "right_rad_s": 10.0, "age_s": 5.0})
    assert demo.view(stale, 0.09, demo.Counters(), 0)["speed_mps"] == 0.0


def test_safety_stops_count_rising_edges_only():
    c = demo.Counters()
    hold = st(run=run("BLOCKED", "field"))
    t = 0.0
    for _ in range(30):  # one hold lasting 30 s is one stop
        demo.view(hold, 0.09, c, t)
        t += 1.0
    demo.view(moving(), 0.09, c, t)
    demo.view(hold, 0.09, c, t + 1)
    assert c.safety_stops == 2


def test_reset_clears_the_counters():
    c = demo.Counters(distance_m=12.0, safety_stops=3, last_t=1.0, in_field_hold=True)
    c.reset()
    assert (c.distance_m, c.safety_stops, c.last_t, c.in_field_hold) == (0.0, 0, None, False)


# ---- the page -------------------------------------------------------------------


def test_both_roles_reach_the_page_and_see_the_link(tmp_path):
    cl = client_for(moving(), tmp_path)
    assert 'href="/demo"' in cl.get("/home").get_data(as_text=True)
    assert cl.get("/demo").status_code == 200
    assert cl.get("/api/demo").get_json()["status"] == demo.DRIVING
    assert cl.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN}).status_code == 200
    assert 'href="/demo"' in cl.get("/status").get_data(as_text=True)
    assert cl.get("/demo").status_code == 200


def test_the_page_says_what_the_product_is(tmp_path):
    body = client_for(st(), tmp_path).get("/demo").get_data(as_text=True)
    want = ("AGV I-PRIME", "Autonomous Guided Vehicle", "Smart material handling solution system")
    want += ("2 T", "1 m/s")
    for s in want:
        assert s in body, s
    # a visitor cannot navigate into the operator pages from here
    for href in ('href="/manual"', 'href="/run"', 'href="/params"', 'href="/home"'):
        assert href not in body, href


def test_reset_query_zeroes_the_counters(tmp_path):
    cl = client_for(moving(), tmp_path)
    cl.get("/api/demo")
    cl.get("/api/demo")
    cl.get("/demo?reset=1")
    assert cl.get("/api/demo").get_json()["distance_m"] == 0.0


def test_the_page_can_only_read():
    """Source scan: no write verb, no endpoint but /api/demo."""
    src = ""
    for p in ("templates/demo.html", "static/demo.js"):
        with open(os.path.join(WEB, p), encoding="utf-8") as fh:
            src += fh.read()
    assert not re.search(r"POST|PUT|DELETE|method\s*:", src)
    assert set(re.findall(r"/api/[a-z_/]+", src)) == {"/api/demo"}


def test_content_file_is_complete():
    with open(os.path.join(WEB, "static", "demo", "content.json"), encoding="utf-8") as fh:
        c = json.load(fh)
    assert c["product"] and c["expansion"] and c["tagline"]
    assert c["cards"]
    for card in c["cards"]:
        assert card["kicker"] and card["title"] and (card.get("body") or card.get("specs"))
