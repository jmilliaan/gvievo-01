"""Flask API against a stub adapter and a temp maps dir (spec §8 "Coordinates", T6)."""

import struct
import zlib

import numpy as np
import pytest
from amr_maps.generate_sim_factory import build
from amr_web.png import encode_gray
from amr_web.server import create_app

from amr_mission import map_bundle as mb

FOOTPRINT_YAML = "polygon: [[-0.5, -0.35], [1.1, -0.35], [1.1, 0.35], [-0.5, 0.35]]\nmargin_m: 0.20\n"


class Stub:
    def __init__(self):
        self.calls = []
        self.previews = []
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

    def survey_request(self, operation, map_id, description, request_id):
        self.calls.append(("survey_request", (operation, map_id, description, request_id)))
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
        if name == "publish_route_preview":
            return lambda compiled, frame: self.previews.append((compiled, frame))
        return self._rec(name)


@pytest.fixture()
def env(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    # world as bundle, plus an unknown patch and a keepout mask for the validation paths
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
    fp = tmp_path / "footprint.yaml"
    fp.write_text(FOOTPRINT_YAML)
    stub = Stub()
    # state_dir in the tmp tree: the app writes web.json (the engineer PIN and the
    # session secret) there, and a test must never touch the vehicle's real ~/.amr.
    app = create_app(stub, str(maps), str(fp), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    return app.test_client(), stub, str(maps), rev_dir, mb.verify(rev_dir)


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
        ("/api/mission/ack", {}, "ack_fault"),
        ("/api/recover", {}, "recover"),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 200 and r.json["ok"], path
        assert stub.calls[-1][0] == name
    rules = [str(r.rule) for r in client.application.url_map.iter_rules()]
    # the one velocity-publishing route is the held manual refresh; nothing else
    assert not any("cmd_vel" in r or "drive" in r or "jog" in r for r in rules)
    assert (
        sum("/api/manual" in r for r in rules) == 3
    )  # press, refresh, release (the /manual page is not an API)


def test_removed_pages_and_apis_are_gone(env):
    """aop-demo-oct: a manual-only vehicle. The run, map, I/O, status and commissioning
    surfaces are not hidden, they do not exist."""
    client, *_ = env
    for page in ("/status", "/io", "/commissioning", "/run", "/run-tracked", "/run-trackless",
                 "/maps", "/editor", "/review"):
        assert client.get(page).status_code == 404, page
    rules = {str(r.rule) for r in client.application.url_map.iter_rules()}
    for gone in ("/api/mode", "/api/maps", "/api/missions", "/api/io", "/api/commissioning",
                 "/api/line/mission", "/api/survey/<op>", "/api/localization/initialpose",
                 "/api/mission/run"):
        assert gone not in rules, gone


def test_arm_delegates_and_disarm_revokes_the_jog_first(env):
    """The web app is the panel's Manual Arm: /api/arm takes a strict boolean; a disarm
    revokes every manual session at the mux before the drives are unpowered."""
    client, stub, *_ = env
    r = client.post("/api/arm", json={"arm": True})
    assert r.status_code == 200 and stub.calls[-1] == ("set_arm", (True,))
    assert stub.published == []  # arming moves nothing and publishes nothing
    r = client.post("/api/arm", json={"arm": False})
    assert r.status_code == 200 and stub.calls[-1] == ("set_arm", (False,))
    assert len(stub.published) == 1 and stub.published[0].valid_for_s == 0.0
    n = len(stub.calls)
    for bad in ({}, {"arm": "yes"}, {"arm": 1}, {"arm": None}):
        assert client.post("/api/arm", json=bad).status_code == 400, bad
    assert len(stub.calls) == n


def test_state_and_footprint(env):
    client, stub, maps, rev_dir, manifest = env
    assert client.get("/api/state").json["localization"]["state_name"] == "READY"
    fp = client.get("/api/footprint").json
    assert (
        fp["margin_m"] == 0.2
        and len(fp["polygon"]) == 4
        and fp["reach_m"] == pytest.approx((1.1**2 + 0.35**2) ** 0.5)
    )
    assert client.get("/").status_code == 302
    for page in ("/home", "/manual", "/alarms"):
        assert client.get(page).status_code == 200



def test_pages_fonts_and_style_guards(env):
    """web-style W8: every page renders, fonts are self-hosted, and the style rules that
    are mechanical (no external URLs, light only, flat, square) hold in the source."""
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    client = env[0]
    for page in ("/home", "/manual", "/monitor", "/alarms", "/params"):
        r = client.get(page)
        assert r.status_code == 200, page
        assert b'id="telemetry"' in r.data and b"/static/amr.css" in r.data, page
    r = client.get("/static/fonts/plex-mono-400.woff2")
    assert r.status_code == 200 and r.data[:4] == b"wOF2"
    root = pathlib.Path(__file__).resolve().parents[1] / "amr_web"
    sources = [*root.glob("static/*.css"), *root.glob("static/*.js"), *root.glob("templates/*.html")]
    assert len(sources) > 8
    for f in sources:
        text = f.read_text()
        assert not re.search(r"https?://", text), f"external URL in {f.name}"
        assert not re.search(r"@media[^{]*prefers-color-scheme", text), f"dark-mode query in {f.name}"
        if f.stem == "demo":
            continue  # the visitors' page has its own brochure look (plan 2026-09-23-demo-page §5)
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
    for page in ("/home", "/manual", "/alarms"):
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

    for page in ("/home", "/manual", "/monitor", "/alarms", "/params"):
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


# ---- dynamic-mapping plan §1.2/§1.3: map review -> a derived revision -------------------------


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# ---- F12: payload shape is a 400, never a 500, and never an adapter call -------------

_JSON_POSTS = [
    "/api/arm",
    "/api/manual/press",
    "/api/manual/refresh",
    "/api/manual/release",
]


@pytest.mark.parametrize("path", _JSON_POSTS)
@pytest.mark.parametrize("raw", ["[1]", '"text"', "7", "null", "{not json", "true"])
def test_wrong_shaped_json_is_a_400_before_any_adapter_call(env, path, raw):
    """POST [1] to an endpoint used to be a 500 from `.get` on a list."""
    client, stub, *_ = env
    before = list(stub.calls)
    r = client.post(path, data=raw, content_type="application/json")
    assert r.status_code == 400, (path, raw, r.status_code, r.get_data(as_text=True)[:200])
    assert r.is_json and r.get_json()["ok"] is False
    assert stub.calls == before, "an invalid payload reached the adapter"

