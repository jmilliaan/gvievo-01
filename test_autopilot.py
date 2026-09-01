#!/usr/bin/env python3
"""Offline checks for the line follower. No CAN, no hardware, no motion.

Two kinds of test:

  * a plant simulation - integrate  e_dot = v*theta + Ls*omega  against the real
    LineFollower, including the 1 mm sensor quantisation, the 50 Hz tick, the
    transport delay and (crucially) the wheel slew limit imposed by 6083h. The
    slew limit is what makes this worth simulating: an ideal plant that lets yaw
    follow the command instantly says K_RATIO = 100 is fine, and on this vehicle
    that diverges at 0.8 m/s.

  * behavioural assertions on the guards - conditional integration, the sensor
    slew clamp, no derivative kick after reset(), line-loss grace.

Run:  python3 test_autopilot.py
"""
import math
import os
import pathlib
import struct
import sys
import threading

import autopilot
import config
import kinematics
import motion

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def sensor(pos_mm, n=1):
    """A TPDO1 decode shaped like canworker._sensor_json()."""
    return {"tracks": [{"index": i + 1, "pos_mm": pos_mm, "width": 10}
                       for i in range(n)],
            "has_track": True}


NO_TRACK = {"tracks": [], "has_track": False}


# ---------------------------------------------------------------------------
# plant simulation
# ---------------------------------------------------------------------------

def simulate(base_rpm, e0_mm=30.0, seconds=12.0, driver_accel=2000.0,
             delay_s=0.020, sub_dt=0.0005, at_speed=True):
    """Closed-loop step response. Returns (overshoot_mm, settle_s, tail_rms_mm).

    at_speed pre-loads the ramp so the disturbance lands while already cruising.
    That is the demanding case and the realistic one: starting from rest lets the
    PID null most of the error before the vehicle has any speed, which flatters
    high gains badly.
    """
    f = autopilot.LineFollower()
    f.reset()

    y, theta = e0_mm / 1000.0, 0.0
    nl_act = nr_act = 0.0
    nl_cmd = nr_cmd = 0.0
    queue = []

    # The follower always ramps toward AUTO_RPM, so the cruise speed under test
    # has to BE AUTO_RPM or the vehicle spends the run decelerating.
    saved_rpm = config.AUTO_RPM
    config.AUTO_RPM = base_rpm
    if at_speed:
        f._v_rpm = base_rpm
        nl_act = nr_act = base_rpm
        nl_cmd = nr_cmd = base_rpm

    try:
        return _integrate(f, y, theta, nl_act, nr_act, nl_cmd, nr_cmd, queue,
                          seconds, driver_accel, delay_s, sub_dt, e0_mm)
    finally:
        config.AUTO_RPM = saved_rpm


def _integrate(f, y, theta, nl_act, nr_act, nl_cmd, nr_cmd, queue,
               seconds, driver_accel, delay_s, sub_dt, meas_mm):
    t = 0.0
    next_tick = next_frame = 0.0
    over = 0.0
    settle = None
    tail = []

    while t < seconds:
        if t >= next_frame:                       # 100 Hz, quantised to 1 mm
            next_frame += 0.01
            # The MLS reports where the LINE is relative to the SENSOR, which is
            # the NEGATIVE of where the sensor is relative to the line. Getting
            # this backwards used to cancel against INVERT_ERROR=False and the
            # sim converged for the wrong reason; with the real polarity now
            # measured on the machine, the model has to match it.
            meas_mm = -round((y + config.SENSOR_LOOKAHEAD_M
                              * math.sin(theta)) * 1000.0)
        if t >= next_tick:                        # 50 Hz control tick
            next_tick += config.DT_NOMINAL_S
            l, r, _ = f.update(sensor(meas_mm), 0.0, config.DT_NOMINAL_S, True)
            queue.append((t + delay_s, l, r))
        while queue and queue[0][0] <= t:
            _, nl_cmd, nr_cmd = queue.pop(0)

        # 6083h slews each wheel; this is the constraint the ideal model misses.
        step = driver_accel * sub_dt
        nl_act += max(-step, min(step, nl_cmd - nl_act))
        nr_act += max(-step, min(step, nr_cmd - nr_act))

        # Forward speed comes from the wheels, not from a constant - otherwise
        # speed_reduction has no effect on the plant and the controller and the
        # vehicle disagree about how fast it is going.
        v, omega = kinematics.wheels_to_body(nl_act, nr_act)
        y += v * math.sin(theta) * sub_dt
        theta += omega * sub_dt
        t += sub_dt

        e = y + config.SENSOR_LOOKAHEAD_M * math.sin(theta)
        over = max(over, -e)
        if abs(e) < 0.002 and settle is None and t > 0.5:
            settle = t
        elif abs(e) >= 0.002:
            settle = None
        if t > seconds - 2.0:
            tail.append(e)

    rms = math.sqrt(sum(x * x for x in tail) / len(tail)) * 1000.0 if tail else 0.0
    return over * 1000.0, settle, rms


def test_step_response():
    print("\nstep response (30 mm), real slew limit + 20 ms transport delay")
    zeta = autopilot.predicted_zeta()
    print(f"  gains K_RATIO={config.K_RATIO} KD={config.KD} "
          f"-> predicted zeta {zeta:.3f}")
    for rpm, label in ((config.AUTO_RPM, "cruise"), (2546.0, "0.8 m/s target")):
        over, settle, rms = simulate(rpm)
        d = (f"overshoot {over:.1f} mm, settle "
             f"{f'{settle:.2f} s' if settle else 'NEVER'}, tail {rms:.2f} mm")
        check(f"converges at {rpm:.0f} r/min ({label})", settle is not None, d)
        check(f"overshoot bounded at {rpm:.0f} r/min", over < 25.0, "")
        check(f"tail settled at {rpm:.0f} r/min", rms < 3.0, "")


def test_divergence_is_detectable():
    """The rig must be able to SEE instability, or the passes above mean nothing."""
    print("\nnegative control: an over-high gain must diverge")
    k, kd = config.K_RATIO, config.KD
    try:
        config.K_RATIO, config.KD = 100.0, 10.0
        over, settle, _ = simulate(2546.0, seconds=8.0)
        check("K_RATIO=100 at 0.8 m/s diverges as predicted",
              settle is None or over > 50.0, f"overshoot {over:.0f} mm")
    finally:
        config.K_RATIO, config.KD = k, kd


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

def test_no_derivative_kick_on_reset():
    print("\nreset() must not differentiate a standing error against a fake zero")
    f = autopilot.LineFollower()
    f.reset()
    _, _, d1 = f.update(sensor(40.0), 0.0, 0.02, True)
    check("first tick after reset has zero D term", d1["d"] == 0.0,
          f"d={d1['d']:.4f}")
    _, _, d2 = f.update(sensor(40.0), 0.0, 0.02, True)
    check("second tick with unchanged error still has ~zero D",
          abs(d2["d"]) < 1e-9, f"d={d2['d']:.6f}")


def test_sensor_slew_guard():
    print("\nsensor guards")
    f = autopilot.LineFollower()
    f.reset()
    f.update(sensor(10.0), 0.0, 0.02, True)
    _, _, d = f.update(sensor(95.0), 0.0, 0.02, True)   # 85 mm jump
    check("a glitch jump is clamped, not accepted", d["guard"] == "slew",
          f"guard={d['guard']!r} e_used={d['e_used']}")
    check("clamped to the step limit",
          abs(d["e_used"] - (10.0 + config.SENSOR_MAX_STEP_MM)) < 1e-6,
          f"e_used={d['e_used']}")

    f.reset()
    _, _, d = f.update(sensor(500.0), 0.0, 0.02, True)  # beyond the sensor
    check("an implausible reading is discarded", d["guard"] == "discard"
          and not d["has_track"], f"guard={d['guard']!r}")


