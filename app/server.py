"""Flask front end for the AGV: a manual jog pad and an auto (line-follow) page.

Read the safety model before changing anything here:

  * THE WEB APP CANNOT START THE VEHICLE. There is no /api/arm and no
    /api/auto/run: the physical panel owns entering every state (PB Reset arms
    in the selected mode, PB Start runs auto). The only thing here that can
    produce motion is /api/drive, and only while the vehicle is already armed
    in MANUAL - which only the panel can bring about.
  * A manual direction is HELD, not latched. The browser re-POSTs /api/drive
    about every 100 ms while the button or key is down; the bus thread zeros
    the setpoint if it misses three in a row. Closing the tab, losing Wi-Fi and
    letting go all look the same to the AGV, which is the point.
  * Everything else here only ever stops: /api/disarm de-energises and
    /api/stop zeroes the setpoint.
  * Auto is latched and watchdogged, but a panel-started run is held up by the
    DI scan rather than by this page's poll - see canworker._panel_scan().
"""
import os
import sys

from flask import Flask, jsonify, render_template, request

# This file lives in app/, so the repo root is its PARENT. Anchoring to the root
# rather than to this file is what makes `python3 main.py`, a systemd unit with
# an absolute path, and an import from any cwd all resolve the same modules.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("", "core", "drivers", os.path.join("drivers", "canbus")):
    sys.path.insert(0, os.path.join(_ROOT, _d) if _d else _ROOT)

# Bare imports throughout - see the note in canworker.py on why the layer
# directories go on sys.path instead of becoming packages. templates/ and
# static/ are siblings of THIS file, which is exactly where Flask looks.
import autopilot  # noqa: E402
import config  # noqa: E402
import events  # noqa: E402
import motion  # noqa: E402
from canworker import Controller  # noqa: E402

# guard holds the permitted/forbidden write lists from the monitoring plan's
# section 8; the monitor page displays them because an assessor will ask.
import guard  # noqa: E402

app = Flask(__name__)
ctl = Controller()


def _fail(msg, code=409):
    return jsonify({"ok": False, "error": str(msg)}), code


# ---- pages ----------------------------------------------------------------

@app.get("/")
def index():
    return manual()


@app.get("/manual")
def manual():
    return render_template(
        "manual.html", page="manual", pad=motion.PAD, labels=motion.LABELS,
        glyphs=motion.GLYPHS, keymap=motion.KEYMAP,
        table={d: motion.velocities(d) for d in motion.PAD},
        full=config.MANUAL_FULL_RPM, half=config.MANUAL_HALF_RPM,
        rfid_ip=f"{config.RFID_IP}:{config.RFID_PORT}",
        watchdog_ms=int(config.MANUAL_WATCHDOG_S * 1000))


@app.get("/monitor")
def monitor():
    return render_template(
        "monitor.html", page="monitor",
        heartbeat_ms=config.CAN_HEARTBEAT_MS,
        bitrate_kbps=config.CAN_BITRATE // 1000,
        nodes={str(n): config.NODES[n] for n in config.NODES},
        allowed=sorted(f"{i:04X}h" for i in guard.ALLOWED),
        scan_period_s=config.LOOP_PERIOD_S,
        forbidden=sorted(f"{i:04X}h" for i in guard.FORBIDDEN))


@app.get("/io")
def io():
    """Digital I/O lamps. Read-only: nothing here can energise an output."""
    return render_template(
        "io.html", page="io",
        di_names=config.DIO_DI_NAMES, do_names=config.DIO_DO_NAMES,
        dio_ip=f"{config.DIO_IP}:{config.DIO_PORT}",
        scan_hz=round(1.0 / config.DIO_SCAN_PERIOD_S))


