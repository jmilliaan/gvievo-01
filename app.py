"""Flask front end for the AGV: a manual jog pad and an auto (line-follow) page.

Read the safety model before changing anything here:

  * Nothing moves until the page POSTs /api/arm, which runs the same preflight
    drive_forward.py does (error register clear, Remote bit set, no FAULT).
  * A manual direction is HELD, not latched. The browser re-POSTs /api/drive
    about every 100 ms while the button or key is down; the bus thread zeros
    the setpoint if it misses three in a row. Closing the tab, losing Wi-Fi and
    letting go all look the same to the AGV, which is the point.
  * Auto is latched but still watchdogged - the page's telemetry poll doubles
    as its heartbeat, so a dead page stops the run.
"""
import os
import sys

from flask import Flask, jsonify, render_template, request

# This file lives at the repo root, so this puts the repo root itself on the
# path. That makes `python3 app.py`, `python3 /home/.../agv_can/app.py` from a
# systemd unit, and an import from any cwd all resolve the same modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Flat imports: motion.py and canworker.py are siblings of this file. templates/
# and static/ are siblings too, which is exactly where Flask looks by default.
import autopilot  # noqa: E402
import config  # noqa: E402
import events  # noqa: E402
import motion  # noqa: E402
from canworker import Controller  # noqa: E402

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
        watchdog_ms=int(config.MANUAL_WATCHDOG_S * 1000))


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
    ctl.keepalive()          # the auto page's poll is also its heartbeat
    return jsonify(ctl.snapshot())


@app.post("/api/preflight")
def api_preflight():
    try:
        return jsonify(ctl.submit("preflight"))
    except Exception as e:
        return _fail(e)


@app.post("/api/arm")
def api_arm():
    mode = (request.json or {}).get("mode", "manual")
    if mode not in ("manual", "auto"):
        return _fail(f"bad mode {mode!r}", 400)
    try:
        return jsonify(ctl.submit("arm", mode))
    except Exception as e:
        return _fail(e)


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


@app.post("/api/auto/run")
def api_auto_run():
    running = bool((request.json or {}).get("run", False))
    try:
        return jsonify(ctl.submit("auto_run", running))
    except Exception as e:
        return _fail(e)


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
