"""The DEMO page (manuals/plans/2026-09-23-demo-page.md), the landing page since 2026-10-15.

The display unit is stationary. The contract is about what a visitor can and cannot
see or do: the safety scanner's view around the vehicle outline, three sentences and
one number, no fault vocabulary, no way to command the vehicle, and open to both
roles without a PIN.
"""

import json
import math
import os
import re

import yaml
from agv_core import alarms as cat
from amr_web.server import create_app

from amr_web import demo, role

WEB = os.path.join(os.path.dirname(__file__), "..", "amr_web")
SRC = os.path.join(os.path.dirname(__file__), "..", "..")
ICONS = {"scanner", "layers", "bolt", "shield", "stop", "route", "load", "panel", "speed", "map", "qr"}

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


class Live:
    def __init__(self, ps):
        self.ps = ps

    def pose_scan(self):
        return self.ps


class Stub:
    def __init__(self, state, ps=None):
        self.state_ = state
        self.live = Live(ps)

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


def client_for(state, tmp_path, ps=None):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    app = create_app(Stub(state, ps), str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    return app.test_client()


# ---- the scanner view -----------------------------------------------------------

# a 1.0 x 0.6 m box around the pivot
BOX = ((0.5, 0.3), (0.5, -0.3), (-0.5, -0.3), (-0.5, 0.3))


def ps(points, x=0.0, y=0.0, yaw=0.0, pose_age=0.1, scan_age=0.1, pose_frame="odom", scan_frame="odom"):
    return {
        "generation": 1,
        "pose": {"x": x, "y": y, "yaw": yaw, "frame": pose_frame, "age_s": pose_age},
        "scan": {"points": points, "frame": scan_frame, "age_s": scan_age},
    }


def test_points_come_back_in_the_vehicle_frame():
    # vehicle at (10, 5) facing +y (world); a point 2 m ahead of it in the world is at (10, 7)
    d = demo.view(ps([(10.0, 7.0)], x=10.0, y=5.0, yaw=math.pi / 2), BOX)
    assert d["points"] == [(2.0, 0.0)]
    assert d["nearest_m"] == 1.5  # from the front edge at x=0.5
    assert d["status"] == demo.WATCHING


def test_someone_close_reads_as_near():
    d = demo.view(ps([(1.2, 0.0), (3.0, 0.0)]), BOX)
    assert d["status"] == demo.NEAR and d["nearest_m"] == 0.7
    assert d["near_points"] == [(1.2, 0.0)] and d["points"] == [(3.0, 0.0)]
    assert demo.view(ps([(1.2, 0.0)]), BOX, near_m=0.5)["status"] == demo.WATCHING


def test_the_vehicles_own_body_is_not_someone():
    d = demo.view(ps([(0.1, 0.1), (3.0, 0.0)]), BOX)
    assert d["status"] == demo.WATCHING and d["points"] == [(3.0, 0.0)]


def test_far_points_are_not_sent():
    d = demo.view(ps([(demo.VIEW_M + 1.0, 0.0), (2.0, 0.0)]), BOX)
    assert d["points"] == [(2.0, 0.0)]


def test_an_empty_scan_is_still_watching():
    d = demo.view(ps([]), BOX)
    assert d["status"] == demo.WATCHING and d["nearest_m"] is None


def test_missing_stale_or_mismatched_data_is_standby():
    cases = [
        None,
        {"generation": 1, "pose": None, "scan": None},
        ps([(2.0, 0.0)], scan_age=5.0),
        ps([(2.0, 0.0)], pose_age=5.0),
        ps([(2.0, 0.0)], pose_frame="map", scan_frame="odom"),
        {
            "generation": 1,
            "pose": {"x": "bad", "y": 0, "yaw": 0, "frame": "odom", "age_s": 0.1},
            "scan": {"points": [(2.0, 0.0)], "frame": "odom", "age_s": 0.1},
        },
    ]
    for c in cases:
        d = demo.view(c, BOX)
        assert d["status"] == demo.STANDBY and d["points"] == d["near_points"] == [], c
        assert d["nearest_m"] is None, c


def test_outline_distance():
    assert demo.outline_distance(0.0, 0.0, BOX) == 0.0
    assert abs(demo.outline_distance(1.5, 0.0, BOX) - 1.0) < 1e-9
    assert abs(demo.outline_distance(0.0, -1.3, BOX) - 1.0) < 1e-9


def test_no_fault_vocabulary_ever_reaches_the_page(tmp_path):
    """Whatever the vehicle state, /api/demo speaks only the three sentences."""
    codes = set(cat.CATALOGUE)
    faults = [
        st(run=run("FAULT")),
        st(line=line("FAULT"), mode="LINE"),
        st(run=run("BLOCKED", "estop")),
        st(mode="FAULT"),
        st(drives={"operational": False, "left": "Fault", "right": "Fault", "age_s": 0.1}),
    ]
    for s in faults:
        for p in (None, ps([(1.0, 0.0)])):
            body = client_for(s, tmp_path, p).get("/api/demo").get_data(as_text=True)
            assert not re.search(r"0x[0-9A-Fa-f]+|\b[0-9A-F]{4}h\b", body), body
            for word in ("PATH_BLOCKED", "DRIVE_ALARM", "cross-track", "heartbeat", "estop", "FAULT", *codes):
                assert word not in body, (word, body)
            assert json.loads(body)["sentence"] in demo.SENTENCES.values()
    assert set(demo.SENTENCES) == {demo.WATCHING, demo.NEAR, demo.STANDBY}


# ---- the page -------------------------------------------------------------------


def test_demo_is_the_landing_page(tmp_path):
    """2026-10-15: / opens the demo for both roles (the kiosk starts on /); the Demo tab leads
    back to it from the operator pages."""
    cl = client_for(st(), tmp_path, ps([(3.0, 0.0)]))
    assert cl.get("/").headers["Location"].endswith("/demo")
    assert 'href="/demo"' in cl.get("/home").get_data(as_text=True)
    assert cl.get("/demo").status_code == 200
    assert cl.get("/api/demo").get_json()["status"] == demo.WATCHING
    assert cl.post("/api/role", json={"role": "engineer", "pin": role.DEFAULT_PIN}).status_code == 200
    assert cl.get("/").headers["Location"].endswith("/demo")
    assert 'href="/demo"' in cl.get("/manual").get_data(as_text=True)


def test_the_page_says_what_the_product_is(tmp_path):
    body = client_for(st(), tmp_path).get("/demo").get_data(as_text=True)
    want = ("I-PRIME Trackless AGV", "Automated Guided Vehicle", "Smart material handling solution system")
    want += ("2 T", "1 m/s", "data-outline=", "data-zones=", "ISO 3691-4")
    for s in want:
        assert s in body, s
    assert "stands for" not in body
    # a stationary unit: nothing about driving
    for s in ("m/s right now", "driven in this demo", "Driving the route"):
        assert s not in body, s
    # a visitor cannot navigate into the operator pages from here
    for href in ('href="/manual"', 'href="/run"', 'href="/params"', 'href="/home"'):
        assert href not in body, href
    # one sliding card per content.json card, eight at most, each in its own colour
    assert body.count('class="d-slide"') == 8
    assert body.count('style="--accent:#') >= 16  # slide + dot


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
    assert c["cards"] and c["specs"]
    assert 1 <= len(c["cards"]) <= 8
    for card in c["cards"]:
        assert card["kicker"] and card["title"] and card["body"]
        assert card["icon"] in ICONS, card["icon"]
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", card["color"]), card["color"]
    with open(os.path.join(WEB, "templates", "demo.html"), encoding="utf-8") as fh:
        page = fh.read()
    for icon in ICONS:
        assert f'id="i-{icon}"' in page, icon
    for sp in c["specs"]:
        assert sp["value"] and sp["label"]
    assert float(c["near_m"]) > 0


# ---- the scanner's fields on the radar (2026-10-15) ----------------------------------


def _fields():
    with open(os.path.join(SRC, "amr_bringup", "config", "scanner_fields.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_zones_are_in_the_body_frame_and_ordered():
    z = demo.zones(_fields())
    assert [x["kind"] for x in z] == ["slow", "stop", "protective"], "outer first: drawn back to front"
    prot = z[-1]["poly"]
    assert math.isclose(min(p[0] for p in prot), -0.02 + demo.SCANNER_X_M, abs_tol=1e-3)
    assert math.isclose(max(p[0] for p in prot), 0.50 + demo.SCANNER_X_M, abs_tol=1e-3)
    assert {p[1] for p in prot} == {-0.40, 0.40}
    assert demo.zones(None) == [] and demo.zones({"fields": {"protective": {"rect": "x"}}}) == []


def test_the_page_draws_the_fields_it_was_given(tmp_path):
    body = client_for(st(), tmp_path).get("/demo").get_data(as_text=True)
    m = re.search(r"data-zones='([^']*)'", body)
    assert m, "the radar carries its zones"
    assert isinstance(json.loads(m.group(1)), list)


def test_scanner_mount_matches_the_description():
    path = os.path.join(SRC, "amr_description", "launch", "description.launch.py")
    with open(path, encoding="utf-8") as fh:
        m = re.search(r'\("laser_x", "([0-9.]+)"', fh.read())
    assert m and float(m.group(1)) == demo.SCANNER_X_M
    with open(os.path.join(WEB, "static", "demo.js"), encoding="utf-8") as fh:
        assert f"SCANNER_X = {demo.SCANNER_X_M}" in fh.read(), "the sweep starts at the scanner"


# ---- the radar needs no odometry (2026-10-15) ------------------------------------------


class BodyLive(Live):
    def __init__(self, body, ps=None):
        super().__init__(ps)
        self.body = body

    def body_pose_scan(self):
        return self.body


def test_the_body_frame_scan_shows_with_no_odometry_at_all(tmp_path):
    """Drives faulted, no wheel states, no odom TF: the odometry pose is None, but the scan
    projected through the static mount transform still reaches the page."""
    from amr_web.live import LiveStore

    store = LiveStore()
    assert store.body_pose_scan() is None
    store.set_body_scan([(3.0, 0.0), (2.0, 1.0)], source_age_s=0.05)
    body = store.body_pose_scan()
    assert body["pose"]["frame"] == body["scan"]["frame"] == "base_footprint"

    maps = tmp_path / "maps"
    maps.mkdir()
    stub = Stub(st(drives={"operational": False, "left": "Fault", "right": "Fault", "age_s": 0.1}))
    stub.live = BodyLive(body, ps=None)
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    d = app.test_client().get("/api/demo").get_json()
    assert d["status"] == demo.WATCHING and [3.0, 0.0] in d["points"]


def test_the_odometry_scan_is_the_fallback(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    stub = Stub(st())
    stub.live = BodyLive(None, ps=ps([(3.0, 0.0)]))
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    assert app.test_client().get("/api/demo").get_json()["status"] == demo.WATCHING
