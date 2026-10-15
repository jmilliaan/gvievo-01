"""Flask app for the operator pages (spec §1.2, §6.3; unified plan §6). Framework-
independent of ROS: everything ROS goes through an `Adapter` object so the app is
testable with a stub.

aop-demo-oct: a manual-only vehicle with no DIO island. The web app is the panel:
/api/arm powers or unpowers the drives (amr_base/web_panel_node, default disarmed)
and the Manual page jogs. No tracked or trackless runs, maps, I/O or commissioning.

One endpoint publishes a velocity: /api/manual/refresh, one ManualCommand per
accepted request, held not latched (unified plan §6.3) - the mux accepts it only
with a fresh supervisor lease, and it expires 0.2 s after it was sent.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import traceback
import uuid
from typing import Any, Protocol

from agv_core import alarms as catalogue
from flask import Flask, Response, jsonify, redirect, render_template, request, session

from amr_navigation import footprint as fpmod
from amr_web import alarms as alarmview
from amr_web import demo as demomod
from amr_web import jog, netcheck, reports, wifi
from amr_web import role as rolemod


class Adapter(Protocol):
    """What the pages need from ROS. `amr_web.adapter.RosAdapter` implements it."""

    def state(self) -> dict[str, Any]: ...
    def ack_fault(self) -> tuple[bool, str]: ...
    # supervisor (unified plan §4.2, §6.2)
    def supervisor_identity(self) -> tuple[str, int]: ...
    def recover(self) -> tuple[bool, str]: ...
    def manual_publish(self, cmd) -> None: ...
    # diagnostics (unified plan §7): snapshots only; a GET never causes bus/Modbus traffic
    def diagnostics(self) -> dict: ...
    def events(self, since: int = 0) -> list[dict]: ...
    def emit(self, level: str, code: str, text: str, source: str = "amr_web") -> None: ...
    # aop-demo-oct: the web app arms the drives (web_panel_node /amr/panel/arm)
    def set_arm(self, arm: bool) -> tuple[bool, str]: ...


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


def _demo_zones() -> list[dict]:
    """The scanner's fields for the demo radar, from amr_bringup's scanner_fields.yaml (the file
    base.launch gives the mux). Read as a file: amr_bringup exec_depends on amr_web, so importing
    amr_bringup.scanner_fields here would be a dependency cycle. No file, no zones."""
    try:
        import yaml  # noqa: PLC0415
        from ament_index_python.packages import get_package_share_directory  # noqa: PLC0415

        path = os.path.join(get_package_share_directory("amr_bringup"), "config", "scanner_fields.yaml")
        with open(path, encoding="utf-8") as fh:
            return demomod.zones(yaml.safe_load(fh))
    except Exception:  # noqa: BLE001 - a dev box without the bringup share: the radar draws no zones
        return []


def create_app(
    adapter: Adapter,
    maps_dir: str,
    footprint_path: str | None = None,
    wifi_iface: str = "wlp1s0",
    state_dir: str = "~/.amr",
    internet_probe: netcheck.InternetProbe | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
    app.config["MAPS_DIR"] = os.path.expanduser(maps_dir)
    app.config["STATE_DIR"] = os.path.expanduser(state_dir)
    # Session cookie carries the role only. The PIN never leaves the server.
    app.secret_key = rolemod.secret(state_dir)
    standing = alarmview.StandingTracker()
    fp = fpmod.load(footprint_path or fpmod.default_path())
    app.config["FOOTPRINT"] = fp
    # ---- pages -------------------------------------------------------------------

    def _role() -> str:
        # Default is the engineer view (2026-10-02, commissioning); operator only once chosen.
        return rolemod.OPERATOR if session.get("role") == rolemod.OPERATOR else rolemod.ENGINEER

    @app.context_processor
    def _inject_role():
        """Every template knows the role, so base.html can show the operator's tabs or the
        engineer's without a second request."""
        return {"role": _role(), "OPERATOR": rolemod.OPERATOR, "ENGINEER": rolemod.ENGINEER}

    @app.get("/")
    def index():
        # The demo is the landing page on start (2026-10-15): the kiosk opens / (through nginx,
        # whose "starting" page refreshes / until the app answers) and so does the tablet.
        return redirect("/demo")

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

    @app.get("/alarms")
    def page_alarms():
        return render_template("alarms.html", page="alarms")

    @app.get("/params")
    def page_params():
        return render_template("params.html", page="params")

    @app.get("/manual")
    def page_manual():
        return render_template("manual.html", page="manual")

    # Maps and Routes live under Run trackless (2026-10-02): `page` lights that tab and
    # `sub` the strip inside it.
    # ---- state -------------------------------------------------------------------

    @app.get("/api/state")
    def api_state():
        return jsonify(adapter.state())

    # ---- DEMO page: visitors, not operators (manuals/plans/2026-09-23-demo-page.md) ----
    # The landing page since 2026-10-15 (the Demo tab leads back to it). Open to both roles,
    # read-only. Everything it may say is decided in demo.py.
    demo_path = os.path.join(app.static_folder or "", "demo", "content.json")
    try:
        with open(demo_path, encoding="utf-8") as fh:
            demo_content = json.load(fh)
    except (OSError, ValueError):
        demo_content = {"product": "AGV", "cards": [], "specs": []}  # the page must still serve
    demo_outline = [list(p) for p in fp.polygon]
    try:
        demo_near_m = float(demo_content.get("near_m", demomod.NEAR_M))
    except (TypeError, ValueError):
        demo_near_m = demomod.NEAR_M
    demo_zones = _demo_zones()

    @app.get("/demo")
    def page_demo():
        return render_template(
            "demo.html", c=demo_content, outline=demo_outline, zones=demo_zones, view_m=demomod.RADAR_M
        )

    @app.get("/api/demo")
    def api_demo():
        # The body-frame scan first: it needs no odometry, so the radar shows with the drives
        # off or faulted. The odometry-projected one is the fallback (and the offline demo server).
        ps = None
        if hasattr(adapter, "live"):
            body = getattr(adapter.live, "body_pose_scan", None)
            ps = (body() if body else None) or adapter.live.pose_scan()
        return jsonify(demomod.view(ps, fp.polygon, demo_near_m))

    wifi_reader = wifi.WifiReader(wifi_iface)

    @app.get("/api/wifi")
    def api_wifi():
        return jsonify(wifi_reader.read())

    # the robot's own internet reachability (header indicator); probes at most once per 4 s
    internet = internet_probe or netcheck.InternetProbe()

    @app.get("/api/internet")
    def api_internet():
        return jsonify(internet.read())

    @app.get("/api/footprint")
    def api_footprint():
        return jsonify({"polygon": list(fp.polygon), "margin_m": fp.margin_m, "reach_m": fp.reach_m})

    # ---- coordinator calls (services on the robot; the browser never commands wheels) ----

    def _call(fn, *args):
        ok, msg = fn(*args)
        return _result(ok, msg)

    # ---- diagnostics (unified plan §7): owner snapshots, never a second CAN/Modbus client ----

    @app.get("/api/diagnostics")
    def api_diagnostics():
        return jsonify(adapter.diagnostics() if hasattr(adapter, "diagnostics") else {})

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

    # ---- live view (unified plan §6.4): the pose and scan, for the Manual page's radar ----

    @app.get("/api/live/pose")
    def api_live_pose():
        if not hasattr(adapter, "live"):
            return jsonify({"generation": 0, "pose": None, "scan": None})
        return jsonify(adapter.live.pose_scan())

    @app.post("/api/recover")
    def api_recover():
        return _call(adapter.recover)

    # ---- drive power (aop-demo-oct): the web app is the panel's Manual Arm ----

    @app.post("/api/arm")
    def api_arm():
        """{"arm": true} powers the drives at zero, {"arm": false} unpowers them. Arming
        moves nothing: a jog still needs a held button. Refused while the drives are
        faulted or silent (web_panel_node), and dropped by a drive fault."""
        d, err = _body()
        if err:
            return err
        arm = d.get("arm")
        if not isinstance(arm, bool):
            return _result(False, "arm must be true or false", 400)
        if not arm:
            # Stop any jog first: disarming under a held button would be a coast, not a stop.
            inst, gen = adapter.supervisor_identity()
            with jog_lock:
                sessions.invalidate_all()
                adapter.manual_publish(jog.Command(inst, gen, "", 0, 0.0, 0.0, 0.0, "", 0.0))
        return _call(adapter.set_arm, arm)

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
        if run_state in ("READY", "EXECUTING", "PAUSED", "BLOCKED"):
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
