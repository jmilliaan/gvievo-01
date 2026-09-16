"""Flask app for the operator pages (spec §1.2, §6.3). Framework-independent of ROS:
everything ROS goes through an `Adapter` object so the app is testable with a stub.

Nothing here commands wheels. Selecting, drawing, validating or saving moves
nothing; the run page only calls the coordinator's services (pause / abort /
prepare-resume / load), and the physical panel Start authorises motion.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import numpy as np
from amr_navigation.route import Route, RouteError
from amr_navigation.validate import load_keepout, validate
from flask import Flask, Response, jsonify, redirect, render_template, request

from amr_maps import grid as gridio
from amr_mission import map_bundle as mb
from amr_navigation import footprint as fpmod
from amr_navigation import store
from amr_web.png import encode_gray


class Adapter(Protocol):
    """What the pages need from ROS. `amr_web.adapter.RosAdapter` implements it."""

    def state(self) -> dict[str, Any]: ...
    def survey_start(self, map_id: str, description: str) -> tuple[bool, str]: ...
    def survey_returned(self) -> tuple[bool, str]: ...
    def survey_save(self, note: str) -> tuple[bool, str]: ...
    def survey_abort(self) -> tuple[bool, str]: ...
    def localization_confirm(self) -> tuple[bool, str]: ...
    def localization_reset(self) -> tuple[bool, str]: ...
    def set_initial_pose(self, x: float, y: float, yaw: float) -> tuple[bool, str]: ...
    def publish_route_preview(self, compiled, frame_id: str) -> None: ...
    def run_mission(self, mission_id: str) -> tuple[bool, str]: ...
    def pause(self) -> tuple[bool, str]: ...
    def abort(self) -> tuple[bool, str]: ...
    def prepare_resume(self) -> tuple[bool, str]: ...
    def ack_fault(self) -> tuple[bool, str]: ...


def _result(ok: bool, message: str, status_fail: int = 409, **extra):
    body = {"ok": ok, "message": message, **extra}
    return jsonify(body), (200 if ok else status_fail)


def create_app(adapter: Adapter, maps_dir: str, footprint_path: str | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
    app.config["MAPS_DIR"] = os.path.expanduser(maps_dir)
    fp = fpmod.load(footprint_path or fpmod.default_path())
    app.config["FOOTPRINT"] = fp
    _grids: dict[tuple[str, int], tuple[Any, gridio.Grid]] = {}

    def bundle(map_id: str, rev: int):
        key = (map_id, rev)
        if key not in _grids:
            _grids[key] = mb.load(app.config["MAPS_DIR"], map_id, rev)
        return _grids[key]

    # ---- pages -------------------------------------------------------------------

    @app.get("/")
    def index():
        return redirect("/maps")

    @app.get("/maps")
    def page_maps():
        return render_template("maps.html", page="maps")

    @app.get("/editor")
    def page_editor():
        return render_template("editor.html", page="editor")

    @app.get("/run")
    def page_run():
        return render_template("run.html", page="run")

    # ---- state -------------------------------------------------------------------

    @app.get("/api/state")
    def api_state():
        return jsonify(adapter.state())

    @app.get("/api/footprint")
    def api_footprint():
        return jsonify({"polygon": list(fp.polygon), "margin_m": fp.margin_m, "reach_m": fp.reach_m})

    # ---- maps ----------------------------------------------------------------------

    @app.get("/api/maps")
    def api_maps():
        maps_dir = app.config["MAPS_DIR"]
        out = []
        if os.path.isdir(maps_dir):
            for map_id in sorted(os.listdir(maps_dir)):
                revs = mb.list_revisions(maps_dir, map_id)
                if not revs:
                    continue
                items = []
                for r in revs:
                    try:
                        m, _ = bundle(map_id, r)
                    except mb.BundleError as e:
                        items.append({"revision": r, "error": str(e)})
                        continue
                    items.append(
                        {
                            "revision": r,
                            "sha256": m.sha256,
                            "created": m.created,
                            "width": m.width,
                            "height": m.height,
                            "resolution": m.resolution,
                            "origin": m.origin,
                            "start": m.start,
                            "review": m.review,
                            "routes": store.list_routes(maps_dir, map_id),
                        }
                    )
                out.append({"map_id": map_id, "revisions": items})
        return jsonify(out)

    @app.get("/api/maps/<map_id>/<int:rev>")
    def api_map(map_id: str, rev: int):
        try:
            m, g = bundle(map_id, rev)
        except mb.BundleError as e:
            return _result(False, str(e), 404)
        return jsonify(
            {
                "map_id": map_id,
                "revision": rev,
                "sha256": m.sha256,
                "width": g.width,
                "height": g.height,
                "resolution": g.meta.resolution,
                "origin": [g.meta.origin_x, g.meta.origin_y, g.meta.origin_yaw],
                "start": m.start,
                "routes": store.list_routes(app.config["MAPS_DIR"], map_id),
            }
        )

    @app.get("/api/maps/<map_id>/<int:rev>/image.png")
    def api_map_image(map_id: str, rev: int):
        try:
            _, g = bundle(map_id, rev)
        except mb.BundleError as e:
            return _result(False, str(e), 404)
        img = np.full(g.data.shape, 205, dtype=np.uint8)
        img[g.data == 0] = 254
        img[g.data >= 65] = 0
        png = encode_gray(np.flipud(img))  # row 0 = bottom in the grid, top in the image
        return Response(png, mimetype="image/png", headers={"Cache-Control": "max-age=3600"})

    # ---- routes --------------------------------------------------------------------

    def _validate_payload(map_id: str, rev: int, payload: dict):
        m, g = bundle(map_id, rev)
        route = Route.from_dict(payload)
        route.map.id, route.map.revision, route.map.sha256 = map_id, rev, m.sha256
        keepout = load_keepout(mb.revision_dir(app.config["MAPS_DIR"], map_id, rev))
        return route, validate(route, m, g, fp, keepout)

    def _compiled_dict(compiled) -> dict:
        return {
            "total_length_m": compiled.total_length_m,
            "total_turn_deg": float(np.degrees(compiled.total_turn_rad)),
            "closes": compiled.closes,
            "end": list(compiled.end),
            "steps": [
                {
                    "id": s.id,
                    "type": s.type,
                    "start": list(s.start),
                    "end": list(s.end),
                    "length_m": s.length_m,
                    "signed_angle_deg": float(np.degrees(s.signed_angle_rad)),
                    "duration_est_s": s.duration_est_s,
                }
                for s in compiled.steps
            ],
        }

    @app.post("/api/maps/<map_id>/<int:rev>/routes/validate")
    def api_route_validate(map_id: str, rev: int):
        try:
            route, v = _validate_payload(map_id, rev, request.get_json(force=True) or {})
        except mb.BundleError as e:
            return _result(False, str(e), 404)
        except RouteError as e:
            return jsonify(
                {"ok": False, "issues": [{"code": "schema", "message": str(e), "step_id": e.step_id}]}
            ), 422
        if v.ok:
            adapter.publish_route_preview(v.compiled, route.frame_id)
        body = {"ok": v.ok, "issues": [i.to_dict() for i in v.issues], "route": route.to_dict()}
        if v.compiled is not None:
            body["compiled"] = _compiled_dict(v.compiled)
        return jsonify(body), (200 if v.ok else 422)

    @app.post("/api/maps/<map_id>/<int:rev>/routes/save")
    def api_route_save(map_id: str, rev: int):
        try:
            route, v = _validate_payload(map_id, rev, request.get_json(force=True) or {})
        except mb.BundleError as e:
            return _result(False, str(e), 404)
        except RouteError as e:
            return jsonify(
                {"ok": False, "issues": [{"code": "schema", "message": str(e), "step_id": e.step_id}]}
            ), 422
        if not v.ok:
            return jsonify({"ok": False, "issues": [i.to_dict() for i in v.issues]}), 422
        revision, path, sha = store.save_route(app.config["MAPS_DIR"], route)
        return jsonify(
            {"ok": True, "route_id": route.route_id, "revision": revision, "sha256": sha, "path": path}
        )

    @app.get("/api/maps/<map_id>/<int:rev>/routes/<route_id>/<int:rrev>")
    def api_route_get(map_id: str, rev: int, route_id: str, rrev: int):
        try:
            route, sha = store.load_route(app.config["MAPS_DIR"], map_id, route_id, rrev)
            m, g = bundle(map_id, rev)
        except (store.StoreError, mb.BundleError) as e:
            return _result(False, str(e), 404)
        v = validate(route, m, g, fp, load_keepout(mb.revision_dir(app.config["MAPS_DIR"], map_id, rev)))
        body = {
            "route": route.to_dict(),
            "sha256": sha,
            "ok": v.ok,
            "issues": [i.to_dict() for i in v.issues],
        }
        if v.compiled is not None:
            body["compiled"] = _compiled_dict(v.compiled)
            if v.ok:
                adapter.publish_route_preview(v.compiled, route.frame_id)
        return jsonify(body)

    # ---- missions ------------------------------------------------------------------

    @app.get("/api/missions")
    def api_missions():
        return jsonify(store.list_missions(app.config["MAPS_DIR"]))

    @app.post("/api/missions")
    def api_mission_create():
        d = request.get_json(force=True) or {}
        try:
            map_id, rev = str(d["map_id"]), int(d["map_revision"])
            route_id, rrev = str(d["route_id"]), int(d["route_revision"])
            m, g = bundle(map_id, rev)
            route, sha = store.load_route(app.config["MAPS_DIR"], map_id, route_id, rrev)
        except (KeyError, ValueError, TypeError):
            return _result(False, "map_id, map_revision, route_id, route_revision required", 400)
        except (store.StoreError, mb.BundleError) as e:
            return _result(False, str(e), 404)
        v = validate(route, m, g, fp, load_keepout(mb.revision_dir(app.config["MAPS_DIR"], map_id, rev)))
        if not v.ok:
            return jsonify({"ok": False, "issues": [i.to_dict() for i in v.issues]}), 422
        mission_id = str(d.get("mission_id") or f"{route_id}_rev{rrev}")
        try:
            path = store.save_mission(
                app.config["MAPS_DIR"], mission_id, map_id, rev, m.sha256, route_id, rrev, sha
            )
        except store.StoreError as e:
            return _result(False, str(e), 400)
        return jsonify({"ok": True, "mission_id": mission_id, "path": path})

    # ---- coordinator calls (services on the robot; the browser never commands wheels) ----

    def _call(fn, *args):
        ok, msg = fn(*args)
        return _result(ok, msg)

    @app.post("/api/survey/start")
    def api_survey_start():
        d = request.get_json(force=True) or {}
        return _call(adapter.survey_start, str(d.get("map_id", "")), str(d.get("description", "")))

    @app.post("/api/survey/returned")
    def api_survey_returned():
        return _call(adapter.survey_returned)

    @app.post("/api/survey/save")
    def api_survey_save():
        d = request.get_json(force=True) or {}
        return _call(adapter.survey_save, str(d.get("note", "")))

    @app.post("/api/survey/abort")
    def api_survey_abort():
        return _call(adapter.survey_abort)

    @app.post("/api/localization/confirm")
    def api_loc_confirm():
        return _call(adapter.localization_confirm)

    @app.post("/api/localization/reset")
    def api_loc_reset():
        return _call(adapter.localization_reset)

    @app.post("/api/localization/initialpose")
    def api_loc_initialpose():
        d = request.get_json(force=True) or {}
        try:
            x, y, yaw = float(d["x_m"]), float(d["y_m"]), float(d["yaw_rad"])
        except (KeyError, ValueError, TypeError):
            return _result(False, "x_m, y_m, yaw_rad required", 400)
        return _call(adapter.set_initial_pose, x, y, yaw)

    @app.post("/api/mission/run")
    def api_mission_run():
        d = request.get_json(force=True) or {}
        return _call(adapter.run_mission, str(d.get("mission_id", "")))

    @app.post("/api/mission/pause")
    def api_mission_pause():
        return _call(adapter.pause)

    @app.post("/api/mission/abort")
    def api_mission_abort():
        return _call(adapter.abort)

    @app.post("/api/mission/resume")
    def api_mission_resume():
        return _call(adapter.prepare_resume)

    @app.post("/api/mission/ack")
    def api_mission_ack():
        return _call(adapter.ack_fault)

    return app