def test_conditional_integration():
    print("\nconditional integration (integrate INSIDE the deadband only)")
    ki = config.KI
    try:
        config.KI = 1.0
        f = autopilot.LineFollower()
        f.reset()
        big = config.TI_DEADBAND_MM + 30.0
        for _ in range(50):
            f.update(sensor(big), 0.0, 0.02, True)
        check("integrator frozen outside the deadband", f._integral == 0.0,
              f"integral={f._integral:.4f}")
        small = config.TI_DEADBAND_MM / 2.0
        for _ in range(50):
            f.update(sensor(small), 0.0, 0.02, True)
        # Sign of the accumulation follows INVERT_ERROR; only the fact that it
        # accumulates at all is under test here.
        check("integrator accumulates inside the deadband", f._integral != 0.0,
              f"integral={f._integral:.4f}")
    finally:
        config.KI = ki


def test_line_loss_grace():
    print("\nline loss")
    f = autopilot.LineFollower()
    f.reset()
    for _ in range(100):
        f.update(sensor(0.0), 0.0, 0.02, True)
    cruising = f._v_rpm
    check("reaches cruise before the line drops", cruising > 100.0,
          f"v_base={cruising:.0f}")

    _, _, d = f.update(NO_TRACK, 0.0, 0.02, True)
    check("first missing frame coasts, does not stop", d["state"] == "coast",
          f"state={d['state']}")

    # The budget is a distance, so how long it lasts depends on how fast we are
    # going. Drive until it trips rather than assuming a tick count.
    for _ in range(500):
        _, _, d = f.update(NO_TRACK, 0.0, 0.02, True)
        if d["state"] == "line_lost":
            break
    check("grace expires into a stop", d["state"] == "line_lost",
          f"state={d['state']}")

    for _ in range(300):
        _, _, d = f.update(NO_TRACK, 0.0, 0.02, True)
    check("ramps down to zero after line loss", abs(d["v_base"]) < 1.0,
          f"v_base={d['v_base']:.2f}")


def test_stale_sensor_is_not_line_loss():
    print("\nstale sensor is a different failure from a tape gap")
    f = autopilot.LineFollower()
    f.reset()
    _, _, d = f.update(sensor(0.0), config.SENSOR_TIMEOUT_S + 0.05, 0.02, True)
    check("stale frames stop immediately, no grace",
          d["state"] == "sensor_lost", f"state={d['state']}")
    _, _, d = f.update(sensor(0.0), None, 0.02, True)
    check("never-seen sensor is also a stop", d["state"] == "sensor_lost")


def test_joint_saturation_preserves_ratio():
    print("\nsaturation scales BOTH wheels (turn ratio preserved)")
    f = autopilot.LineFollower()
    f.reset()
    v_rpm, omega = 3900.0, -3.0            # deliberately past the ceiling
    left, right, scale = f._to_wheels(v_rpm, omega)
    check("scale factor applied", scale < 1.0, f"scale={scale:.3f}")
    check("neither wheel exceeds the motor limit",
          max(abs(left), abs(right)) <= config.MOTOR_MAX_RPM + 1e-6,
          f"L={left:.0f} R={right:.0f}")

    # Uniform scaling multiplies v and omega by the same factor, so omega/v -
    # the radius of the arc being driven - must come out unchanged. Compare
    # against the REQUESTED arc, not against some other command.
    want = omega / kinematics.rpm_to_mps(v_rpm)
    v_out, w_out = kinematics.wheels_to_body(left, right)
    check("arc (omega/v) preserved through scaling",
          abs(want - w_out / v_out) < 1e-6,
          f"requested {want:.5f}, got {w_out / v_out:.5f}")


def test_inner_wheel_floor():
    print("\ninner wheel floor limits the DIFFERENTIAL, not one wheel")
    f = autopilot.LineFollower()
    f.reset()
    left, right, _ = f._to_wheels(400.0, -5.0)     # demands a huge differential
    lo = config.INNER_WHEEL_MIN_RPM
    check("inner wheel held at or above the floor",
          min(left, right) >= lo - 1e-6, f"L={left:.1f} R={right:.1f} floor={lo}")
    check("base speed unchanged by the floor",
          abs((left + right) / 2.0 - 400.0) < 1e-6,
          f"mean={(left + right) / 2.0:.2f}")


def test_kinematics_roundtrip():
    print("\nkinematics")
    l, r = kinematics.body_to_wheels(0.25, 0.3)
    v, w = kinematics.wheels_to_body(l, r)
    check("body_to_wheels and wheels_to_body are inverses",
          abs(v - 0.25) < 1e-9 and abs(w - 0.3) < 1e-9, f"v={v:.6f} w={w:.6f}")
    check("2546 r/min is 0.8 m/s",
          abs(kinematics.rpm_to_mps(2546) - 0.8) < 0.001,
          f"{kinematics.rpm_to_mps(2546):.4f} m/s")
    check("yaw accel limit at 6083h=2000 is 2.59 rad/s^2",
          abs(kinematics.max_yaw_accel(2000) - 2.586) < 0.01,
          f"{kinematics.max_yaw_accel(2000):.3f}")


# ---------------------------------------------------------------------------
# canworker re-entrancy (regression)
# ---------------------------------------------------------------------------

class _FakeRaw:
    """A bus that behaves like the real one during an SDO read while the MLS is
    streaming: a couple of sensor frames are already queued, then the SDO reply
    lands, then the queue drains empty."""

    def __init__(self):
        self.pending = [("pdo",), ("pdo",)]

    def send(self, m):
        if 0x600 <= m.arbitration_id <= 0x67F:
            self.pending += [("pdo",), ("sdo", m.arbitration_id - 0x600)]

    def recv(self, timeout=None):
        import can
        if not self.pending:
            return None
        kind = self.pending.pop(0)
        if kind[0] == "pdo":
            return can.Message(arbitration_id=config.TPDO1_COB,
                               data=bytes(8), is_extended_id=False)
        return can.Message(arbitration_id=0x580 + kind[1],
                           data=bytes([0x43, 0, 0, 0]) + struct.pack("<I", 7),
                           is_extended_id=False)

    def shutdown(self):
        pass


def test_arm_does_not_deadlock():
    """Arming must not self-deadlock the bus thread.

    sdo_read() drains the RX queue before transmitting, TpdoTap routes sensor
    frames to Controller._on_pdo(), and _on_pdo() takes Controller._lock. Any
    bus I/O performed while already holding that lock therefore deadlocks the
    bus thread against itself - and because snapshot() and keepalive() take the
    same lock, every Flask request wedges with it. That is not hypothetical: it
    shipped, and it presented as 409s on both arm and disarm with /api/state
    hanging.
    """
    print("\ncanworker: arming must not deadlock on the sensor stream")
    import canworker
    import events

    ctl = canworker.Controller()
    ctl.bus = canworker.TpdoTap(_FakeRaw(), ctl._on_pdo)
    ctl._do_preflight = lambda: {"ok": True, "report": []}
    ctl._nmt = lambda cmd, node: None

    t = threading.Thread(target=lambda: ctl._do_arm("auto"), daemon=True)
    t.start()
    t.join(timeout=10.0)
    check("_do_arm completes (no deadlock)", not t.is_alive(),
          "still blocked after 10 s" if t.is_alive() else "")
    if t.is_alive():
        return
    check("the re-entrant path was actually exercised", ctl._sensor_seen > 0,
          f"{ctl._sensor_seen} sensor frames absorbed during the arm")

    done = threading.Event()
    threading.Thread(target=lambda: (ctl.snapshot(), done.set()),
                     daemon=True).start()
    check("snapshot() still returns afterwards", done.wait(3.0))

    # No bus call may sit inside a locked section - the RLock is a backstop,
    # not a licence. This is the invariant that actually keeps it fixed.
    import re
    src = pathlib.Path("canworker.py").read_text().split("\n")
    inlock, indent, bad = False, 0, []
    for i, line in enumerate(src, 1):
        body = line.strip()
        if body.startswith("with self._lock"):
            inlock, indent = True, len(line) - len(line.lstrip())
            continue
        if inlock:
            cur = len(line) - len(line.lstrip())
            if body and cur <= indent:
                inlock = False
            elif re.search(r"self\._read\(|self\._write\(|sdo_read\("
                           r"|sdo_write\(|self\._nmt\(|bus\.(send|recv)\(",
                           body):
                bad.append(f"{i}: {body}")
    check("no bus I/O inside any locked section", not bad,
          "; ".join(bad) if bad else "")

    # -- the health wiring, end to end on the fake bus -----------------------
    # health.py is unit-tested above; this proves the Controller actually feeds
    # it and acts on it, which a source scan alone cannot show.
    ctl._armed = True
    ctl._auto_running = True
    ctl._target = (800, 800)
    events.clear()

    for nid in config.NODES:                    # both drivers answered once
        ctl._src_node[nid].mark_rx(now=0.0)
    hw = ctl._hw.evaluate(now=0.0)
    check("healthy drivers raise no critical fault", not hw["system_error"])

    hw = ctl._hw.evaluate(now=config.DRIVER_TIMEOUT_S + 1.0)
    check("a silent driver trips the critical tier", hw["system_error"],
          hw["system_detail"])
    target = ctl._apply_health(hw, armed=True, target=(800, 800))
    check("a critical fault zeroes the setpoint", target == (0, 0), str(target))
    check("a critical fault clears the auto latch", not ctl._auto_running)
    check("a critical fault names itself in stop_reason",
          "silent" in (ctl._last_stop_reason or ""), str(ctl._last_stop_reason))

    n_after_first = len(events.since(0)[1])
    for i in range(50):                         # a second of ticks, still dead
        hw2 = ctl._hw.evaluate(now=config.DRIVER_TIMEOUT_S + 2.0 + i * 0.02)
        if hw2["changed"] or hw2["system_edge"] is not None:
            ctl._apply_health(hw2, armed=True, target=(0, 0))
    check("a standing fault does not re-emit every tick",
          len(events.since(0)[1]) == n_after_first,
          f"{len(events.since(0)[1]) - n_after_first} extra event(s)")

    ctl._health = hw
    try:
        ctl._do_arm("manual")
        check("arming is refused while a driver is silent", False, "accepted!")
    except RuntimeError as e:
        check("arming is refused while a driver is silent",
              "not answering" in str(e), str(e)[:60])
    events.clear()


