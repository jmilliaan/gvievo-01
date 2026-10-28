"""Flask app for the operator pages (spec §1.2, §6.3; unified plan §6). Framework-
independent of ROS: everything ROS goes through an `Adapter` object so the app is
testable with a stub.

One endpoint publishes a velocity: /api/manual/refresh, one ManualCommand per
accepted request, held not latched (unified plan §6.3) - the mux accepts it only
under the physical selector MANUAL with a fresh supervisor lease, and it expires
0.2 s after it was sent. Everything else only selects, draws, validates, saves or
asks the supervisor / coordinators; the physical panel authorises motion.

Mode and survey operations are asynchronous: 202 + operation_id, then
GET /api/operations/<id> until it is terminal.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import threading
import time
import traceback
import uuid
from typing import Any, Protocol

import numpy as np
from agv_core import alarms as catalogue
from agv_core import paths
from flask import Flask, Response, jsonify, redirect, render_template, request, session

from amr_base.wire import MODE_IDLE, MODE_LINE, SURVEY_OPS
from amr_maps import grid as gridio
from amr_mission import map_bundle as mb
from amr_mission import survey_move as survey_movemod
from amr_web import alarms as alarmview
from amr_web import jog, netcheck, reports, tapegraph_view, wifi
from amr_web import role as rolemod
from amr_web.png import encode_gray


class Adapter(Protocol):
    """What the pages need from ROS. `amr_web.adapter.RosAdapter` implements it."""

    def state(self) -> dict[str, Any]: ...
    def survey_move(self, kind: str, value: float) -> tuple[bool, str]: ...
    def survey_move_stop(self) -> tuple[bool, str]: ...
    def localization_confirm(self) -> tuple[bool, str]: ...
    def localization_reset(self) -> tuple[bool, str]: ...
    def set_initial_pose(
        self, x: float, y: float, yaw: float, map_id: str, map_revision: int, generation: int, sha256: str
    ) -> tuple[bool, str]: ...
    def pause(self) -> tuple[bool, str]: ...
    def abort(self) -> tuple[bool, str]: ...
    def ack_fault(self) -> tuple[bool, str]: ...
    # supervisor (unified plan §4.2, §6.2)
    def supervisor_identity(self) -> tuple[str, int]: ...
    def request_mode(
        self, target: int, map_id: str, map_revision: int, request_id: str
    ) -> tuple[bool, str, str]: ...
    def survey_request(
        self, operation: int, map_id: str, description: str, request_id: str,
        cont: tuple[int, float, float, float] | None = None,
    ) -> tuple[bool, str, str]: ...
    def get_operation(self, operation_id: str) -> dict | None: ...
    def recover(self) -> tuple[bool, str]: ...
    def manual_publish(self, cmd) -> None: ...
    # diagnostics (unified plan §7): snapshots only; a GET never causes bus/Modbus traffic
    def diagnostics(self) -> dict: ...
    def io_image(self) -> dict | None: ...
    def events(self, since: int = 0) -> list[dict]: ...
    def emit(self, level: str, code: str, text: str, source: str = "amr_web") -> None: ...
    def event_log_files(self) -> list[str]: ...
    def manual_allowed(self) -> tuple[bool, str]: ...  # optional (hasattr): the demo has no lease
    live: Any  # live.LiveStore; optional (hasattr): the demo serves no live view
    # tape layer (2026-10-02): clear moves nothing; only physical Start runs (no arm, 2026-10-07)
    def line_clear(self) -> tuple[bool, str]: ...
    def line_mission(self, name: str, destination: str = "") -> tuple[bool, str]: ...
    def line_branch(self, side: str) -> tuple[bool, str]: ...
    def line_speed(self, level: str) -> tuple[bool, str]: ...
    def line_uturn(self, force: bool) -> tuple[bool, str]: ...
    def line_continue(self, arm: bool) -> tuple[bool, str]: ...
    def line_teach(self, action: str, arg: str = "") -> tuple[bool, str]: ...
    def line_at_home(self) -> tuple[bool, str]: ...
    # trips (tracked plan 4): calls and confirmations form and record; they move nothing
    def line_trip(self, action: str, arg: str = "") -> tuple[bool, str]: ...


def _result(ok: bool, message: str, status_fail: int = 409, **extra):
    body = {"ok": ok, "message": message, **extra}
    return jsonify(body), (200 if ok else status_fail)


def _body():
    """The request's JSON object, or (None, a 400 response).

    `request.get_json(force=True) or {}` let a truthy list, string or number
    through to `.get(...)` and the handler crashed with a 500 before touching
    the adapter (review 2026-09-21, F12). Shape is a 400 everywhere; an empty
    body is the empty object so "field required" checks answer for it.
    """
    raw = request.get_data()
    if not raw.strip():
        return {}, None
    d = request.get_json(force=True, silent=True)
    if d is None:
        return None, _result(False, "malformed JSON", 400)
    if not isinstance(d, dict):
        return None, _result(False, "a JSON object is required", 400)
    return d, None


def _finite(x, what: str) -> float:
    """A finite number field. Booleans are not numbers here."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise ValueError(f"{what} must be a finite number")
    return float(x)


