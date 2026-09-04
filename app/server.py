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
  * Everything else here only ever stops: /api/disarm de-energises, /api/stop
    zeroes the setpoint, and /api/restart de-energises and then ends the
    process. None of them can produce motion, and the last is refused outright
    while the vehicle is armed.
  * Auto is latched and watchdogged, but a panel-started run is held up by the
    DI scan rather than by this page's poll - see canworker._panel_scan().
"""
import os
import subprocess
import sys
import threading

from flask import Flask, jsonify, redirect, render_template, request

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
    """The bare address lands on /auto, which is the page a run is watched from.

    A redirect rather than rendering /auto here, so the address bar names the
    page it is showing and a bookmark of the landing page is a bookmark of /auto.

    *** /auto claims the auto watchdog *** (window.CLAIM_HEARTBEAT), so this
    also means a browser left on the bare address feeds it. That is deliberate -
    the landing page is the operator's page - but it is the reason a second
    screen should be parked on /monitor or /alarms, neither of which claims.
    """
    return redirect("/auto")


@app.get("/manual")
def manual():
    # No `table`, `full` or `half`: the pad no longer prints the 60FFh setpoints
    # under each arrow. They are still reported by /api/config, which is where
    # something reading them programmatically should look.
    return render_template(
        "manual.html", page="manual", pad=motion.PAD, labels=motion.LABELS,
        glyphs=motion.GLYPHS, keymap=motion.KEYMAP,
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
        sensor_ip=config.LIDAR_SENSOR_IP,
        scan_hz=round(1.0 / config.LIDAR_SCAN_CYCLE_S),
        decimate=config.LIDAR_DECIMATE,
        zones_validated=config.LIDAR_ZONES_VALIDATED,
        protective_m=2.15, warning_m=10.0, range_m=40.0)


@app.get("/alarms")
def alarms():
    """The event log and everything standing against the vehicle right now.

    Notably it cannot CLEAR anything: a latched fault is cleared at the panel
    with Reset, by somebody who can see the vehicle. The one control on the page
    is the service restart, which is the opposite of silencing an alarm - it
    de-energises the drives, is refused while armed, and throws the log away
    rather than tidying it.
    """
    return render_template("alarms.html", page="alarms",
                           max_events=events.MAX_EVENTS, unit=SERVICE_UNIT)


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
                           auto_slow_rpm=int(config.AUTO_SLOW_RPM),
                           k_ratio=config.K_RATIO, kd=config.KD,
                           zeta=f"{autopilot.predicted_zeta():.2f}",
                           slow_k_ratio=config.SLOW_K_RATIO,
                           slow_kd=config.SLOW_KD,
                           slow_zeta=f"{autopilot.predicted_zeta(slow=True):.2f}",
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


# ---- restarting this service ----------------------------------------------
#
# The controller restarts itself by DYING, not by asking systemd to restart it.
# `systemctl restart` is not available: this process runs as an unprivileged
# user, `sudo -n` wants a password and polkit answers "authorization requires
# authentication" for org.freedesktop.systemd1.manage-units. A web request has
# no terminal to answer either with.
#
# So it de-energises the drives and exits non-zero, and the unit's own
# Restart=on-failure brings it back after RestartSec. That inverts the usual
# reading of an exit code - a deliberate restart is recorded in the journal as a
# failure - and it is the price of needing no privilege at all.
#
# *** THIS DEPENDS ON THE UNIT'S RESTART POLICY. *** Without it, exiting is not
# a restart, it is a shutdown of the only thing that can stop the vehicle. So
# the policy is READ at request time rather than assumed: a unit edited to
# Restart=no, or a process started by hand from a shell, refuses instead.
SERVICE_UNIT = "agv_controller.service"


def _restart_policy():
    """(policy, seconds) from systemd, or (None, None) if it cannot be known.

    `systemctl show` is a read and needs no privilege - unlike `systemctl
    restart`, which is the whole reason this route works the way it does.
    """
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "Restart", "-p", "RestartUSec",
             SERVICE_UNIT],
            capture_output=True, text=True, timeout=4.0)
    except Exception:                       # noqa: BLE001 - no systemd, no policy
        return None, None
    if out.returncode != 0:
        return None, None
    fields = dict(line.split("=", 1) for line in out.stdout.splitlines()
                  if "=" in line)
    return fields.get("Restart"), fields.get("RestartUSec")


@app.post("/api/restart")
def api_restart():
    """Restart the controller process. De-energises the drives on the way out.

    Refused while armed: this is a stop, and a stop the operator did not ask for
    is exactly what the panel's Reset exists to make deliberate. Disarm first,
    which is itself a de-energise, and then the restart costs nothing that was
    not already given up.
    """
    snap = ctl.snapshot()
    if snap.get("armed"):
        return _fail("the vehicle is armed - disarm before restarting the "
                     "controller, so the stop is deliberate rather than a "
                     "side effect")

    policy, usec = _restart_policy()
    if policy not in ("on-failure", "always"):
        return _fail(
            f"this process would not come back: {SERVICE_UNIT} reports "
            f"Restart={policy or 'unknown'}. The restart button relies on "
            f"systemd restarting a process that exits non-zero, because it "
            f"cannot call systemctl itself.")

    events.warn("controller restart requested from /alarms - de-energising")

    def _bye():
        # Off the request thread, so the response reaches the browser before the
        # process stops answering. shutdown() joins the bus thread, whose finally
        # runs _do_disarm() - that is what actually de-energises.
        import time
        time.sleep(0.4)
        try:
            ctl.shutdown()
        finally:
            # _exit, not sys.exit: this is not the main thread, so an exception
            # would simply end this thread and leave the process running with a
            # shut-down controller - the one outcome worse than either restarting
            # or not.
            os._exit(1)

    threading.Thread(target=_bye, name="restart", daemon=True).start()
    return jsonify({"ok": True, "restart_usec": usec, "policy": policy})


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
        "auto_slow_rpm": config.AUTO_SLOW_RPM,
        "driver_ramp": config.RAMP,   # 6083h/6084h, per mode
        "manual_watchdog_ms": int(config.MANUAL_WATCHDOG_S * 1000),
        "auto_watchdog_ms": int(config.AUTO_WATCHDOG_S * 1000),
        "invert_left": config.INVERT_LEFT, "invert_right": config.INVERT_RIGHT,
        "table": {d: motion.velocities(d) for d in motion.PAD},
        "autopilot": {
            "dry_run": config.DRY_RUN, "invert_error": config.INVERT_ERROR,
            "k_ratio": config.K_RATIO, "kd": config.KD, "ki": config.KI,
            "tau_d_s": config.TAU_D_S, "auto_rpm": config.AUTO_RPM,
            "auto_slow_rpm": config.AUTO_SLOW_RPM,
            "slow_k_ratio": config.SLOW_K_RATIO, "slow_kd": config.SLOW_KD,
            "slow_zeta": round(autopilot.predicted_zeta(slow=True), 4),
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