def test_config_profile():
    """The profile is the whole tuning surface, so a bad one must be refused
    loudly at boot rather than showing up as odd behaviour on a length of tape."""
    import copy
    import json
    import shutil
    import tempfile
    print("\nvehicle profile loading")

    base = json.load(open(config.profile_path()))

    def load_with(mutate, name="agv-01"):
        d = copy.deepcopy(base)
        mutate(d)
        # Written under its profile NAME, not a random temp name: the loader
        # requires profile_name to match the filename, so a tmpXXXX.json would
        # be refused for the wrong reason and every check below would pass
        # vacuously.
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, f"{name}.json")
        with open(path, "w") as fh:
            json.dump(d, fh)
        try:
            config.load(path)
            return None
        except config.ConfigError as e:
            return str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            config.load()          # always restore the real profile

    def refuses(name, mutate, expect=""):
        msg = load_with(mutate)
        check(name, msg is not None and expect in (msg or ""), msg or "accepted!")

    check("the real profile loads", config.PROFILE_NAME == "agv-01",
          config.PROFILE_NAME)
    refuses("a typo'd key is refused",
            lambda d: d["autopilot"].update({"k_rato": d["autopilot"].pop("k_ratio")}),
            "unknown key")
    refuses("a missing key is refused",
            lambda d: d["autopilot"].pop("kd"), "missing key")
    refuses("an unknown section is refused",
            lambda d: d.update({"extra": {}}), "unknown top-level")
    refuses("a negative gain is refused, by name",
            lambda d: d["autopilot"].update(k_ratio=-1.0), "K_RATIO")
    refuses("auto_rpm above the motor limit is refused",
            lambda d: d["autopilot"].update(auto_rpm=9000.0), "AUTO_RPM")
    refuses("a bool where a number belongs is refused",
            lambda d: d["autopilot"].update(kd=True), "expected a number")
    refuses("duplicate CAN node IDs are refused",
            lambda d: d["can"].update(sensor_node=2), "distinct")
    # The pairing neither module could check alone before config existed.
    refuses("a software ramp at or above 6083h is refused",
            lambda d: d["autopilot"].update(ramp_accel_rpm_s=2000.0),
            "must stay below")
    # A profile written before the units changed must not run silently on a
    # stale key - the loader rejects unknowns, which is what catches it.
    refuses("a pre-rename profile (line_loss_grace_s) is refused",
            lambda d: d["autopilot"].update(
                line_loss_grace_s=d["autopilot"].pop("line_loss_grace_m")),
            "unknown key")
    refuses("a pre-rename profile (sr_pos_coef) is refused",
            lambda d: d["autopilot"].update(
                sr_pos_coef=d["autopilot"].pop("sr_pos_frac")),
            "unknown key")

    refuses("a driver timeout inside the telemetry period is refused",
            lambda d: d["timing"].update(driver_timeout_s=0.1),
            "driver_timeout_s")
    refuses("an empty can.channel is refused",
            lambda d: d["can"].update(channel=""), "can.channel")

    # The name in the file must match the file. A profile copied for a second
    # vehicle and not renamed would report the old identity in the event log
    # and in every run CSV header.
    msg = load_with(lambda d: None, name="agv-99")
    check("profile_name must match the filename", msg is not None
          and "agv-99" in (msg or ""), msg or "accepted!")

    # -- which vehicle this process is --------------------------------------
    check("the default profile resolves into profiles/",
          config.profile_path().endswith(os.path.join("profiles", "agv-01.json")),
          config.profile_path())
    os.environ[config.PROFILE_ENV_VAR] = "agv-02"
    try:
        check("AGV_PROFILE selects the profile",
              config.profile_path().endswith("agv-02.json"),
              config.profile_path())
        check("an explicit path still wins over the env var",
              config.profile_path("agv-03").endswith("agv-03.json"))
        try:
            config.load()
            check("a missing profile is fatal", False, "accepted!")
        except config.ConfigError as e:
            check("a missing profile names the env var and what exists",
                  config.PROFILE_ENV_VAR in str(e) and "agv-01" in str(e),
                  str(e)[:80])
    finally:
        del os.environ[config.PROFILE_ENV_VAR]
        config.load()

    # A rejected profile must leave the live one untouched - this is what makes
    # load() safe to call again later from a reload endpoint.
    load_with(lambda d: d["autopilot"].update(k_ratio=-1.0))
    check("a rejected profile leaves the live one intact",
          config.K_RATIO == 11.3, f"K_RATIO={config.K_RATIO}")


def test_derived_constants():
    """Values that used to be literals in .py files are now computed from the
    profile primitives.

    The geometry constants are checked against their former literals, because
    those come from a tape measure and must not drift. Everything else is
    checked as a RELATIONSHIP to its inputs - asserting a tuned number here
    would just break the suite every time someone edits the profile, which is
    the whole point of the profile existing."""
    print("\nderived constants follow their inputs")
    close = lambda a, b: abs(a - b) < abs(b) * 1e-6
    check("MPS_PER_RPM", close(config.MPS_PER_RPM, 3.14159265e-4),
          f"{config.MPS_PER_RPM:.6e}")
    check("RPM_PER_MPS", close(config.RPM_PER_MPS, 3183.0989),
          f"{config.RPM_PER_MPS:.4f}")
    check("RAD_S_PER_RPM_DIFF", close(config.RAD_S_PER_RPM_DIFF, 6.4641824e-4),
          f"{config.RAD_S_PER_RPM_DIFF:.6e}")
    check("MAX_SPEED_MPS", close(config.MAX_SPEED_MPS, 1.2566371),
          f"{config.MAX_SPEED_MPS:.4f}")
    check("MANUAL_HALF_RPM is full_rpm * half_ratio, rounded",
          config.MANUAL_HALF_RPM
          == round(config.MANUAL_FULL_RPM * config.MANUAL_HALF_RATIO),
          f"{config.MANUAL_FULL_RPM} x {config.MANUAL_HALF_RATIO} "
          f"-> {config.MANUAL_HALF_RPM}")
    check("DT band is 0.2x .. 5x nominal",
          close(config.DT_MIN_S, 0.2 * config.DT_NOMINAL_S)
          and close(config.DT_MAX_S, 5.0 * config.DT_NOMINAL_S),
          f"{config.DT_MIN_S} .. {config.DT_MAX_S}")
    check("ACCEL/DECEL track the auto ramp block",
          config.ACCEL_RPM_S == config.RAMP["auto"]["accel"]
          and config.DECEL_RPM_S == config.RAMP["auto"]["decel"],
          f"{config.ACCEL_RPM_S} / {config.DECEL_RPM_S}")
    check("TPDO1_COB is 0x180 + sensor node",
          config.TPDO1_COB == 0x180 + config.SENSOR_NODE, hex(config.TPDO1_COB))
    check("NODES maps the configured driver IDs",
          config.NODES == {config.LEFT: "left", config.RIGHT: "right"},
          str(config.NODES))
    # motion's table is built from the profile now, not from module literals.
    full, half = config.MANUAL_FULL_RPM, config.MANUAL_HALF_RPM
    check("manual jog table is built from the profile",
          motion.velocities("forward_left") == (half, full)
          and motion.velocities("forward") == (full, full)
          and motion.velocities("stop") == (0, 0),
          f"fwd-left {motion.velocities('forward_left')}")


