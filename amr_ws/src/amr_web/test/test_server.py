"""Flask API against a stub adapter and a temp maps dir (spec §8 "Coordinates", T6)."""

import struct
import zlib

import numpy as np
import pytest
from amr_maps.generate_sim_factory import build
from amr_web.png import encode_gray
from amr_web.server import create_app

from amr_mission import map_bundle as mb


class Stub:
    def __init__(self):
        self.calls = []
        self.run_state = None
        self.identity = ("inst-1", 3)
        self.published = []
        self.ops = {}

    def state(self):
        return {"mapping": None, "localization": {"state_name": "READY"}, "run": self.run_state}

    # supervisor surface (unified plan §6.2)
    def supervisor_identity(self):
        return self.identity

    def request_mode(self, target, map_id, rev, request_id):
        self.calls.append(("request_mode", (target, map_id, rev, request_id)))
        self.ops["op-mode"] = {"operation_id": "op-mode", "status": 0, "status_name": "PENDING"}
        return True, "op-mode", "accepted"

    def survey_request(self, operation, map_id, description, request_id, cont=None):
        args = (operation, map_id, description, request_id) + ((cont,) if cont is not None else ())
        self.calls.append(("survey_request", args))
        return True, "op-survey", "accepted"

    def get_operation(self, oid):
        return self.ops.get(oid)

    def survey_move(self, kind, value):
        self.calls.append(("survey_move", (kind, value)))
        return (False, "refused: selector is not MANUAL") if value == 99 else (True, "forward 1.00 m")

    def survey_move_stop(self):
        self.calls.append(("survey_move_stop", ()))
        return True, "stopped"

    def manual_publish(self, cmd):
        self.published.append(cmd)

    def _rec(self, name):
        def fn(*a):
            self.calls.append((name, a))
            return True, f"{name} ok"

        return fn

    def __getattr__(self, name):
        return self._rec(name)