@app.get("/lidar")
def lidar():
    """Safety-lidar data output. Read-only, and explicitly NOT a safety path."""
    return render_template(
        "lidar.html", page="lidar",
        sensor_ip=config.LIDAR_SENSOR_IP, host_ip=config.LIDAR_HOST_IP,
        port=config.LIDAR_PORT,
        scan_hz=round(1.0 / config.LIDAR_SCAN_CYCLE_S),
        decimate=config.LIDAR_DECIMATE,
        zones_validated=config.LIDAR_ZONES_VALIDATED,
        protective_m=2.15, warning_m=10.0, range_m=40.0)


@app.get("/alarms")
def alarms():
    """The event log and everything standing against the vehicle right now.

    Read-only. Notably it cannot CLEAR anything: a latched fault is cleared at
    the panel with Reset, by somebody who can see the vehicle.
    """
    return render_template("alarms.html", page="alarms",
                           max_events=events.MAX_EVENTS)


@app.get("/params")
def params():
    """Every tunable the vehicle is running on. Read-only, and unavoidably so:
    there is no endpoint here that writes a profile, because a parameter that
    can be changed from a browser is a parameter that can be changed while
    somebody is standing next to the vehicle. A profile is edited in the JSON
    and the service is restarted, which is also what makes the value on this
    page the value the bus thread is actually using.

    The content is generated from config's schema rather than listed here - see
    config.describe(). A hand-written list would be a second copy of the
    profile format, and the copy that goes stale is the one on the screen.
    """
    return render_template(
        "params.html", page="params",
        sections=config.describe(),
        profile=config.PROFILE_NAME, path=config.PROFILE_PATH_LOADED,
        env_var=config.PROFILE_ENV_VAR,
        zeta=f"{autopilot.predicted_zeta():.2f}",
        enabled=[(name, config.__dict__[f"{name.upper()}_ENABLED"])
                 for name in ("dio", "panel", "rfid", "lidar", "monitor")],
        dry_run=config.DRY_RUN)


@app.get("/auto")
def auto():
    return render_template("auto.html", page="auto",
                           auto_rpm=int(config.AUTO_RPM),
                           k_ratio=config.K_RATIO, kd=config.KD,
                           zeta=f"{autopilot.predicted_zeta():.2f}",
                           dry_run=config.DRY_RUN,
                           watchdog_ms=int(config.AUTO_WATCHDOG_S * 1000))


# ---- api ------------------------------------------------------------------

@app.get("/api/state")
def api_state():
    """Vehicle state. ?hb=1 ALSO refreshes the auto watchdog.

    The heartbeat is opt-in, and that is the safety-relevant part. It used to
    be unconditional, which meant any page polling this fed the watchdog - so a
    monitoring page open on a second screen would hold an auto run alive after
    the auto page had been closed. Now only the page driving the run claims it.

    Fail-safe in the right direction: a page that forgets the flag loses its
    heartbeat and the run stops, rather than a bystander silently holding it
    open.
    """
    if request.args.get("hb") == "1":
        ctl.keepalive()
    return jsonify(ctl.snapshot())


@app.post("/api/preflight")
def api_preflight():
    try:
        return jsonify(ctl.submit("preflight"))
    except Exception as e:
        return _fail(e)


# There is deliberately no /api/arm and no /api/auto/run.
#
# The web app may not put the vehicle into motion by any route except the manual
# jog arrows below, and only while it is already armed in manual. Arming and
# starting an auto run belong to the physical panel - PB Reset arms, PB Start
# runs - so a browser left open on a bench cannot move a 150 kg vehicle.
#
# What remains here only ever STOPS: disarm de-energises, stop zeroes the
# setpoint, and drive is a dead-man that the operator must keep holding.
@app.post("/api/disarm")
def api_disarm():
    try:
        return jsonify(ctl.submit("disarm"))
    except Exception as e:
        return _fail(e)


@app.post("/api/drive")
def api_drive():
    direction = (request.json or {}).get("dir", "stop")
    try:
        ctl.drive(direction)
    except Exception as e:
        return _fail(e)
    return jsonify({"ok": True, "dir": direction})