def test_health():
    """Hardware liveness: the two-tier watchdog and its edge reporting.

    The hole this closes: _poll_telemetry() keeps the last statusword when an
    SDO read returns None, so before health.py a driver that stopped answering
    looked alive for as long as the process ran.
    """
    import health
    print("\nhardware health")

    # -- a source is not a fault until it has been seen once -----------------
    src = health.HealthSource("mls")
    mon = health.HealthMonitor([(src, 1.0)])
    r = mon.evaluate(now=100.0)
    check("a never-seen source is not reported lost",
          not r["sensor_error"] and not r["system_error"])
    check("a never-seen source reports seen=False",
          r["sources"]["mls"]["seen"] is False)

    src.mark_rx(now=100.0)
    r = mon.evaluate(now=100.5)
    check("a fresh source is healthy", r["sources"]["mls"]["ok"] is True)
    r = mon.evaluate(now=101.5)
    check("a source past its timeout is lost", r["sensor_error"] is True,
          r["sensor_detail"])
    src.mark_rx(now=101.6)
    r = mon.evaluate(now=101.7)
    check("a source recovers on the next read", r["sensor_error"] is False)

    # -- the two tiers route differently -------------------------------------
    drv = health.HealthSource("driver:1", critical=True, detail="node 1 (left)")
    mls = health.HealthSource("mls")
    mon = health.HealthMonitor([(drv, 0.5), (mls, 0.5)])
    drv.mark_rx(now=0.0)
    mls.mark_rx(now=0.0)
    mon.evaluate(now=0.1)
    mls.mark_rx(now=1.0)                 # sensor alive, driver silent
    r = mon.evaluate(now=1.0)
    check("a silent driver raises the CRITICAL tier",
          r["system_error"] is True and r["sensor_error"] is False,
          r["system_detail"])
    drv.mark_rx(now=2.0)                 # driver back, sensor now silent
    r = mon.evaluate(now=2.0)
    check("a silent sensor raises the AUTO-ONLY tier",
          r["sensor_error"] is True and r["system_error"] is False,
          r["sensor_detail"])

    # -- edges fire ONCE, not once per tick ----------------------------------
    # This is the events.py trap: at 50 Hz a per-tick emit empties the whole
    # 200-entry ring in about four seconds.
    s = health.HealthSource("x", critical=True)
    mon = health.HealthMonitor([(s, 0.5)])
    s.mark_rx(now=0.0)
    mon.evaluate(now=0.0)
    edges = tier_edges = 0
    for i in range(100):                 # 2 s of ticks with the source dead
        r = mon.evaluate(now=1.0 + i * 0.02)
        edges += len(r["changed"])
        tier_edges += r["system_edge"] is not None
    check("a source transition is reported once, not per tick", edges == 1,
          f"{edges} edge(s) over 100 ticks")
    check("a tier transition is reported once, not per tick", tier_edges == 1,
          f"{tier_edges} edge(s) over 100 ticks")

    # -- PullSource wraps an existing snapshot -------------------------------
    snap = {"comms_ok": True, "rx_age_s": 0.2, "detail": "reader"}
    pull = health.PullSource("rfid", lambda: snap)
    mon = health.HealthMonitor([(pull, 5.0)])
    check("a pull source reports its snapshot verdict",
          mon.evaluate(now=0.0)["sources"]["rfid"]["ok"] is True)
    snap["comms_ok"] = False
    check("a pull source fault reaches the auto-only tier",
          mon.evaluate(now=0.0)["sensor_error"] is True)
    # rfid.enabled false -> comms_ok is None -> not in use, never a fault.
    snap["comms_ok"] = None
    r = mon.evaluate(now=0.0)
    check("a disabled pull source never blocks a mode",
          r["sensor_error"] is False and r["sources"]["rfid"]["in_use"] is False)
    pull_raises = health.PullSource("boom", lambda: 1 / 0)
    check("a raising snapshot is absorbed, never propagated",
          health.HealthMonitor([(pull_raises, 1.0)]).evaluate(now=0.0)
          ["sensor_error"] is False)

    # -- reset clears history across a bus reopen ----------------------------
    s = health.HealthSource("y")
    s.mark_rx(now=0.0)
    mon = health.HealthMonitor([(s, 0.5)])
    mon.reset()
    check("reset() forgets a stale timestamp",
          mon.evaluate(now=999.0)["sensor_error"] is False)

    # -- health.py stays dependency-free -------------------------------------
    head = pathlib.Path("health.py").read_text()
    head = head[head.index('"""', head.index('"""') + 3):]
    imports = {ln.split()[1].split(".")[0] for ln in head.splitlines()
               if ln.startswith(("import ", "from "))}
    check("health.py imports only the standard library",
          imports <= {"time"}, str(sorted(imports)))

    # -- wired into the vehicle, on the paths that prove liveness ------------
    cw = pathlib.Path("canworker.py").read_text()
    check("the sensor marks health on every decoded frame",
          "self._src_mls.mark_rx(" in cw)
    check("each driver marks health on a telemetry answer",
          "self._src_node[nid].mark_rx()" in cw)
    check("health is evaluated outside the lock",
          "hw = self._hw.evaluate(now)" in cw)
    check("a critical fault refuses an arm", "system_error" in
          cw[cw.index("def _do_arm"):cw.index("def _do_disarm")])


def test_sensor_starts_in_every_mode():
    """The tape strip is shown on the manual page too, which only works if the
    sensor is NMT-started on a manual arm - it used to be auto-only."""
    print("\nsensor bring-up is mode-independent")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "canworker.py")).read()
    check("_start_sensor() exists", "def _start_sensor(self):" in src)
    check("no sensor NMT start left behind a mode test",
          'if mode == "auto":\n            self._nmt(0x01, config.SENSOR_NODE)'
          not in src)
    check("both arm paths call it", src.count("self._start_sensor()") == 2,
          f"{src.count('self._start_sensor()')} call sites")
    check("field level polls whenever armed, not only in auto",
          "if armed and now - t_field" in src)


