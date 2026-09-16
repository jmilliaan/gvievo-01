"""Flask API against a stub adapter and a temp maps dir (spec §8 "Coordinates", T6)."""

import struct
import zlib

import numpy as np
import pytest
from amr_maps.generate_sim_factory import build
from amr_maps.grid import Grid, write
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
    app = create_app(stub, str(maps), str(fp))
    app.config["TESTING"] = True
    return app.test_client(), stub, str(maps), rev_dir, mb.verify(rev_dir)


def route_payload(steps, start=(0.0, 0.0, 0.0), repeat=1, route_id="r1"):
    return {
        "schema_version": 1,
        "route_id": route_id,
        "revision": 0,
        "map": {"id": "x", "revision": 9, "sha256": "ignored"},
        "frame_id": "map",
        "start": {"x_m": start[0], "y_m": start[1], "yaw_deg": start[2]},
        "limits": {"linear_mps": 0.3},
        "steps": steps,
        "repeat_count": repeat,
    }


def S(sid, x, y):
    return {"id": sid, "type": "straight", "to": {"x_m": x, "y_m": y}}


def R(sid, d, a):
    return {"id": sid, "type": "rotate", "direction": d, "angle_deg": a}


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


def test_validate_save_load_and_mission(env):
    client, stub, maps, rev_dir, manifest = env
    good = route_payload([S("s1", 15.0, 0.0), R("s2", "ccw", 180), S("s3", 2.0, 0.0)])
    r = client.post("/api/maps/sim_factory/1/routes/validate", json=good)
    assert r.status_code == 200 and r.json["ok"] and r.json["compiled"]["steps"][1]["signed_angle_deg"] == 180
    assert r.json["route"]["map"]["sha256"] == manifest.sha256  # server binds the route to the loaded bundle
    assert len(stub.previews) == 1
    r = client.post("/api/maps/sim_factory/1/routes/save", json=good)
    assert r.status_code == 200 and r.json["revision"] == 1
    r = client.post("/api/maps/sim_factory/1/routes/save", json=good)
    assert r.json["revision"] == 2
    r = client.get("/api/maps/sim_factory/1/routes/r1/2")
    assert r.status_code == 200 and r.json["ok"] and r.json["route"]["revision"] == 2
    r = client.post(
        "/api/missions",
        json={"map_id": "sim_factory", "map_revision": 1, "route_id": "r1", "route_revision": 2},
    )
    assert r.status_code == 200 and r.json["mission_id"] == "r1_rev2"
    r = client.get("/api/missions")
    assert r.json[0]["route"]["revision"] == 2 and r.json[0]["map"]["sha256"] == manifest.sha256
    assert (
        client.post(
            "/api/missions",
            json={"map_id": "sim_factory", "map_revision": 1, "route_id": "r1", "route_revision": 7},
        ).status_code
        == 404
    )
    assert client.post("/api/missions", json={}).status_code == 400


def test_invalid_routes_are_422_with_step_ids(env):
    client, stub, maps, rev_dir, manifest = env
    r = client.post(
        "/api/maps/sim_factory/1/routes/validate",
        json=route_payload([S("s1", 5.0, 0.0), R("s2", "ccw", 90), S("s3", 5.0, 4.0)]),
    )
    assert r.status_code == 422 and not r.json["ok"]
    assert any(i["step_id"] == "s3" and i["code"] == "clearance" for i in r.json["issues"])
    r = client.post("/api/maps/sim_factory/1/routes/validate", json=route_payload([S("s1", 3.0, 0.5)]))
    assert (
        r.status_code == 422
        and r.json["issues"][0]["step_id"] == "s1"
        and "turn" in r.json["issues"][0]["message"]
    )
    r = client.post("/api/maps/sim_factory/1/routes/validate", json=route_payload([R("t", "cw", 60)]))
    assert r.status_code == 422
    r = client.post("/api/maps/sim_factory/1/routes/save", json=route_payload([S("s1", 3.0, 0.5)]))
    assert r.status_code == 422
    r = client.post("/api/maps/sim_factory/1/routes/validate", json={"schema_version": 3})
    assert r.status_code == 422 and r.json["issues"][0]["code"] == "schema"
    assert stub.previews == []  # nothing invalid is previewed


def test_keepout_mask_is_honoured(env):
    client, stub, maps, rev_dir, manifest = env
    g = build()
    ko = Grid(np.zeros(g.data.shape, dtype=np.int8), g.meta)
    r0, c0 = g.world_to_cell(6.0, 0.0)
    ko.data[r0 - 2 : r0 + 2, c0 - 2 : c0 + 2] = 100
    write(ko, f"{rev_dir}/keepout")
    r = client.post("/api/maps/sim_factory/1/routes/validate", json=route_payload([S("s1", 12.0, 0.0)]))
    assert r.status_code == 422 and any("keepout" in i["message"] for i in r.json["issues"])


def test_coordinator_endpoints_delegate_and_never_touch_wheels(env):
    client, stub, maps, rev_dir, manifest = env
    for path, body, name in (
        ("/api/localization/confirm", {}, "localization_confirm"),
        ("/api/localization/initialpose", {"x_m": 1, "y_m": 2, "yaw_rad": 0.5}, "set_initial_pose"),
        ("/api/mission/run", {"mission_id": "m"}, "run_mission"),
        ("/api/mission/pause", {}, "pause"),
        ("/api/mission/resume", {}, "prepare_resume"),
        ("/api/mission/abort", {}, "abort"),
        ("/api/mission/ack", {}, "ack_fault"),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 200 and r.json["ok"], path
        assert stub.calls[-1][0] == name
    assert stub.calls[1] == ("set_initial_pose", (1.0, 2.0, 0.5))
    assert client.post("/api/localization/initialpose", json={"x_m": "no"}).status_code == 400
    rules = [str(r.rule) for r in client.application.url_map.iter_rules()]
    # the one velocity-publishing route is the held manual refresh; nothing else
    assert not any("cmd_vel" in r or "drive" in r or "jog" in r for r in rules)
    assert (
        sum("/api/manual" in r for r in rules) == 3
    )  # press, refresh, release (the /manual page is not an API)


def test_mode_and_survey_are_asynchronous_operations(env):
    client, stub, *_ = env
    r = client.post(
        "/api/mode", json={"target": "navigation", "map_id": "m", "map_revision": 2, "request_id": "r1"}
    )
    assert r.status_code == 202 and r.json["operation_id"] == "op-mode"
    assert stub.calls[-1] == ("request_mode", (3, "m", 2, "r1"))
    assert client.get("/api/operations/op-mode").json["status_name"] == "PENDING"
    assert client.get("/api/operations/nope").status_code == 404
    assert client.post("/api/mode", json={"target": "navigation", "map_id": "m"}).status_code == 422
    assert client.post("/api/mode", json={"target": "fly"}).status_code == 400
    r = client.post("/api/survey/start", json={"map_id": "a", "description": "mark"})
    assert (
        r.status_code == 202
        and stub.calls[-1][0] == "survey_request"
        and stub.calls[-1][1][:3] == (0, "a", "mark")
    )
    r = client.post("/api/survey/save", json={"note": "seams ok"})
    assert r.status_code == 202 and stub.calls[-1][1][:3] == (2, "", "seams ok")
    assert client.post("/api/survey/bogus", json={}).status_code == 404


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
    for page in ("/maps", "/editor", "/run"):
        assert client.get(page).status_code == 200