@pytest.fixture()
def env(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    # the sim world as a published bundle
    g = build()
    stage = mb.staging_dir(str(maps), "sim_factory", 1)
    m = mb.Manifest(
        "sim_factory",
        1,
        mb.now_iso(),
        "map",
        0.05,
        [-3.0, -10.0, 0.0],
        g.width,
        g.height,
        {"x_m": 0, "y_m": 0, "yaw_rad": 0, "description": "mark"},
        {"dx_m": 0, "dy_m": 0, "dyaw_rad": 0, "note": "t"},
    )
    mb.stage_bundle(stage, g, None, m, required_posegraph=False)
    mb.verify(stage)
    rev_dir = mb.publish(stage, str(maps), "sim_factory", 1)
    stub = Stub()
    # state_dir in the tmp tree: the app writes web.json (the engineer PIN and the
    # session secret) there, and a test must never touch the vehicle's real ~/.amr.
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    return app.test_client(), stub, str(maps), rev_dir, mb.verify(rev_dir)


def test_maps_index_and_image(env):
    client, stub, maps, rev_dir, manifest = env
    r = client.get("/api/maps")
    assert r.status_code == 200 and r.json[0]["map_id"] == "sim_factory"
    assert r.json[0]["revisions"][0]["sha256"] == manifest.sha256
    r = client.get("/api/maps/sim_factory/1")
    assert r.json["width"] == 600 and r.json["origin"] == [-3.0, -10.0, 0.0]
    r = client.get("/api/maps/sim_factory/1/image.png")
    assert r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", r.data[16:24])
    assert (w, h) == (600, 400)
    assert client.get("/api/maps/nope/1").status_code == 404


def test_png_encoder_round_trip():
    img = (np.arange(12, dtype=np.uint8) * 20).reshape(3, 4)
    png = encode_gray(img)
    idat_len = struct.unpack(">I", png[33:37])[0]
    raw = zlib.decompress(png[41 : 41 + idat_len])
    rows = [raw[i * 5 + 1 : i * 5 + 5] for i in range(3)]
    assert rows == [img[r].tobytes() for r in range(3)]


def test_coordinator_endpoints_delegate_and_never_touch_wheels(env):
    client, stub, maps, rev_dir, manifest = env
    for path, body, name in (
        ("/api/localization/confirm", {}, "localization_confirm"),
        (
            "/api/localization/initialpose",
            {"x_m": 1, "y_m": 2, "yaw_rad": 0.5, "map_id": "a", "map_revision": 2, "generation": 7},
            "set_initial_pose",
        ),
        ("/api/mission/ack", {}, "ack_fault"),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 200 and r.json["ok"], path
        assert stub.calls[-1][0] == name
    assert stub.calls[1] == ("set_initial_pose", (1.0, 2.0, 0.5, "a", 2, 7, ""))
    # R12: a pose without the map identity it was drawn on is not accepted at all
    no_map = {"x_m": 1, "y_m": 2, "yaw_rad": 0}
    assert client.post("/api/localization/initialpose", json=no_map).status_code == 400
    assert client.post("/api/localization/initialpose", json={"x_m": "no"}).status_code == 400
    rules = [str(r.rule) for r in client.application.url_map.iter_rules()]
    # the one velocity-publishing route is the held manual refresh; nothing else
    assert not any("cmd_vel" in r or "drive" in r or "jog" in r for r in rules)
    assert (
        sum("/api/manual" in r for r in rules) == 3
    )  # press, refresh, release (the /manual page is not an API)


def test_mode_and_survey_are_asynchronous_operations(env):
    client, stub, *_ = env
    r = client.post("/api/mode", json={"target": "line", "request_id": "r1"})
    assert r.status_code == 202 and r.json["operation_id"] == "op-mode"
    assert stub.calls[-1] == ("request_mode", (7, "", 0, "r1"))
    assert client.get("/api/operations/op-mode").json["status_name"] == "PENDING"
    assert client.get("/api/operations/nope").status_code == 404
    # NAVIGATION is not entered from the web since 2026-10-28 (no routes, no trackless missions)
    n = len(stub.calls)
    nav = {"target": "navigation", "map_id": "m", "map_revision": 2}
    for bad in (nav, {"target": "idle"}, {"target": "fly"}):
        assert client.post("/api/mode", json=bad).status_code == 400
    assert len(stub.calls) == n
    r = client.post("/api/survey/start", json={"map_id": "a", "description": "mark"})
    assert (
        r.status_code == 202
        and stub.calls[-1][0] == "survey_request"
        and stub.calls[-1][1][:3] == (0, "a", "mark")
    )
    r = client.post("/api/survey/save", json={"note": "seams ok"})
    assert r.status_code == 202 and stub.calls[-1][1][:3] == (2, "", "seams ok")
    assert client.post("/api/survey/bogus", json={}).status_code == 404


def test_continue_survey_start_forwards_revision_and_hint(env):
    client, stub, *_ = env
    body = {"map_id": "hall", "description": "by rack C", "continue_revision": 2,
            "hint": {"x_m": 51.8, "y_m": -38.9, "yaw_rad": 0.03}}
    r = client.post("/api/survey/start", json=body)
    assert r.status_code == 202 and stub.calls[-1] == (
        "survey_request", (0, "hall", "by rack C", stub.calls[-1][1][3], (2, 51.8, -38.9, 0.03))
    )
    n = len(stub.calls)
    for bad in (
        {**body, "hint": None},
        {**body, "hint": {"x_m": 1.0, "y_m": "x", "yaw_rad": 0.0}},
        {**body, "hint": {"x_m": float("inf"), "y_m": 0.0, "yaw_rad": 0.0}},
        {**body, "continue_revision": -1},
        {**body, "continue_revision": True},
    ):
        assert client.post("/api/survey/start", json=bad).status_code == 422
    assert len(stub.calls) == n  # nothing refused reached the robot
    # continue_revision 0 is an ordinary new map
    r = client.post("/api/survey/start", json={**body, "continue_revision": 0})
    assert r.status_code == 202 and len(stub.calls[-1][1]) == 4


def test_maps_say_which_revisions_can_be_continued(env, tmp_path):
    client, stub, maps, rev_dir, manifest = env
    assert client.get("/api/maps").json[0]["revisions"][0]["continuable"] is False  # no pose graph
    pg = tmp_path / "pg"
    (tmp_path / "pg.posegraph").write_bytes(b"graph")
    (tmp_path / "pg.data").write_bytes(b"data")
    stage = mb.staging_dir(maps, "hall", 1)
    m, g = mb.load(maps, "sim_factory", 1)
    m.map_id = "hall"
    mb.stage_bundle(stage, g, str(pg), m)
    mb.publish(stage, maps, "hall", 1)
    idx = {x["map_id"]: x for x in client.get("/api/maps").json}
    assert idx["hall"]["revisions"][0]["continuable"] is True
    one = client.get("/api/maps/hall/1").json
    assert one["continuable"] is True and one["review"]["note"] == "t"
    page = client.get("/mapping")
    assert page.status_code == 200
    assert b'id="btn-cs-start"' in page.data and b"mapping.js" in page.data
    assert client.get("/survey-continue?map=hall&rev=1").headers["Location"].endswith("/mapping")


def test_guided_branch_orders_need_the_engineer_and_a_valid_side(env):
    client, stub, *_ = env
    r = client.post("/api/line/branch", json={"side": "left"})
    assert r.status_code == 200 and stub.calls[-1] == ("line_branch", ("left",))
    n = len(stub.calls)
    for bad in ({"side": "up"}, {"side": ""}, {}):
        assert client.post("/api/line/branch", json=bad).status_code == 422
    client.post("/api/role", json={"role": "operator"})
    assert client.post("/api/line/branch", json={"side": "right"}).status_code == 403
    assert len(stub.calls) == n  # nothing refused reached the robot
    page = client.get("/teach")
    assert page.status_code == 200 and b'data-side="straight"' in page.data and b"ArrowLeft" in page.data


def test_guided_speed_toggle_needs_the_engineer_and_a_valid_level(env):
    client, stub, *_ = env
    r = client.post("/api/line/speed", json={"level": "high"})
    assert r.status_code == 200 and stub.calls[-1] == ("line_speed", ("high",))
    n = len(stub.calls)
    for bad in ({"level": "fast"}, {"level": ""}, {}):
        assert client.post("/api/line/speed", json=bad).status_code == 422
    client.post("/api/role", json={"role": "operator"})
    assert client.post("/api/line/speed", json={"level": "normal"}).status_code == 403
    assert len(stub.calls) == n  # nothing refused reached the robot
    page = client.get("/teach")
    assert b'data-speed="normal"' in page.data and b'data-speed="high"' in page.data


def test_state_and_page_addresses(env):
    """2026-10-28: Mapping replaces Run trackless, Maps, Routes, Review and Continue survey; Run is
    the tape product; Guide is part of Teach. Old addresses redirect, removed tools are gone."""
    client, stub, maps, rev_dir, manifest = env
    assert client.get("/api/state").json["localization"]["state_name"] == "READY"
    assert client.get("/").status_code == 302
    for page in ("/mapping", "/run", "/teach"):
        assert client.get(page).status_code == 200, page
    for old, new in (("/maps", "/mapping"), ("/survey-continue", "/mapping"), ("/run-trackless", "/mapping"),
                     ("/run-tracked", "/run"), ("/guide", "/teach"), ("/calls", "/run#calls")):
        r = client.get(old)
        assert r.status_code == 302 and r.headers["Location"].endswith(new), old
    for gone in ("/editor", "/review", "/demo", "/api/demo", "/api/footprint", "/api/missions",
                 "/api/maps/sim_factory/1/dynamic.png", "/api/maps/sim_factory/1/routes/r1/1"):
        assert client.get(gone).status_code == 404, gone
    for gone in ("/api/mission/run", "/api/mission/resume", "/api/mission/pause", "/api/mission/abort",
                 "/api/missions", "/api/maps/sim_factory/1/edit", "/api/maps/sim_factory/1/routes/validate",
                 "/api/maps/sim_factory/1/routes/save"):
        assert client.post(gone, json={}).status_code in (404, 405), gone
    assert stub.calls == []


def test_pages_fonts_and_style_guards(env):
    """web-style W8: every page renders, fonts are self-hosted, and the style rules that
    are mechanical (no external URLs, light only, flat, square) hold in the source."""
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    client = env[0]
    for page in (
        "/home",
        "/manual",
        "/mapping",
        "/run",
        "/teach",
        "/monitor",
        "/io",
        "/alarms",
        "/params",
    ):
        r = client.get(page)
        assert r.status_code == 200, page
        assert b'id="telemetry"' in r.data and b"/static/amr.css" in r.data, page
    r = client.get("/static/fonts/plex-mono-400.woff2")
    assert r.status_code == 200 and r.data[:4] == b"wOF2"
    root = pathlib.Path(__file__).resolve().parents[1] / "amr_web"
    sources = [*root.glob("static/*.css"), *root.glob("static/*.js"), *root.glob("templates/*.html")]
    assert len(sources) > 15
    for f in sources:
        text = f.read_text()
        assert not re.search(r"https?://", text), f"external URL in {f.name}"
        assert not re.search(r"@media[^{]*prefers-color-scheme", text), f"dark-mode query in {f.name}"
        assert "box-shadow" not in text, f.name
        assert "gradient(" not in text, f.name
        for radius in re.findall(r"border-radius\s*:\s*([^;}]+)", text):
            assert radius.strip() in ("50%", "2px", "0"), f"{f.name}: border-radius {radius}"


def test_one_layout_three_sizes(env):
    """amr.css "one layout, three sizes": the laptop and the 7-inch HMI report near-identical
    CSS viewports, so the app scales itself through the root font size. Every length in
    the stylesheet must be rem (a px font or width would not follow the knob), the knob
    must be applied before the stylesheet loads (no flash at the wrong size), and every
    page must carry the Aa control that cycles it."""
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    root = pathlib.Path(__file__).resolve().parents[1] / "amr_web"
    css = (root / "static" / "amr.css").read_text()
    for size in ("s", "m", "l"):
        assert f'html[data-ui="{size}"]' in css or (size == "s" and "html { font-size:10px; }" in css)
    # borders (1-4px hairlines) and the two real-pixel @media breakpoints are the exceptions
    prop = r"(?:font-size|font|width|height|padding|margin|gap)"
    lengths = re.finditer(prop + r"\s*:[^;{}]*?\b(\d+(?:\.\d+)?)px", css)
    px = [m.group(0) for m in lengths if float(m.group(1)) > 4 and not m.group(0).startswith("font-size:1")]
    px = [x for x in px if x not in ("width:820px", "width:760px")]
    assert not px, f"px lengths in amr.css do not follow the size knob: {px}"
    assert "rem" in css and "@media (pointer:coarse)" in css

    base = (root / "templates" / "base.html").read_text()
    assert base.index("dataset.ui") < base.index('href="/static/amr.css"')
    assert "(pointer:coarse)" in base and "amr.ui" in base
    client = env[0]
    for page in ("/home", "/manual", "/run", "/alarms"):
        html = client.get(page).data.decode()
        assert 'id="ui-size"' in html and 'id="pill-link"' in html, page


def test_every_element_id_a_page_script_uses_exists_on_that_page(env):
    """web-style §6: no JS runtime in CI - an id renamed in a template must not silently
    break its handler. Collects $('id') / getElementById('id') / tile|tiles('id') from the
    page's inline and linked scripts and checks the rendered page defines each id."""
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    client = env[0]
    static = pathlib.Path(__file__).resolve().parents[1] / "amr_web" / "static"
    pat = re.compile(r"""(?:\$|getElementById|tiles?)\(\s*'([A-Za-z][\w-]*)'""")
    # Some ids exist only in one role (the engineer's Restart button), so a page is
    # rendered in BOTH and the ids unioned - a handler must match the markup it ships with.
    from amr_web import role as rolemod  # noqa: PLC0415

    for page in (
        "/manual",
        "/mapping",
        "/run",
        "/teach",
        "/monitor",
        "/io",
        "/alarms",
        "/params",
    ):
        client.post("/api/role", json={"role": "operator"})
        html = client.get(page).data.decode()
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        client.post("/api/role", json={"role": "engineer", "pin": rolemod.DEFAULT_PIN})
        eng = client.get(page).data.decode()
        ids |= set(re.findall(r'\bid="([^"]+)"', eng))
        html += eng
        code = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
        for src in sorted(set(re.findall(r'<script src="/static/([\w.]+)"', html))):
            code += (static / src).read_text()  # amr.js too: the rail ids must exist on every page
        missing = {i for i in pat.findall(code) if i not in ids}
        assert not missing, f"{page}: scripts use ids not on the page: {sorted(missing)}"


def test_wifi_parse_and_bars(tmp_path):
    from amr_web import wifi

    proc = (
        "Inter-| sta-|   Quality        | Discarded packets | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt frag retry misc | beacon | 22\n"
        "wlp1s0: 0000   70.  -40.  -256        0      0      0      0     83        0\n"
    )
    assert wifi.parse_proc(proc, "wlp1s0") == -40.0
    assert wifi.parse_proc(proc, "wlan9") is None
    assert [wifi.bars_for(d) for d in (-40, -60, -70, -80, -90, None)] == [4, 3, 2, 1, 0, 0]

    p = tmp_path / "wireless"
    p.write_text(proc)
    r = wifi.WifiReader("wlp1s0", proc_path=str(p))
    r._ssid, r._ssid_t = "agv_field", float("inf")  # skip nmcli in the test
    out = r.read()
    assert (out["connected"], out["dbm"], out["bars"], out["ssid"]) == (True, -40.0, 4, "agv_field")
    p.write_text(proc.splitlines()[0] + "\n")
    assert wifi.WifiReader("wlp1s0", proc_path=str(p)).read()["connected"] is False
    assert wifi.WifiReader("wlp1s0", proc_path=str(tmp_path / "missing")).read()["bars"] == 0


def test_wifi_endpoint(env):
    client = env[0]
    r = client.get("/api/wifi")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) >= {"iface", "connected", "ssid", "dbm", "bars"}


def test_survey_move_endpoints_forward_to_the_node_and_validate(env):
    client, stub, *_ = env
    r = client.post("/api/survey_move", json={"kind": "straight", "value": 1.0})
    assert r.status_code == 200 and r.json["message"] == "forward 1.00 m"
    assert ("survey_move", ("straight", 1.0)) in stub.calls
    r = client.post("/api/survey_move", json={"kind": "straight", "value": 99})
    assert r.status_code == 409 and "MANUAL" in r.json["message"]  # the node's refusal, passed on
    for bad in ({"kind": "strafe", "value": 1}, {"kind": "rotate", "value": "x"}, {"kind": "rotate"}):
        assert client.post("/api/survey_move", json=bad).status_code == 422
    assert client.post("/api/survey_move/stop", json={}).status_code == 200
    page = client.get("/mapping").data
    for el in (
        b'id="sm-dist"', b'id="sm-fwd"', b'id="sm-rev"', b'id="sm-stop"',
        b'data-deg="-135"', b'data-deg="20"', b'data-deg="-30"',
    ):
        assert el in page


# ---- F12: payload shape is a 400, never a 500, and never an adapter call -------------

_JSON_POSTS = [
    "/api/mode",
    "/api/survey/start",
    "/api/survey_move",
    "/api/manual/press",
    "/api/manual/refresh",
    "/api/manual/release",
    "/api/localization/initialpose",
]


@pytest.mark.parametrize("path", _JSON_POSTS)
@pytest.mark.parametrize("raw", ["[1]", '"text"', "7", "null", "{not json", "true"])
def test_wrong_shaped_json_is_a_400_before_any_adapter_call(env, path, raw):
    """POST [1] to /api/mode used to be a 500 from `.get` on a list."""
    client, stub, *_ = env
    before = list(stub.calls)
    r = client.post(path, data=raw, content_type="application/json")
    assert r.status_code == 400, (path, raw, r.status_code, r.get_data(as_text=True)[:200])
    assert r.is_json and r.get_json()["ok"] is False
    assert stub.calls == before, "an invalid payload reached the adapter"


def test_initialpose_rejects_booleans_nonfinite_and_bad_revisions(env):
    client, stub, *_ = env
    good = {
        "x_m": 1.0,
        "y_m": 2.0,
        "yaw_rad": 0.1,
        "map_id": "sim_factory",
        "map_revision": 1,
        "generation": 3,
    }
    for k, v in (
        ("x_m", True),
        ("y_m", "1"),
        ("yaw_rad", None),
        ("map_revision", 0),
        ("map_revision", True),
        ("map_revision", 1.5),
        ("map_revision", 10**30 * 1.0),
        ("generation", -1),
        ("map_id", 5),
        ("map_id", ""),
    ):
        bad = {**good, k: v}
        r = client.post("/api/localization/initialpose", json=bad)
        assert r.status_code == 400, (k, v, r.get_json())
    r = client.post(
        "/api/localization/initialpose",
        data='{"x_m": 1e999, "y_m": 0, "yaw_rad": 0, "map_id": "m", "map_revision": 1, "generation": 0}',
        content_type="application/json",
    )
    assert r.status_code == 400


def test_survey_move_value_must_be_a_finite_number(env):
    client, stub, *_ = env
    for v in (True, "1", None, [1]):
        r = client.post("/api/survey_move", json={"kind": "straight", "value": v})
        assert r.status_code == 422, (v, r.get_json())
    r = client.post(
        "/api/survey_move", data='{"kind": "straight", "value": 1e999}', content_type="application/json"
    )
    assert r.status_code == 422
    assert not any(c[0] == "survey_move" for c in stub.calls)


def test_guided_forced_u_turn_needs_the_engineer_and_a_boolean(env):
    client, stub, *_ = env
    r = client.post("/api/line/uturn", json={"force": True})
    assert r.status_code == 200 and stub.calls[-1] == ("line_uturn", (True,))
    r = client.post("/api/line/uturn", json={"force": False})
    assert r.status_code == 200 and stub.calls[-1] == ("line_uturn", (False,))
    n = len(stub.calls)
    for bad in ({"force": "yes"}, {"force": 1}, {}):
        assert client.post("/api/line/uturn", json=bad).status_code == 422
    client.post("/api/role", json={"role": "operator"})
    assert client.post("/api/line/uturn", json={"force": True}).status_code == 403
    assert len(stub.calls) == n  # nothing refused reached the robot
    page = client.get("/teach")
    assert page.status_code == 200 and b'data-uturn="true"' in page.data


def test_guided_continue_needs_the_engineer_and_a_boolean(env):
    client, stub, *_ = env
    r = client.post("/api/line/continue", json={"arm": True})
    assert r.status_code == 200 and stub.calls[-1] == ("line_continue", (True,))
    n = len(stub.calls)
    for bad in ({"arm": "yes"}, {}):
        assert client.post("/api/line/continue", json=bad).status_code == 422
    client.post("/api/role", json={"role": "operator"})
    assert client.post("/api/line/continue", json={"arm": True}).status_code == 403
    assert len(stub.calls) == n
    assert b'data-continue="true"' in client.get("/teach").data


def test_the_tape_graph_overlay_is_read_only_and_for_any_role(env):
    client, stub, *_ = env
    teach = client.get("/teach").data
    assert b'data-act="mark_delete"' in teach and b'data-act="mark_role"' in teach
    assert b'id="gd-mark"' in teach
    client.post("/api/role", json={"role": "operator"})
    r = client.get("/api/line/graph")
    assert r.status_code == 200 and r.json["available"] is False
    assert b"tapegraph.js" in client.get("/mapping").data



def test_the_survey_spins_are_the_steps_the_move_accepts(env):
    """Lean plan D109: mapping.html renders ROTATE_STEPS_DEG, both directions."""
    from amr_mission.survey_move import ROTATE_STEPS_DEG  # noqa: PLC0415

    client = env[0]
    html = client.get("/mapping").get_data(as_text=True)
    for d in ROTATE_STEPS_DEG:
        assert f'data-deg="{d:g}">Left {d:g}°' in html and f'data-deg="-{d:g}">Right {d:g}°' in html
    assert html.count('class="tool" data-deg=') == 2 * len(ROTATE_STEPS_DEG) == 12


def test_pages_carry_the_jog_constants(env):
    """Lean plan D109: jogpad.js reads the Python constants from the page."""
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    from amr_web import jog  # noqa: PLC0415

    client = env[0]
    html = client.get("/mapping").get_data(as_text=True)
    assert json.loads(re.search(r"data-jog='([^']*)'", html).group(1)) == jog.page_constants()