def test_grace_is_a_distance_not_a_time():
    """The regression that started all this.

    line_loss_grace was a TIME, so raising cruise 800 -> 2000 silently grew the
    blind travel from 75 mm to 188 mm and nobody noticed. As a distance the
    budget holds across speeds - the coast lasts a shorter TIME when moving
    faster, but covers the same GROUND, which is the quantity that matters.
    """
    print("\nline-loss grace is budgeted in distance, not time")

    def coast(base_rpm):
        saved = config.AUTO_RPM
        config.AUTO_RPM = base_rpm
        try:
            f = autopilot.LineFollower()
            f.reset()
            for _ in range(600):                  # reach cruise
                f.update(sensor(0.0), 0.0, 0.02, True)
            v = f._v_rpm
            secs, dist = 0.0, 0.0
            for _ in range(2000):
                _, _, d = f.update(NO_TRACK, 0.0, 0.02, True)
                if d["state"] != "coast":
                    break
                secs += 0.02
                dist += kinematics.rpm_to_mps(d["v_base"]) * 0.02
            return v, secs, dist
        finally:
            config.AUTO_RPM = saved

    v_slow, t_slow, d_slow = coast(800.0)
    v_fast, t_fast, d_fast = coast(2000.0)
    check("both speeds reached cruise", v_slow > 700 and v_fast > 1900,
          f"{v_slow:.0f} / {v_fast:.0f} r/min")
    check("coasts the same DISTANCE at either speed",
          abs(d_slow - d_fast) < 0.02,
          f"{d_slow*1000:.0f} mm at 800 vs {d_fast*1000:.0f} mm at 2000")
    check("distance is about the configured budget",
          abs(d_fast - config.LINE_LOSS_GRACE_M) < 0.03,
          f"{d_fast*1000:.0f} mm vs budget {config.LINE_LOSS_GRACE_M*1000:.0f} mm")
    check("coasts for LESS TIME when moving faster", t_fast < t_slow * 0.75,
          f"{t_slow:.2f} s at 800 vs {t_fast:.2f} s at 2000")

    # Standstill backstop: no distance accrues, so only the time ceiling can
    # end it. Drive the follower with the ramp pinned at zero.
    f = autopilot.LineFollower()
    f.reset()
    secs = 0.0
    for _ in range(2000):
        f._v_rpm = 0.0                      # pin: stopped, cannot travel
        _, _, d = f.update(NO_TRACK, 0.0, 0.02, True)
        secs += 0.02
        if d["state"] != "coast":
            break
    check("a stationary AGV still gives up, on the time ceiling",
          d["state"] == "line_lost"
          and secs <= config.LINE_LOSS_GRACE_MAX_S + 0.05,
          f"{d['state']} after {secs:.2f} s "
          f"(ceiling {config.LINE_LOSS_GRACE_MAX_S:.2f} s)")


def test_speed_reduction_is_a_fraction():
    """Speed reduction must shed the same PROPORTION of base at any speed."""
    print("\nspeed reduction scales with base speed")

    def shed(base_rpm, err_mm=20.0):
        f = autopilot.LineFollower()
        f.reset()
        f._v_rpm = base_rpm
        for _ in range(200):                # let the SR low-pass settle
            red = f._reduce_speed(err_mm / 1000.0, 0.02)
        return red

    r800, r2000 = shed(800.0), shed(2000.0)
    check("20 mm error sheds the same fraction at 800 and 2000",
          abs(r800 / 800.0 - r2000 / 2000.0) < 0.005,
          f"{r800/800*100:.1f}% vs {r2000/2000*100:.1f}%")
    check("and that fraction is the configured one",
          abs(r2000 / 2000.0 - 20.0 * config.SR_POS_FRAC) < 0.005,
          f"{r2000/2000*100:.1f}% vs {20.0*config.SR_POS_FRAC*100:.1f}%")
    check("the cap still bounds it", shed(2000.0, err_mm=5000.0)
          <= 2000.0 * config.SR_CAP + 1e-6)


def test_loop_health():
    """The loop-health window is what makes a telemetry stall visible without
    hand-parsing a CSV column, so its two timings must stay distinct."""
    print("\nloop health window")
    import canworker

    h = canworker._LoopHealth(window=4)
    seen, out = 0, None
    for i, (new, armed) in enumerate([(2, True), (0, True), (2, True), (0, True)]):
        seen += new
        out = h.tick(i * 0.02, 0.009, seen, armed)
    check("emits once the window fills", out is not None)
    check("work and period are separate numbers",
          abs(out["work_avg_ms"] - 9.0) < 0.01
          and abs(out["period_avg_ms"] - 20.0) < 0.01,
          f"work {out['work_avg_ms']:.1f} ms, period {out['period_avg_ms']:.1f} ms")
    check("counts starved ticks while armed", out["starved"] == 2,
          str(out["starved"]))
    check("window resets after emitting", h.tick(0.1, 0.009, seen, True) is None)

    h2 = canworker._LoopHealth(window=4)
    for i in range(4):
        out2 = h2.tick(i * 0.02, 0.009, 0, False)
    check("no frames while DISARMED is not starvation", out2["starved"] == 0)