@app.post("/api/stop")
def api_stop():
    ctl.halt()
    return jsonify({"ok": True})


@app.get("/api/events")
def api_events():
    """Operator events newer than ?since=<seq>. since=0 returns the whole ring.

    Polled only when /api/state reports an event_seq ahead of what the page
    holds, so a quiet vehicle costs nothing.
    """
    try:
        since = int(request.args.get("since", 0))
    except (TypeError, ValueError):
        since = 0
    latest, items = events.since(since)
    return jsonify({"seq": latest, "events": items})


@app.get("/api/can")
def api_can():
    """Drive monitoring detail. Read-only, and deliberately does NOT keepalive.

    Split from /api/state so a monitoring page can poll as often as it likes
    without touching the auto watchdog.
    """
    snap = ctl.snapshot()
    return jsonify({
        "can": snap.get("can"),
        "nodes": snap.get("nodes"),
        "health": snap.get("health"),
        "connected": snap.get("connected"),
        "how": snap.get("how"),
        "error": snap.get("error"),
    })


@app.get("/api/lidar")
def api_lidar():
    """The decimated point cloud. Read-only, and deliberately does NOT keepalive.

    Split from /api/state for the same reason /api/can is: this is polled by one
    page several times a second and carries far more than a status line, and no
    amount of looking at a picture should hold an auto run alive.

    GET only, and there is no counterpart that writes. The scanner is read-only
    business - see drivers/lidar.py.
    """
    return jsonify(ctl.lidar_cloud())


@app.get("/api/config")
def api_config():
    return jsonify({
        "profile": config.PROFILE_NAME,
        "profile_path": config.PROFILE_PATH_LOADED,
        "full_rpm": config.MANUAL_FULL_RPM, "half_rpm": config.MANUAL_HALF_RPM,
        "auto_rpm": config.AUTO_RPM,
        "driver_ramp": config.RAMP,   # 6083h/6084h, per mode
        "manual_watchdog_ms": int(config.MANUAL_WATCHDOG_S * 1000),
        "auto_watchdog_ms": int(config.AUTO_WATCHDOG_S * 1000),
        "invert_left": config.INVERT_LEFT, "invert_right": config.INVERT_RIGHT,
        "table": {d: motion.velocities(d) for d in motion.PAD},
        "autopilot": {
            "dry_run": config.DRY_RUN, "invert_error": config.INVERT_ERROR,
            "k_ratio": config.K_RATIO, "kd": config.KD, "ki": config.KI,
            "tau_d_s": config.TAU_D_S, "auto_rpm": config.AUTO_RPM,
            "zeta": round(autopilot.predicted_zeta(), 4),
            "ramp_accel": config.RAMP_ACCEL_RPM_S,
            "line_loss_grace_m": config.LINE_LOSS_GRACE_M,
        },
    })


def main():
    """Entry point for both the shell and the agv_controller systemd unit.

    *** THIS MOVES HARDWARE, and it has no authentication. *** Anyone who can
    reach the port can drive the AGV. Keep it on a trusted network.

    The CAN bus is opened once, on a dedicated thread, when the server starts -
    see canworker.py for why nothing else is allowed to touch it.
    """
    import argparse

    ap = argparse.ArgumentParser(
        description=main.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true",
                    help="Flask autoreload. Off by default: a reload would open "
                         "can0 twice and orphan an armed driver.")
    args = ap.parse_args()

    ctl.start()
    print(f"AGV web UI on http://{args.host}:{args.port}/  "
          f"(manual: /manual, auto: /auto)")
    try:
        app.run(host=args.host, port=args.port, debug=args.debug,
                use_reloader=args.debug, threaded=True)
    finally:
        # Reached via KeyboardInterrupt, which is why the unit sends SIGINT
        # rather than the default SIGTERM - see the service file.
        print("shutting down - de-energising motors")
        ctl.shutdown()


if __name__ == "__main__":
    sys.exit(main() or 0)