def _positive_int(x, what: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x < 1:
        raise ValueError(f"{what} must be a positive integer")
    return x


def _continuable(m) -> bool:
    """A survey can continue only a revision that carries slam_toolbox's saved pose graph."""
    return not mb.missing_posegraph(m)


def create_app(
    adapter: Adapter,
    maps_dir: str,
    wifi_iface: str = "wlp1s0",
    state_dir: str | None = None,  # None: agv_core.paths
    internet_probe: netcheck.InternetProbe | None = None,
    product: str | None = None,  # tape | slam | both; None = the profile's `tracked`
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
    app.config["MAPS_DIR"] = os.path.expanduser(maps_dir)
    state_dir = state_dir or paths.state_dir()
    app.config["STATE_DIR"] = os.path.expanduser(state_dir)
    # Session cookie carries the role only. The PIN never leaves the server.
    app.secret_key = rolemod.secret(state_dir)
    standing = alarmview.StandingTracker()
    _grids: dict[tuple[str, int], tuple[Any, gridio.Grid]] = {}

    def bundle(map_id: str, rev: int):
        key = (map_id, rev)
        if key not in _grids:
            _grids[key] = mb.load(app.config["MAPS_DIR"], map_id, rev)
        return _grids[key]

    # ---- pages -------------------------------------------------------------------

    def _role() -> str:
        # Default is the engineer view (2026-10-02); operator only once chosen.
        return rolemod.OPERATOR if session.get("role") == rolemod.OPERATOR else rolemod.ENGINEER

    def _product() -> str:
        """The profile's `tracked`: tape | slam | both. A dev box without a profile is both."""
        try:
            from agv_core import config  # noqa: PLC0415

            return config.product()
        except Exception:  # noqa: BLE001
            return "both"

    product = product or _product()

    tracked_ok = product in ("tape", "both")
    trackless_ok = product in ("slam", "both")

    @app.context_processor
    def _inject_role():
        """Every template knows the role, so base.html can show the operator's three
        tabs or the engineer's ten without a second request - and the product, so a
        tab for the other product is not offered at all."""
        return {"role": _role(), "OPERATOR": rolemod.OPERATOR, "ENGINEER": rolemod.ENGINEER,
                "product": product, "tracked_ok": tracked_ok, "trackless_ok": trackless_ok,
                "fresh_s": alarmview.FRESH_S, "jog_consts": jog.page_constants()}

    def _engineer_only(what: str):
        """A 403 for the operator role ("<what> the engineer view (PIN)"), None for the engineer.
        Checked before the body is read, so a refusal never depends on what was sent."""
        if _role() != rolemod.ENGINEER:
            return _result(False, f"{what} the engineer view (PIN)", 403)
        return None

    def _need(ok: bool):
        """A page or API of the other product is 404, not hidden (dual-product plan Inc. 4)."""
        if not ok:
            from flask import abort  # noqa: PLC0415

            abort(404)

    @app.get("/")
    def index():
        return redirect("/home")

    @app.get("/home")
    def page_home():
        return render_template("home.html", page="home")

    @app.post("/api/role")
    def api_role():
        """Switch role. To engineer: the PIN must match. Back to operator: always allowed
        (a mistake guard you cannot leave is a trap)."""
        d, err = _body()
        if err:
            return err
        want = str(d.get("role", "")).lower()
        if want == rolemod.OPERATOR:
            session["role"] = rolemod.OPERATOR
            return jsonify({"ok": True, "role": rolemod.OPERATOR, "message": "operator view"})
        if want != rolemod.ENGINEER:
            return _result(False, "role must be operator or engineer", 400)
        if not rolemod.check(app.config["STATE_DIR"], str(d.get("pin", ""))):
            return _result(False, "wrong PIN", 403)
        session["role"] = rolemod.ENGINEER
        return jsonify({"ok": True, "role": rolemod.ENGINEER, "message": "engineer view"})

    @app.get("/api/role")
    def api_role_get():
        return jsonify({"role": _role()})

    @app.get("/monitor")
    def page_monitor():
        return render_template("monitor.html", page="monitor")

    @app.get("/io")
    def page_io():
        return render_template("io.html", page="io")

    @app.get("/alarms")
    def page_alarms():
        return render_template("alarms.html", page="alarms")

    @app.get("/params")
    def page_params():
        return render_template("params.html", page="params")

    @app.get("/manual")
    def page_manual():
        return render_template("manual.html", page="manual")

    # MAPPING (2026-10-28): survey, continue a survey and the AMCL position on one page. Routes,
    # map area edits and trackless missions were removed with it; the vehicle's one map is the
    # tape-localization map. Old addresses redirect so a bookmark or the kiosk still lands.
    @app.get("/mapping")
    def page_mapping():
        _need(trackless_ok)
        return render_template("mapping.html", page="mapping", rotate_steps=survey_movemod.ROTATE_STEPS_DEG)

    @app.get("/maps")
    @app.get("/survey-continue")
    @app.get("/run-trackless")
    def page_mapping_old():
        _need(trackless_ok)
        return redirect("/mapping")

    # Run is the tape product (2026-10-28; "Run tracked" until then).
    @app.get("/run")
    def page_run():
        _need(tracked_ok)
        return render_template("run.html", page="run")

    @app.get("/run-tracked")
    def page_run_tracked_old():
        _need(tracked_ok)
        return redirect("/run")

    @app.get("/teach")
    def page_teach():
        _need(tracked_ok)
        return render_template("teach.html", page="teach")

    @app.get("/guide")
    def page_guide():
        _need(tracked_ok)
        return redirect("/teach")

    @app.get("/tape-areas")
    def page_tape_areas():
        """High-speed areas drawn on the teaching map (tracked plan 4, 2026-10-25). Engineer."""
        _need(tracked_ok)
        return render_template("tape_areas.html", page="teach")

    @app.post("/api/line/areas")
    def api_line_areas():
        """Save {"id", "polygon": [[x, y], ...]} or delete {"id", "delete": true} one area. Files
        only: a trip reads them at its Start. Engineer."""
        _need(tracked_ok)
        denied = _engineer_only("high-speed areas need")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        if d.get("delete") is True:
            ok, msg = tapegraph_view.save_area(app.config["STATE_DIR"], d.get("id"), None)
        else:
            ok, msg = tapegraph_view.save_area(app.config["STATE_DIR"], d.get("id"), d.get("polygon"))
        return _result(ok, msg, 422)

    @app.get("/calls")
    def page_calls():
        """Machine calls and the trip (tracked plan 4). Operator and engineer. Nothing on it starts
        the vehicle: a trip leaves HOME on AUTO + the physical Start."""
        _need(tracked_ok)
        return render_template("calls.html", page="calls")

    # ---- tape layer: mission choice and arm/clear. Nothing here moves the vehicle:
    # a run starts only on the physical Start under AUTO (line_follow_node). ----

    @app.get("/api/line/missions")
    def api_line_missions():
        _need(tracked_ok)
        from agv_core import mission as missions  # noqa: PLC0415

        # Each mission's destination stops, so the page can offer them as a list
        # rather than free text. A file that does not validate is listed with its
        # error: selecting it is refused by the layer anyway, with the same words.
        # notes: each mission's branch and speed rule, "empty" included (the "none" entry).
        names, dests, errors, notes = [], {}, {}, {}
        for n in missions.list_missions():
            try:
                m = missions.load(n)
            except missions.MissionError as e:
                m = None
                errors[n] = str(e)
            if m is not None:
                notes[n] = missions.summary(m)
            if n == "empty":
                continue
            names.append(n)
            if m is not None:
                dests[n] = missions.destinations(m)
        # The site mission is a job only with the live position engine (tracked plan 4).
        try:
            from agv_core import config  # noqa: PLC0415

            if config.TAPE_LOC_LIVE:
                site = config.TAPE_LOC_SITE_MISSION
                names.append(site)
                notes[site] = "trips from machine calls (Calls page), driven by position; Start at HOME"
        except Exception:  # noqa: BLE001 - a dev box without a profile
            pass
        return jsonify({"missions": names, "destinations": dests, "errors": errors, "notes": notes})

    @app.post("/api/line/mission")
    def api_line_mission():
        _need(tracked_ok)
        d, err = _body()
        if err:
            return err
        return _call(adapter.line_mission, str(d.get("name", "") or ""), str(d.get("destination", "") or ""))

    @app.post("/api/line/clear")
    def api_line_clear():
        _need(tracked_ok)
        return _call(adapter.line_clear)

    # ---- tape-graph localization (tracked plan 3, P1): teach and shadow. Nothing here
    # moves the vehicle: a teach pass is driven by AUTO + the physical Start or under MANUAL.

    @app.get("/api/line/site")
    def api_line_site():
        """The site mission's circuits and stations, for the Teach page's lists."""
        _need(tracked_ok)
        from agv_core import mission as missions  # noqa: PLC0415

        live = False
        try:
            from agv_core import config  # noqa: PLC0415

            name = config.TAPE_LOC_SITE_MISSION       # the one the line layer teaches and shadows
            live = bool(getattr(config, "TAPE_LOC_LIVE", False))
        except Exception:  # noqa: BLE001 - a dev box without a profile
            names = missions.list_site_missions()
            name = names[0] if names else ""
        try:
            m = missions.load_site(name)
        except missions.MissionError as e:
            return jsonify({"mission": name, "circuits": [], "stations": [], "points": [], "machines": {},
                            "live": live, "error": str(e)})
        # Machines per group in circuit order (their release / swap stop), for the Calls page.
        machines = {}
        for g, row in m["GROUPS"].items():
            stops = [it["id"] for it in m["CIRCUITS"][row["circuit"]]["items"] if it["kind"] == "stop"]
            first = {mc: min(stops.index(sid) for k, sid in act.items() if k != "uturn")
                     for mc, act in row["machines"].items()}
            machines[g] = sorted(row["machines"], key=lambda mc: (first[mc], mc))
        return jsonify({"mission": m["MISSION_NAME"], "circuits": sorted(m["CIRCUITS"]),
                        "stations": [m["HOME"], *[s for s in m["STATIONS"] if s != m["HOME"]]],
                        "points": list(m["POINTS"]), "machines": machines, "trip_calls": m["TRIP_CALLS"],
                        "home": m["HOME"], "live": live, "error": ""})

    @app.get("/api/line/graph")
    def api_line_graph():
        """The taught tape graph (or the newest pass), anchors, stations and marks for the map
        overlay. Files only, read-only, any role."""
        _need(tracked_ok)
        return jsonify(tapegraph_view.view(app.config["STATE_DIR"], app.config["MAPS_DIR"]))

    # Guided mission (2026-10-23): the engineer's branch order for the next fork. It chooses a
    # tape only; the run starts and resumes on AUTO + the physical Start (line_follow_node).
    @app.post("/api/line/branch")
    def api_line_branch():
        _need(tracked_ok)
        denied = _engineer_only("branch orders need")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        side = str(d.get("side", "") or "")
        if side not in ("left", "straight", "right"):
            return _result(False, "side must be left, straight or right", 422)
        return _call(adapter.line_branch, side)

    # Its speed toggle (2026-10-24): HIGH lets the mission's marker pair grant HIGH, NORMAL
    # ignores the zone codes. It never starts or resumes the run.
    @app.post("/api/line/speed")
    def api_line_speed():
        _need(tracked_ok)
        denied = _engineer_only("the speed toggle needs")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        level = str(d.get("level", "") or "")
        if level not in ("normal", "high"):
            return _result(False, "level must be normal or high", 422)
        return _call(adapter.line_speed, level)

    # Its forced U-turn (2026-10-24): the next tape end is the U-turn, strip or not. It changes
    # what a tape end means to the running job; it never starts or resumes the run.
    @app.post("/api/line/uturn")
    def api_line_uturn():
        _need(tracked_ok)
        denied = _engineer_only("the forced U-turn needs")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        force = d.get("force")
        if not isinstance(force, bool):
            return _result(False, "force must be true or false", 422)
        return _call(adapter.line_uturn, force)

    # And "continue this run on the next Start" after a "track lost" end. Moves nothing.
    @app.post("/api/line/continue")
    def api_line_continue():
        _need(tracked_ok)
        denied = _engineer_only("continuing a run needs")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        arm = d.get("arm")
        if not isinstance(arm, bool):
            return _result(False, "arm must be true or false", 422)
        return _call(adapter.line_continue, arm)

    @app.post("/api/line/teach")
    def api_line_teach():
        _need(tracked_ok)
        denied = _engineer_only("teaching needs")
        if denied:
            return denied
        d, err = _body()
        if err:
            return err
        return _call(adapter.line_teach, str(d.get("action", "") or ""), str(d.get("arg", "") or ""))

    # Trips (tracked plan 4): a machine calls, a call is cancelled, the operator confirms the
    # releases (before the U-turn) or the trolleys off at HOME. They form and record a trip;
    # it leaves HOME only on AUTO + the physical Start. Operator and engineer.
    TRIP_ACTIONS = ("call", "cancel", "confirm_released", "confirm_off", "status")

    @app.post("/api/line/trip")
    def api_line_trip():
        _need(tracked_ok)
        d, err = _body()
        if err:
            return err
        action, arg = str(d.get("action", "") or ""), str(d.get("arg", "") or "")
        if action not in TRIP_ACTIONS:
            return _result(False, f"action must be one of {', '.join(TRIP_ACTIONS)}", 422)
        if action in ("call", "cancel") and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", arg):
            return _result(False, "arg must be a machine name", 422)
        return _call(adapter.line_trip, action, arg if action in ("call", "cancel") else "")

    @app.post("/api/line/at_home")
    def api_line_at_home():
        _need(tracked_ok)
        return _call(adapter.line_at_home)

    # ---- state -------------------------------------------------------------------

    @app.get("/api/state")
    def api_state():
        return jsonify(adapter.state())

    wifi_reader = wifi.WifiReader(wifi_iface)

    @app.get("/api/wifi")
    def api_wifi():
        return jsonify(wifi_reader.read())

    # the robot's own internet reachability (header indicator); probes at most once per 4 s
    internet = internet_probe or netcheck.InternetProbe()

    @app.get("/api/internet")
    def api_internet():
        return jsonify(internet.read())

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
                    except (mb.BundleError, gridio.GridError) as e:
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
                            "continuable": _continuable(m),
                        }
                    )
                out.append({"map_id": map_id, "revisions": items})
        return jsonify(out)

    @app.get("/api/maps/<map_id>/<int:rev>")
    def api_map(map_id: str, rev: int):
        try:
            m, g = bundle(map_id, rev)
        except (mb.BundleError, gridio.GridError) as e:
            return _result(False, str(e), 404)
        return jsonify(
            {
                "map_id": map_id,
                "revision": rev,
                "sha256": m.sha256,
                **gridio.meta_dict(g),
                "start": m.start,
                "review": m.review,
                "continuable": _continuable(m),
            }
        )

    @app.get("/api/maps/<map_id>/<int:rev>/image.png")
    def api_map_image(map_id: str, rev: int):
        try:
            _, g = bundle(map_id, rev)
        except mb.BundleError as e:
            return _result(False, str(e), 404)
        png = encode_gray(np.flipud(gridio.trinary_image(g)))  # row 0 = bottom in the grid, top in the image
        return Response(png, mimetype="image/png", headers={"Cache-Control": "max-age=3600"})

    # ---- coordinator calls (services on the robot; the browser never commands wheels) ----

    def _call(fn, *args):
        ok, msg = fn(*args)
        return _result(ok, msg)

    # ---- diagnostics (unified plan §7): owner snapshots, never a second CAN/Modbus client ----

    @app.get("/api/diagnostics")
    def api_diagnostics():
        return jsonify(adapter.diagnostics() if hasattr(adapter, "diagnostics") else {})

    @app.get("/api/io")
    def api_io():
        return jsonify(adapter.io_image() if hasattr(adapter, "io_image") else None)

    @app.post("/api/page-error")
    def api_page_error():
        """A page script failed in the browser. Recorded as an event so a silent dead
        button becomes a line in the log instead of a shrug."""
        d, _ = _body()
        where = str((d or {}).get("where", "?"))[:120]
        what = str((d or {}).get("what", ""))[:300]
        adapter.emit("warn", "WEB_BUG", f"{where}: {what}")
        return jsonify({"ok": True})

    @app.get("/api/alarms")
    def api_alarms():
        """What is standing against the vehicle, worst first, with the action for each,
        plus the single line and single button the Home page shows. Computed here so no
        page has to re-derive it (and disagree)."""
        st = adapter.state()
        rows = standing.apply(alarmview.standing(st), time.time())
        return jsonify({"alarms": rows, "headline": alarmview.headline(st, rows)})

    @app.get("/api/events")
    def api_events():
        try:
            since = int(request.args.get("since", "0"))
        except ValueError:
            since = 0
        rows = adapter.events(since) if hasattr(adapter, "events") else []
        # The catalogue title travels with every event, so the history reads in the same
        # words as the standing list instead of in raw codes.
        return jsonify([dict(e, title=catalogue.get(e.get("code", "")).title) for e in rows])

    @app.get("/api/config")
    def api_config():
        """Effective configuration, read-only, with provenance: the strict vehicle
        profile (config.describe(), the same rows the legacy page showed) plus what
        the owners report they are actually running (from /diagnostics)."""

        from agv_core import config  # noqa: PLC0415

        diag = adapter.diagnostics() if hasattr(adapter, "diagnostics") else {}
        runtime = {k: v["values"] for k, v in diag.items() if k in ("can/bus", "imu/mls")}
        return jsonify(
            {
                "profile": config.PROFILE_NAME,
                "profile_path": config.PROFILE_PATH_LOADED,
                "sections": config.describe(),
                "runtime": runtime,
                "note": "profile = the vehicle profile; runtime = what the owning node reports it uses",
            }
        )

    # ---- live view (unified plan §6.4): bounded rates, encoded once per snapshot ----

    def _want_live():
        """Every live-view request keeps /scan and /tf subscribed (live.LIVE_IDLE_S)."""
        want = getattr(getattr(adapter, "live", None), "want", None)
        if want is not None:
            want()

    @app.get("/api/live/map")
    def api_live_map():
        _want_live()
        meta = adapter.live.map_meta() if hasattr(adapter, "live") else None
        if meta is None:
            return jsonify({"snapshot": 0, "available": False})
        return jsonify(dict(meta, available=True))

    @app.get("/api/live/map.png")
    def api_live_map_png():
        _want_live()
        try:
            snap = int(request.args.get("snapshot", "0"))
        except ValueError:
            return _result(False, "snapshot must be an integer", 400)
        png = adapter.live.map_png(snap) if hasattr(adapter, "live") else None
        if png is None:
            return _result(False, "no such live snapshot (a newer grid exists)", 404)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/live/pose")
    def api_live_pose():
        _want_live()
        if not hasattr(adapter, "live"):
            return jsonify({"generation": 0, "pose": None, "scan": None})
        return jsonify(adapter.live.pose_scan())

    # ---- supervisor operations: accepted (202) vs completed (poll /api/operations/<id>) ----

    def _accepted(accepted: bool, operation_id: str, message: str):
        if accepted:
            return jsonify({"ok": True, "operation_id": operation_id, "message": message}), 202
        status = 503 if "unavailable" in message else 409
        return jsonify({"ok": False, "operation_id": operation_id, "message": message}), status

    @app.post("/api/mode")
    def api_mode():
        d, err = _body()
        if err:
            return err
        # NAVIGATION is not entered from the web since 2026-10-28 (no routes, no trackless
        # missions); MAPPING is entered by a survey start.
        target = {"idle": MODE_IDLE, "line": MODE_LINE}.get(str(d.get("target", "")).lower())
        if target is None:
            return _result(False, "target must be idle or line", 400)
        rid = str(d.get("request_id") or uuid.uuid4().hex)
        return _accepted(*adapter.request_mode(target, "", 0, rid))

    @app.post("/api/survey/<op>")
    def api_survey(op: str):
        if op not in SURVEY_OPS:
            return _result(False, "unknown survey operation", 404)
        d, err = _body()
        if err:
            return err
        rid = str(d.get("request_id") or uuid.uuid4().hex)
        desc = str(d.get("description", d.get("note", "")))
        if op == "start" and d.get("continue_revision") not in (None, 0):
            # continue a saved survey: revision + where the vehicle stands on it. The
            # supervisor re-checks the bundle; the session matches the scan before loading.
            try:
                rev = _positive_int(d.get("continue_revision"), "continue_revision")
                h = d.get("hint")
                if not isinstance(h, dict):
                    raise ValueError("hint {x_m, y_m, yaw_rad} is required to continue a survey")
                hint = (_finite(h.get("x_m"), "hint.x_m"), _finite(h.get("y_m"), "hint.y_m"),
                        _finite(h.get("yaw_rad"), "hint.yaw_rad"))
            except ValueError as e:
                return _result(False, str(e), 422)
            return _accepted(*adapter.survey_request(
                SURVEY_OPS[op], str(d.get("map_id", "")), desc, rid, cont=(rev, *hint)))
        return _accepted(*adapter.survey_request(SURVEY_OPS[op], str(d.get("map_id", "")), desc, rid))

    # preset survey moves (press once): validated again by survey_move_node, which also checks
    # the MANUAL authority; a refused move answers 409 with the node's reason
    @app.post("/api/survey_move")
    def api_survey_move():
        d, err = _body()
        if err:
            return err
        kind = str(d.get("kind", ""))
        try:
            value = _finite(d.get("value"), "value")
        except ValueError as e:
            return _result(False, str(e), 422)
        if kind not in ("straight", "rotate"):
            return _result(False, "kind must be straight or rotate, value a finite number", 422)
        return _result(*adapter.survey_move(kind, value))

    @app.post("/api/survey_move/stop")
    def api_survey_move_stop():
        return _result(*adapter.survey_move_stop())

    @app.get("/api/operations/<operation_id>")
    def api_operation(operation_id: str):
        op = adapter.get_operation(operation_id)
        if op is None:
            return _result(False, "no such operation", 404)
        return jsonify(op)

    @app.post("/api/recover")
    def api_recover():
        # Owner decision 2026-10-25 (unified plan WP-B4): Recover - which also acknowledges a
        # drive-link fault after the power cycle - is the engineer's.
        denied = _engineer_only("Recover needs")
        if denied:
            return denied
        return _call(adapter.recover)

    # ---- manual jog (unified plan §6.3): the only endpoint that publishes a velocity ----

    sessions = jog.JogSessions(time.monotonic)
    jog_lock = threading.Lock()
    app.config["JOG"] = sessions

    def _jog_error(e: jog.JogError):
        return jsonify({"ok": False, "message": str(e)}), e.status

    @app.post("/api/manual/press")
    def api_manual_press():
        d, err = _body()
        if err:
            return err
        owner = str(d.get("owner", ""))[:64]
        if not owner:
            return _result(False, "owner token required", 400)
        inst, gen = adapter.supervisor_identity()
        if hasattr(adapter, "manual_allowed"):
            ok, why = adapter.manual_allowed()
            if not ok:
                return _result(False, why, 409)
        with jog_lock:
            try:
                s = sessions.press(owner, inst, gen)
            except jog.JogError as e:
                return _jog_error(e)
        return jsonify(
            {
                "ok": True,
                "session": s.id,
                "ticket": s.ticket,
                "generation": gen,
                "v_max": jog.V_MAX,
                "w_max": jog.W_MAX,
            }
        )

    @app.post("/api/manual/refresh")
    def api_manual_refresh():
        d, err = _body()
        if err:
            return err
        inst, gen = adapter.supervisor_identity()
        with jog_lock:
            try:
                cmd = sessions.refresh(
                    str(d.get("session", "")),
                    str(d.get("ticket", "")),
                    d.get("seq"),
                    d.get("v"),
                    d.get("w"),
                    inst,
                    gen,
                )
            except jog.JogError as e:
                return _jog_error(e)
            adapter.manual_publish(cmd)  # exactly one command per accepted request, under the lock
        return jsonify(
            {"ok": True, "ticket": cmd.ticket, "valid_for_s": cmd.valid_for_s, "v": cmd.v, "w": cmd.w}
        )

    @app.post("/api/manual/release")
    def api_manual_release():
        d, err = _body()
        if err:
            return err
        inst, gen = adapter.supervisor_identity()
        with jog_lock:
            had = sessions.release(str(d.get("session", "")))
            # The session is dead before this goes out. valid_for_s = 0 is a revocation at
            # the mux (gating.ManualIntake): terminal for the session whatever its seq, so
            # neither this zero nor a delayed refresh can lose to the sequence filter (R02).
            # Published under the lock so it cannot interleave with a refresh publication.
            adapter.manual_publish(
                jog.Command(inst, gen, str(d.get("session", "")), 0, 0.0, 0.0, 0.0, "", 0.0)
            )
        return jsonify({"ok": True, "released": had})

    @app.post("/api/stop")
    def api_stop():
        """Revoke this browser's manual session. During a route use pause/abort."""
        inst, gen = adapter.supervisor_identity()
        with jog_lock:
            sessions.invalidate_all()
            # empty session + valid_for_s 0: the mux drops whatever it holds
            adapter.manual_publish(jog.Command(inst, gen, "", 0, 0.0, 0.0, 0.0, "", 0.0))
        return jsonify({"ok": True, "message": "manual sessions revoked"})

    @app.post("/api/localization/confirm")
    def api_loc_confirm():
        return _call(adapter.localization_confirm)

    @app.post("/api/localization/reset")
    def api_loc_reset():
        return _call(adapter.localization_reset)

    @app.post("/api/localization/initialpose")
    def api_loc_initialpose():
        d, err = _body()
        if err:
            return err
        try:
            x, y, yaw = (_finite(d.get(k), k) for k in ("x_m", "y_m", "yaw_rad"))
            map_id = d.get("map_id")
            if not isinstance(map_id, str) or not map_id:
                raise ValueError("map_id must be text")
            map_rev = _positive_int(d.get("map_revision"), "map_revision")
            gen = d.get("generation")
            if isinstance(gen, bool) or not isinstance(gen, int) or gen < 0:
                raise ValueError("generation must be a non-negative integer")
        except ValueError as e:
            return _result(False, f"{e} (x_m, y_m, yaw_rad, map_id, map_revision, generation required)", 400)
        # the adapter re-checks the identity against the live ModeState right before publishing (R12)
        return _call(adapter.set_initial_pose, x, y, yaw, map_id, map_rev, gen, str(d.get("sha256", "")))

    @app.post("/api/mission/pause")
    def api_mission_pause():
        return _call(adapter.pause)

    @app.post("/api/mission/abort")
    def api_mission_abort():
        return _call(adapter.abort)

    @app.post("/api/mission/ack")
    def api_mission_ack():
        return _call(adapter.ack_fault)

    # ---- service control: the one button for a base the supervisor cannot rebuild ----

    @app.post("/api/service/restart")
    def api_service_restart():
        """Restart amr.service. The supervisor refuses Recover for a dead base (the drives
        must be re-armed), so without this the operator's only route is SSH. Refused while
        anything is moving or a run is live: this kills the layer and the drives with it.

        Needs a sudoers line (see RUNBOOK section 5); without it the call answers 501 and
        says so rather than pretending it worked."""
        st = adapter.state()
        mux = st.get("mux") or {}
        moving = max(abs(mux.get("left_rad_s") or 0.0), abs(mux.get("right_rad_s") or 0.0)) > 1e-3
        if moving:
            return _result(False, "the wheels are turning; stop the vehicle first", 409)
        run_state = (st.get("run") or {}).get("state_name")
        if run_state in alarmview.RUN_ACTIVE:
            return _result(False, f"a run is {run_state}; abort it first", 409)
        cmd = ["sudo", "-n", "systemctl", "restart", "amr.service"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)  # noqa: S603
        except FileNotFoundError:
            return _result(False, "systemctl is not available on this machine", 501)
        except subprocess.TimeoutExpired:
            # The restart kills this very process, so a timeout is the SUCCESS path.
            return jsonify({"ok": True, "message": "restarting; this page will reconnect"})
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:200]
            if "password" in detail or "not allowed" in detail:
                return _result(False, "not permitted: the sudoers line for amr.service is missing", 501)
            return _result(False, f"restart failed: {detail}", 500)
        adapter.emit("warn", "MODE_CHANGE", "service restart requested from the operator page")
        return jsonify({"ok": True, "message": "restarting; this page will reconnect"})

    # ---- reports: verbose on disk, short on screen ----

    @app.get("/api/reports")
    def api_reports():
        return jsonify(reports.listing(app.config["STATE_DIR"]))

    @app.post("/api/report")
    def api_report():
        d, _ = _body()
        note = str((d or {}).get("note", ""))
        try:
            name = reports.build(
                app.config["STATE_DIR"],
                state=adapter.state(),
                events=adapter.events(0),
                diagnostics=adapter.diagnostics() if hasattr(adapter, "diagnostics") else {},
                event_files=adapter.event_log_files() if hasattr(adapter, "event_log_files") else [],
                note=note,
            )
        except OSError as e:
            return _result(False, f"could not write the report: {e}", 500)
        adapter.emit("info", "MODE_CHANGE", f"report saved: {name}")
        return jsonify({"ok": True, "name": name, "message": f"saved {name}"})

    @app.get("/api/report/<name>")
    def api_report_get(name: str):
        path = reports.path_of(app.config["STATE_DIR"], name)
        if path is None:
            return _result(False, "no such report", 404)
        with open(path, "rb") as fh:
            body = fh.read()
        return Response(
            body,
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
        )

    # ---- error boundary: a bug answers JSON with a reference, never a stack trace ----

    @app.errorhandler(Exception)
    def _unhandled(e):
        from werkzeug.exceptions import HTTPException  # noqa: PLC0415

        if isinstance(e, HTTPException):
            return jsonify({"ok": False, "code": "HTTP", "message": e.description}), e.code
        ref = uuid.uuid4().hex[:8]
        app.logger.error("WEB_BUG %s on %s\n%s", ref, request.path, traceback.format_exc())
        try:
            adapter.emit("warn", "WEB_BUG", f"{request.path} failed (ref {ref})")
        except Exception:  # noqa: BLE001 - the error path must not raise
            pass
        body = {"ok": False, "code": "WEB_BUG", "ref": ref, "message": f"internal error (ref {ref})"}
        return jsonify(body), 500

    return app