def test_event_log():
    """A stop reason has to outlive a page reload, and the buffer must not be
    floodable from a per-tick path."""
    print("\noperator event log")
    import events

    events.clear()
    check("empty buffer reports seq 0", events.latest_seq() == 0)
    s1 = events.info("armed in manual mode")
    s2 = events.warn("line lost")
    check("sequence numbers advance", s2 > s1, f"{s1} -> {s2}")

    latest, items = events.since(0)
    check("since(0) returns everything", len(items) == 2 and latest == s2)
    _, newer = events.since(s1)
    check("since(seq) returns only newer", [e["seq"] for e in newer] == [s2])
    check("entries carry level and message",
          newer[0]["level"] == "warn" and newer[0]["msg"] == "line lost")

    for i in range(events.MAX_EVENTS + 50):
        events.info(f"filler {i}")
    _, items = events.since(0)
    check("ring buffer is bounded", len(items) == events.MAX_EVENTS,
          f"{len(items)} retained, cap {events.MAX_EVENTS}")
    check("oldest entries are the ones dropped",
          all("filler" in e["msg"] for e in items))

    def hammer():
        for _ in range(300):
            events.info("x")
    ts = [threading.Thread(target=hammer) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    _, items = events.since(0)
    seqs = [e["seq"] for e in items]
    check("concurrent emit keeps sequence numbers unique and ordered",
          len(set(seqs)) == len(seqs) and seqs == sorted(seqs))
    check("an unknown level does not raise",
          events.emit("bogus", "still recorded") > 0)
    events.clear()

    # The 50 Hz paths must never emit - one chatty call site empties the whole
    # buffer of anything meaningful in about four seconds.
    src = pathlib.Path("canworker.py").read_text()

    def method_body(name, text=src):
        """Source of one method, ending at the NEXT def rather than a named one.

        Slicing to a named successor silently widens the window when someone
        inserts a method between the two, which turns this check into a false
        positive against a method it was never meant to cover.
        """
        start = text.index(f"def {name}")
        nxt = text.find("\n    def ", start + 1)
        return text[start:nxt if nxt != -1 else len(text)]

    check("_run_autopilot() never emits",
          "events." not in method_body("_run_autopilot"))
    win = src[src.index("class _LoopHealth"):src.index("class Controller")]
    check("_LoopHealth never emits", "events." not in win)
    check("driver faults are edge-tracked, not polled",
          "_fault_seen" in src)


def test_run_plot():
    """The plot is generated on STOP inside the service; a crash there must not
    be able to reach the control thread, and the PNG must be a real PNG."""
    import struct
    import plotrun
    import runlog
    print("\nrun plot rendering")

    rows = [dict(t=i * 0.02, state="run" if i < 400 else "stopping",
                 e_mm=12.0 * math.sin(i * 0.05), n_l=800.0, n_r=790.0,
                 rpm_l=798.0, rpm_r=788.0) for i in range(450)]
    png = plotrun.render(rows, title="test", subtitle="gains")
    check("emits a PNG signature", png[:8] == b"\x89PNG\r\n\x1a\n")
    w, h = struct.unpack(">II", png[16:24])
    check("IHDR is the requested pixel size", (w, h) == (1700, 850), f"{w}x{h}")
    check("width/height are honoured", struct.unpack(
        ">II", plotrun.render(rows, width=900, height=500)[16:24]) == (900, 500))

    check("empty input does not raise", plotrun.render([])[:4] == b"\x89PNG")

    # Fixed axes are what make two runs comparable by eye. An out-of-range point
    # must clip at the frame rather than quietly rescaling and defeating that.
    lims = {}
    real_render = plotrun.render

    def capture(rws, **kw):
        plt = plotrun._pyplot()
        out = real_render(rws, **kw)
        lims["fig_count"] = len(plt.get_fignums())
        return out

    spiky = [dict(r) for r in rows]
    spiky[10]["e_mm"] = 900.0
    a = capture(rows, err_range=(-30.0, 30.0), rpm_range=(0.0, 2500.0))
    b = capture(spiky, err_range=(-30.0, 30.0), rpm_range=(0.0, 2500.0))
    check("an out-of-range point does not change the frame size",
          struct.unpack(">II", a[16:24]) == struct.unpack(">II", b[16:24]))
    check("the outlier still changes the image (drawn, then clipped)", a != b)
    check("figures are closed, not leaked", lims["fig_count"] == 0,
          f"{lims['fig_count']} open figures")

    stats = plotrun._stats(rows)
    check("stats line reports duration and RMS",
          "Duration" in stats and "RMS" in stats and "Avg L" in stats, stats)
    check("stats ignores non-run rows",
          plotrun._stats([dict(t=0.0, state="stopping", e_mm=500.0,
                               n_l=0.0, n_r=0.0, rpm_l=0.0, rpm_r=0.0)])
          is not None)
    check("all-None error column does not raise",
          plotrun.render([dict(t=i * 0.02, state="run", e_mm=None, n_l=1.0,
                               n_r=1.0, rpm_l=1.0, rpm_r=1.0)
                          for i in range(10)])[:4] == b"\x89PNG")

    # Decimation must keep the extremes: a one-tick spike is exactly the thing
    # worth seeing, and dropping it would make the plot lie about the run.
    spiky = [dict(t=i * 0.02, state="run", e_mm=0.0, n_l=800.0, n_r=800.0,
                  rpm_l=800.0, rpm_r=800.0) for i in range(20000)]
    spiky[7777]["e_mm"] = 99.0
    spiky[9999]["e_mm"] = -77.0
    kept = plotrun._decimate(spiky, 1000, 0.0, spiky[-1]["t"])
    check("decimation thins a long run", len(kept) < len(spiky) / 4,
          f"{len(spiky)} -> {len(kept)} rows")
    es = [r["e_mm"] for r in kept]
    check("decimation preserves the error envelope",
          max(es) == 99.0 and min(es) == -77.0,
          f"kept max {max(es)} min {min(es)}")
    check("decimated rows stay in time order",
          all(kept[i]["t"] <= kept[i + 1]["t"] for i in range(len(kept) - 1)))

    # A bad row must set .error, not propagate out of close().
    lg = runlog.RunLog()
    lg.path = "/nonexistent/dir/run.csv"
    lg.plot_path = "/nonexistent/dir/run.png"
    lg.dir = "/nonexistent/dir"
    lg._render()
    check("a plot failure is captured, never raised",
          lg.error is not None and lg.plot_path is None, str(lg.error)[:50])

    # matplotlib must not be dragged into the control process at import time -
    # it costs seconds and ~100 MB, and only the render thread ever needs it.
    src = pathlib.Path("plotrun.py").read_text()
    head = src[:src.index("def _pyplot")]
    check("plotrun does not import matplotlib at module level",
          "import matplotlib" not in head and "import pyplot" not in head)
    check("the Agg backend is selected before pyplot",
          src.index('matplotlib.use("Agg")') < src.index("import matplotlib.pyplot"))


def test_rfid():
    """Protocol is not inferred - it is the same reader hardware as KIM2A, so the
    framing is checked against frames shaped exactly like the ones their
    production parser handles."""
    import copy
    import json
    import tempfile
    import rfid
    print("\nrfid link")

    cx = rfid.ChafonCFCodec(init=bytes.fromhex("CFFF0070002415"),
                            frame_len=17, tag_offset=13, tag_len=2,
                            ignore=("3130",))

    check("init command is the one the working vehicle sends",
          cx.handshake() == bytes.fromhex("CFFF0070002415"),
          cx.handshake().hex(" ").upper())
    check("push-only: there is nothing to poll", cx.poll() is None)

    def frame(tag_hex, fill=b"\x00"):
        f = bytearray(b"\xCF" + fill * 16)
        f[13:15] = bytes.fromhex(tag_hex)
        return bytes(f)

    good = frame("1234")
    frames, used = cx.decode(good)
    check("a 17-byte frame decodes", len(frames) == 1 and used == 17)
    check("tag comes from bytes 13:15", cx.tag_of(frames[0]) == "1234",
          str(cx.tag_of(frames[0])))

    check("the 3130 startup echo is not a tag",
          cx.tag_of(frame("3130")) is None)

    frames, used = cx.decode(b"\x00\x11" + good)
    check("junk before the header is skipped", len(frames) == 1 and used == 19)

    frames, used = cx.decode(good + good)
    check("two frames in one read both decode", len(frames) == 2)

    frames, used = cx.decode(good[:9])
    check("a partial frame is kept, not consumed",
          frames == [] and used == 0, f"used={used}")
    frames, used = cx.decode(good + good[:9])
    check("trailing partial survives a whole frame",
          len(frames) == 1 and used == 17, f"used={used}")

    # KIM2A splits the hex STRING on "CF" and length-checks the pieces, so a
    # frame whose payload contains 0xCF is torn in two and dropped. Scanning for
    # the header and taking a fixed span keeps it.
    embedded = bytearray(good)
    embedded[5] = 0xCF
    frames, _ = cx.decode(bytes(embedded))
    check("a payload containing 0xCF still decodes as ONE frame",
          len(frames) == 1 and cx.tag_of(frames[0]) == "1234",
          f"{len(frames)} frame(s)")

    import random
    random.seed(11)
    ok = True
    for _ in range(400):
        blob = bytes(random.randrange(256) for _ in range(random.randrange(48)))
        try:
            fr, u = cx.decode(blob)
            assert 0 <= u <= len(blob)
            for f in fr:
                cx.tag_of(f)
        except Exception as e:                      # noqa: BLE001
            check("decode never raises on random bytes", False, repr(e))
            ok = False
            break
    if ok:
        check("decode and tag_of never raise on random bytes", True)

    link = rfid.RfidLink()
    snap = link.snapshot()
    check("carrier is read from the real NIC, or None if absent",
          snap["carrier"] in (True, False, None), str(snap["carrier"]))
    check("silence is not a fault while connected",
          snap["silent"] is False, str(snap["silent"]))

    base = json.load(open(config.profile_path()))

    def refuses(name, mutate, expect):
        import shutil
        d = copy.deepcopy(base)
        mutate(d)
        # Under its profile name - the loader checks the stem, so a temp name
        # would be refused for the wrong reason. See test_config_profile().
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "agv-01.json")
        with open(p, "w") as fh:
            json.dump(d, fh)
        try:
            config.load(p)
            check(name, False, "accepted!")
        except config.ConfigError as e:
            check(name, expect in str(e), str(e)[:70])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            config.load()

    refuses("a tag slice outside the frame is refused",
            lambda d: d["rfid"].update(tag_offset=16), "must fit inside")
    refuses("a non-hex init command is refused",
            lambda d: d["rfid"].update(init_hex="zz"), "init_hex")
    refuses("enabling with no init command is refused",
            lambda d: d["rfid"].update(init_hex=""), "stay silent")
    refuses("an ignore_tags entry of the wrong width is refused",
            lambda d: d["rfid"].update(ignore_tags=["31"]), "hex chars")
    refuses("silent_warn below recv_timeout is refused",
            lambda d: d["rfid"].update(silent_warn_s=0.5), "silent_warn_s")


def test_run_numbering():
    """Run directories are NNNN-auto_<stamp>, numbered from what is on disk.

    The sequence is the thing a human cites ("run 17"), so it has to be
    monotonic, gap-tolerant, and immune to two runs landing in the same second -
    which the bare timestamp scheme was not.
    """
    import shutil
    import tempfile
    import runlog
    print("\nrun log numbering")

    saved = runlog.LOG_DIR
    tmp = tempfile.mkdtemp()
    try:
        runlog.LOG_DIR = tmp
        check("an empty log directory starts at 1", runlog.next_seq(tmp) == 1)
        check("a missing log directory starts at 1",
              runlog.next_seq(os.path.join(tmp, "nope")) == 1)

        for n in (1, 7, 17):
            os.makedirs(os.path.join(tmp, f"{n:04d}-auto_20260901_120000"))
        check("numbering continues from the highest prefix present",
              runlog.next_seq(tmp) == 18, "0001/0007/0017 -> 18")

        os.makedirs(os.path.join(tmp, "auto_20260901_130000"))
        os.makedirs(os.path.join(tmp, "notes"))
        check("unprefixed entries are ignored", runlog.next_seq(tmp) == 18)

        os.makedirs(os.path.join(tmp, "10000-auto_20260901_120000"))
        check("the prefix survives passing 9999", runlog.next_seq(tmp) == 10001)

        shutil.rmtree(tmp)
        os.makedirs(tmp)
        dirs = []
        for _ in range(3):
            lg = runlog.RunLog()
            lg.open("numbering")
            lg.write({"state": "run", "e_mm": 1.0, "dt": 0.02}, {"loop_ms": 20.0})
            lg.close(plot=False)
            dirs.append(os.path.basename(lg.dir))
        check("consecutive runs number 1, 2, 3",
              [d[:4] for d in dirs] == ["0001", "0002", "0003"], " ".join(dirs))
        # The old bare-timestamp name collided here and the second run silently
        # overwrote the first one's CSV.
        check("runs in the same second get distinct directories",
              len(set(dirs)) == 3)

        shutil.rmtree(os.path.join(tmp, dirs[1]))
        lg = runlog.RunLog()
        lg.open()
        lg.close(plot=False)
        check("a deleted run leaves a gap, never a collision",
              os.path.basename(lg.dir).startswith("0004"),
              os.path.basename(lg.dir))

        # LOG_DIR must be read at call time; as a default argument it would
        # freeze at import and this redirect would be silently ignored.
        check("next_seq() honours a reassigned LOG_DIR",
              runlog.next_seq() == 5, str(runlog.next_seq()))
    finally:
        runlog.LOG_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)


def _why(g, index):
    """The refusal message, so a test can assert it explains itself."""
    try:
        g.check(index, 0x40)
        return ""
    except g.ForbiddenWrite as e:
        return str(e)


def test_can_monitoring():
    """Alarm decode, the write deny-list, and the round-robin poller.

    All pure tables and bookkeeping, so all testable without a bus. The wiring
    that puts them on the bus is checked in the two tests below.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "canbus"))
    import alarms
    import canmon
    import guard
    print("\nCAN monitoring: alarms, deny-list, poller")

    # -- EMCY decode -------------------------------------------------------
    a = alarms.decode_emcy(bytes([0x53, 0xFF, 0x81, 0, 0, 0, 0, 0]))
    check("the top-priority HWTO alarm decodes",
          a["name"] == "HWTO input circuit error" and a["level"] == "error"
          and a["tier"] == alarms.MUST, a["name"])
    check("the error register is decoded from byte 2",
          a["register_bits"] == ["generic", "manufacturer"],
          str(a["register_bits"]))
    # 0000h is the drive saying everything cleared, not a fault.
    clr = alarms.decode_emcy(bytes(8))
    check("0000h is a clear, not an alarm",
          clr["cleared"] and clr["level"] == "info")
    unk = alarms.decode_emcy(bytes([0x99, 0x99, 0, 0, 0, 0, 0, 0]))
    check("an unlisted code still reports as an error",
          not unk["cleared"] and unk["level"] == "error"
          and "9999" in unk["hex"], unk["name"])
    check("a short frame decodes rather than raising",
          alarms.decode_emcy(b"\x22\xff")["code"] == 0xFF22)
    check("decode_emcy never raises on random bytes",
          all(alarms.decode_emcy(bytes([i, i, i])) for i in range(0, 256, 17)))
    missing = [c for c in (0xFF53, 0xFF68, 0xFF50, 0xFF55, 0xFF22, 0xFF25,
                           0xFF21, 0xFF26, 0x8120, 0x8130, 0x8140, 0xFF31,
                           0xFF45, 0xFF41, 0xFFF0)
               if c not in alarms.EMCY_CODES]
    check("every MUST alarm from the plan is in the table", not missing,
          f"{len(alarms.EMCY_CODES)} codes"
          + (f", missing {[hex(c) for c in missing]}" if missing else ""))

    # -- statusword flags: ILA is how the FX3 quick stop becomes visible ----
    flags = {f["name"] for f in alarms.decode_statusword_flags(0x0800)}
    check("ILA decodes from statusword bit 11", flags == {"ILA"}, str(flags))
    check("a clear statusword yields no flags",
          alarms.decode_statusword_flags(0x0027) == [])
    check("decode_statusword_flags tolerates None",
          alarms.decode_statusword_flags(None) == [])
    check("NMT state decodes from the heartbeat byte",
          alarms.decode_nmt(0x05) == "Operational"
          and alarms.decode_nmt(0x7F) == "Pre-operational")

    # -- the write deny-list (monitoring plan section 8) --------------------
    check("the setpoint is writable", guard.is_allowed(0x60FF, 800))
    check("the controlword is writable", guard.is_allowed(0x6040, 0x000F))
    check("the heartbeat interval is writable", guard.is_allowed(0x1017, 200))
    # 403Eh bit 6 is FREE: it releases the holding brake on BOTH drive wheels.
    check("403Eh (FREE / brake release) is refused",
          not guard.is_allowed(0x403E, 0x40))
    check("40D0h (clear ETO / automatic restart) is refused",
          not guard.is_allowed(0x40D0, 1))
    check("40C0h (alarm reset) is refused", not guard.is_allowed(0x40C0, 1))
    check("1011h (restore defaults) is refused", not guard.is_allowed(0x1011, 1))
    check("1010h (store parameters) is refused", not guard.is_allowed(0x1010, 1))
    check("the whole 4xxxh parameter block is refused",
          not any(guard.is_allowed(i) for i in (0x4000, 0x40C6, 0x4123, 0x4FFF)))
    # 6040h is allowed, but bit 7 of it is fault reset by another name.
    check("controlword bit 7 (fault reset) is refused",
          not guard.is_allowed(0x6040, 0x0080))
    check("a refusal explains itself", "FREE" in _why(guard, 0x403E),
          _why(guard, 0x403E)[:60])
    check("an unlisted index is refused by default",
          not guard.is_allowed(0x1000, 1))

    # Every write in canworker must go through the guard, not around it.
    cw = pathlib.Path("canworker.py").read_text()
    check("_write() calls the guard", "guard_write(index, value)" in cw)
    direct = [ln.strip() for ln in cw.splitlines()
              if "sdo_write(" in ln and "def " not in ln and "guard" not in ln
              and not ln.strip().startswith(("#", "*", '"'))
              and "only ever call" not in ln]
    # _do_disarm calls sdo_write directly on the shutdown path, where raising
    # would leave the motors energised. Those are 6040h/60FFh only; the count
    # is pinned so a new bypass cannot slip in unnoticed.
    check("direct sdo_write calls are only the disarm path",
          len(direct) == 3, f"{len(direct)}: " + "; ".join(direct)[:110])
    check("no direct write targets a forbidden index",
          not any(f"0x{i:04X}" in "".join(direct) for i in guard.FORBIDDEN))

    # -- round-robin poller -------------------------------------------------
    pol = canmon.MonitorPoller([1, 2])
    seen = [pol.next_object()[1] for _ in range(len(canmon.OBJECTS))]
    check("a sweep visits every object exactly once",
          sorted(seen) == sorted(o[1] for o in canmon.OBJECTS),
          f"{len(seen)} objects")
    check("the cursor wraps and counts sweeps", pol.sweeps == 1)

    # Types come from the MANUAL, not the plan - the plan guessed 40A4h as
    # INT32 when it is INT16, and a 16-bit signed value read as 32-bit is
    # plausible-looking garbage rather than an error.
    check("40A4h is decoded as INT16 per the manual",
          canmon.OBJECT_BY_KEY["bus_v"][3] == "i16")
    check("409Bh is decoded as INT32 per the manual",
          canmon.OBJECT_BY_KEY["cur_a"][3] == "i32")
    check("a negative current decodes as regeneration",
          canmon._decode("i32", struct.pack("<i", -2500)) == -2500)
    check("an i16 sign bit is honoured",
          canmon._decode("i16", struct.pack("<h", -55)) == -55)
    check("a short payload decodes rather than raising",
          canmon._decode("i32", b"\x01") == 1)
    check("a None payload yields None", canmon._decode("i16", None) is None)

    pol.store(1, "bus_v", 482)
    pol.store(1, "drv_c", 723)
    pol.store(1, "mtr_c", 400)
    pol.store(2, "bus_v", 375)
    snap = pol.snapshot(config.MONITOR_THRESHOLDS)
    check("a raw reading is scaled to its unit",
          snap["nodes"]["1"]["bus_v"]["value"] == 48.2,
          str(snap["nodes"]["1"]["bus_v"]["value"]))
    check("a temperature over its warn threshold is flagged",
          snap["nodes"]["1"]["drv_c"]["state"] == "warn")
    check("a temperature under its warn threshold is not",
          snap["nodes"]["1"]["mtr_c"]["state"] == "ok")
    # Two-sided: low bus voltage is battery sag, and stopping distance was
    # already degraded before anything alarmed.
    check("bus voltage is flagged at the LOW end too",
          snap["nodes"]["2"]["bus_v"]["state"] == "warn",
          str(snap["nodes"]["2"]["bus_v"]["value"]))
    pol.store(1, "info", None)
    check("an unanswered read stores as blank, not zero",
          pol.snapshot()["nodes"]["1"]["info"]["value"] is None)


def test_unsolicited_frames_survive_sdo():
    """EMCY and heartbeat must reach their handlers even mid-SDO.

    This is the whole reason TpdoTap exists and the reason it had to grow.
    sdo_read() opens by draining the RX queue and then keeps only frames
    matching 0x580+node, discarding the rest - so any pushed frame class not
    routed by the tap is silently lost for as long as a transfer is in flight,
    which with a setpoint write most ticks is most of the time.
    """
    import canworker
    from verify_drivers import sdo_read
    print("\nunsolicited frames survive an SDO transfer")

    emcy, beats, pdos = [], [], []

    class _Bus:
        """Replays a fixed frame sequence, pushed frames mixed into the stream."""

        def __init__(self, frames):
            self._frames = list(frames)
            self.sent = []

        def send(self, msg):
            self.sent.append(msg)

        def recv(self, timeout=None):
            # sdo_read() drains with timeout=0 before transmitting. Returning
            # nothing then models an idle bus, so the scripted frames land
            # AFTER the request - which is the case under test.
            if not timeout:
                return None
            return self._frames.pop(0) if self._frames else None

        def shutdown(self):
            pass

    def msg(cob, data):
        return canworker.can.Message(arbitration_id=cob, data=bytes(data),
                                     is_extended_id=False)

    reply = [0x4B, 0x41, 0x60, 0, 0x27, 0x06, 0, 0]     # 6041h = 0x0627
    raw = _Bus([
        msg(0x080 + 1, [0x22, 0xFF, 0x81, 0, 0, 0, 0, 0]),   # EMCY, node 1
        msg(0x700 + 2, [0x05]),                              # heartbeat, node 2
        msg(config.TPDO1_COB, [0] * 8),                      # the MLS stream
        msg(0x580 + 1, reply),                               # the SDO reply
    ])
    tap = canworker.TpdoTap(raw, on_pdo=lambda m: pdos.append(m),
                            on_emcy=lambda n, d: emcy.append((n, d)),
                            on_heartbeat=lambda n, b: beats.append((n, b)),
                            nodes=[1, 2])

    st, val, _, _ = sdo_read(tap, 1, 0x6041, 0, collision_window=0.0)
    check("the SDO reply still gets through", st is True and val is not None)
    check("an EMCY mid-transfer reaches its handler",
          len(emcy) == 1 and emcy[0][0] == 1, str(emcy)[:60])
    check("a heartbeat mid-transfer reaches its handler",
          beats == [(2, 0x05)], str(beats))
    check("the sensor stream is still routed", len(pdos) == 1)

    # A handler that throws must not break the bus thread - these run inside
    # somebody else's SDO transfer.
    boom = canworker.TpdoTap(
        _Bus([msg(0x080 + 1, [0] * 8), msg(0x580 + 1, reply)]),
        on_pdo=lambda m: None, on_emcy=lambda n, d: 1 / 0,
        on_heartbeat=lambda n, b: None, nodes=[1])
    st, _, _, _ = sdo_read(boom, 1, 0x6041, 0, collision_window=0.0)
    check("a throwing handler cannot break the transfer", st is True)

    # A frame we do not route must be handed back, not swallowed.
    passthru = canworker.TpdoTap(_Bus([msg(0x580 + 1, reply)]),
                                 on_pdo=lambda m: None, nodes=[])
    check("an unrouted frame is returned to the caller",
          passthru.recv(timeout=0.1) is not None)


def test_monitor_page_does_not_feed_the_watchdog():
    """A read-only page must not hold an auto run alive.

    /api/state used to call keepalive() unconditionally, so ANY page polling it
    fed the auto watchdog - meaning a monitoring page open on a second screen
    would keep a run going after the auto page had been closed. The heartbeat is
    now opt-in, and forgetting the flag stops the run rather than extending it.
    """
    import app as webapp
    print("\nthe monitoring page cannot hold a run alive")

    seen = []
    real = webapp.ctl.keepalive
    webapp.ctl.keepalive = lambda: seen.append(1)
    try:
        c = webapp.app.test_client()
        c.get("/api/state")
        check("/api/state alone does NOT refresh the watchdog", not seen,
              f"{len(seen)} refresh(es)")
        c.get("/api/can")
        check("/api/can does NOT refresh the watchdog", not seen)
        c.get("/api/state?hb=1")
        check("/api/state?hb=1 DOES refresh the watchdog", len(seen) == 1)
    finally:
        webapp.ctl.keepalive = real

    # Only the page that drives the vehicle may claim it.
    auto = pathlib.Path("templates/auto.html").read_text()
    mon = pathlib.Path("templates/monitor.html").read_text()
    common = pathlib.Path("static/common.js").read_text()
    check("the auto page claims the heartbeat", "CLAIM_HEARTBEAT = true" in auto)
    check("the monitor page does not", "CLAIM_HEARTBEAT" not in mon)
    check("the claim is declared before common.js polls",
          "prescript" in auto and "prescript" in
          pathlib.Path("templates/base.html").read_text())
    check("common.js only sends hb=1 when the page claims it",
          "CLAIM_HEARTBEAT ? '/api/state?hb=1'" in common)

    # The page itself must render and be read-only.
    c = webapp.app.test_client()
    body = c.get("/monitor").get_data(as_text=True)
    check("the monitor page renders", "Diagnostic only" in body)
    check("it states the golden rule", "not a safety path" in body)
    check("it publishes the write deny-list", "403Eh" in body and "40D0h" in body)
    check("it has no controls", "<button" not in body)


def main():
    print(f"autopilot config: K_RATIO={config.K_RATIO} KD={config.KD} "
          f"KI={config.KI} zeta={autopilot.predicted_zeta():.3f} "
          f"DRY_RUN={config.DRY_RUN}")
    test_kinematics_roundtrip()
    test_no_derivative_kick_on_reset()
    test_sensor_slew_guard()
    test_conditional_integration()
    test_line_loss_grace()
    test_stale_sensor_is_not_line_loss()
    test_joint_saturation_preserves_ratio()
    test_inner_wheel_floor()
    test_step_response()
    test_divergence_is_detectable()
    test_config_profile()
    test_derived_constants()
    test_health()
    test_sensor_starts_in_every_mode()
    test_grace_is_a_distance_not_a_time()
    test_speed_reduction_is_a_fraction()
    test_loop_health()
    test_event_log()
    test_arm_does_not_deadlock()
    test_run_plot()
    test_run_numbering()
    test_rfid()
    test_can_monitoring()
    test_unsolicited_frames_survive_sdo()
    test_monitor_page_does_not_feed_the_watchdog()

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: " + ", ".join(FAIL))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
