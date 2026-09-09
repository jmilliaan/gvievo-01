"""The bus thread: arming, locking, frame routing, loop timing."""
import math
import os
import pathlib
import struct
import sys
import threading

from helpers import FAIL, ROOT, check, _FakeRaw, sensor

import autopilot
import config
import kinematics
import motion

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
    src = (ROOT / "canworker.py").read_text().split("\n")
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


def test_sensor_starts_in_every_mode():
    """The tape strip is shown on the manual page too, which only works if the
    sensor is NMT-started on a manual arm - it used to be auto-only."""
    print("\nsensor bring-up is mode-independent")
    src = (ROOT / "canworker.py").read_text()
    check("_start_sensor() exists", "def _start_sensor(self):" in src)
    check("no sensor NMT start left behind a mode test",
          'if mode == "auto":\n            self._nmt(0x01, config.SENSOR_NODE)'
          not in src)
    check("both arm paths call it", src.count("self._start_sensor()") == 2,
          f"{src.count('self._start_sensor()')} call sites")
    check("field level polls whenever armed, not only in auto",
          "if armed and now - t_field" in src)


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


def test_horn_follows_commanded_motion():
    """DO high whenever motion is commanded, in either mode, and never else."""
    print("\ncanworker: the horn")
    import canworker

    class FakeDio:
        def __init__(self):
            self.calls = []

        def set_coil(self, ch, value, hold_s):
            self.calls.append((ch, value, hold_s))

    ctl = canworker.Controller()
    fake = FakeDio()
    ctl._dio = fake

    def horn(armed, target):
        fake.calls.clear()
        ctl._update_horn(armed, target)
        check_ch = [c for c in fake.calls if c[0] == config.HORN_DO_CHANNEL]
        return check_ch[-1][1] if check_ch else None

    check("a jog sounds it", horn(True, (600, 600)) is True)
    check("so does a spin, where the wheels oppose each other and the vehicle "
          "does not go anywhere a bystander expects",
          horn(True, (600, -600)) is True)
    check("an auto run sounds it - the same vehicle, so the same warning",
          horn(True, (800, 810)) is True)
    check("a single creeping wheel still counts as motion",
          horn(True, (0, 40)) is True)

    check("armed and holding zero is silent - arming is not motion",
          horn(True, (0, 0)) is False)
    check("a disarmed vehicle is silent", horn(False, (0, 0)) is False)
    # The interlock, stated rather than implied. A setpoint left standing from
    # before a disarm must not sound the horn on a vehicle that cannot move.
    check("...even if a setpoint is somehow still standing",
          horn(False, (600, 600)) is False)

    check("the command carries the renewal deadline, so a dead tick drops it",
          fake.calls[-1][2] == config.HORN_HOLD_S, str(fake.calls[-1]))

    # Renewed every tick, not written on the edge - that is what makes the
    # deadline in dio.set_coil() a live watchdog rather than a formality.
    fake.calls.clear()
    for _ in range(5):
        ctl._update_horn(True, (600, 600))
    check("a held jog renews the claim every tick", len(fake.calls) == 5)

    # And the policy has to be ON the tick, not merely available to it.
    src = (ROOT / "canworker.py").read_text()
    body = src[src.index("def _run(self)"):src.index("def _update_horn")]
    check("_run() calls it on every tick, outside any armed-only branch",
          "self._update_horn(armed, target)" in body)

    horn_at = src.index("self._update_horn(armed, target)")
    check("and does so BEFORE the setpoint reaches the wheels",
          horn_at < src.index("self._write_target(target)", horn_at))


def test_a_safety_stop_is_logged_even_though_it_is_not_a_fault():
    """An HWTO/STO stop must leave a trace, and the fault edge cannot provide one.

    The BLVD-KRD manual lists "HWTO signal input is active" as the cause of
    CiA 402 transitions 7, 9, 10 and 12 - ordinary moves out of Operation
    enabled. A fault is transition 13, a separate path. So the safety chain
    removing torque leaves the FAULT bit clear and 1001h at zero, and the
    existing fault-edge logger stays silent: the vehicle stops and the event
    log shows nothing, which reads as a vehicle that stopped for no reason.

    This is the regression that matters, so it is driven through the real
    _poll_telemetry() with the statusword a stopped drive actually reports.
    """
    import canworker
    import config
    import events
    print("\nan STO stop is logged even though the drive calls it no fault")

    ctl = canworker.Controller()
    words = {}

    def fake_read(nid, index, sub=0, **kw):
        if index == 0x6041:
            return words[nid]
        if index == 0x1001:
            return 0            # error register CLEAR - this is not a fault
        if index == 0x603F:
            return 0            # no alarm code either: plain loss of torque
        return 0

    ctl._read = fake_read
    ctl._read_i32 = lambda nid, index, sub=0, **kw: 0

    # Running normally.
    for n in config.NODES:
        words[n] = 0x1737
    ctl._poll_telemetry()
    check("a drive in Operation enabled decodes as such",
          all(ctl._telemetry[n]["state"] == "Operation enabled"
              for n in config.NODES))
    events.clear()
    ctl._poll_telemetry()
    check("a steady state logs nothing - the edge really is an edge",
          not events.since(0)[1], str(events.since(0)[1]))

    # The safety chain takes torque away.
    events.clear()
    for n in config.NODES:
        words[n] = 0x0040                       # Switch on disabled
    ctl._poll_telemetry()
    msgs = [e["msg"] for e in events.since(0)[1]]

    check("*** the drive does NOT call this a fault ***",
          all(not ctl._telemetry[n]["fault"] for n in config.NODES)
          and all(not ctl._telemetry[n]["error_reg"] for n in config.NODES),
          "so the FAULT-bit logger has nothing to report")
    check("...and indeed no FAULT event is emitted",
          not any("FAULT" in m for m in msgs), str(msgs))
    check("*** but the state transition IS logged, per node ***",
          sum("Operation enabled -> Switch on disabled" in m for m in msgs)
          == len(config.NODES), str(msgs))
    check("...as a warning, because leaving Operation enabled while armed is "
          "something this software did not do",
          all(e["level"] == "warn" for e in events.since(0)[1]
              if "Operation enabled ->" in e["msg"]))
    check("...naming the statusword and the error code, which is what tells a "
          "plain loss of torque from an HWTO alarm",
          all("statusword 0x0040" in m and "error code 0x0000" in m
              for m in msgs if "Operation enabled ->" in m), str(msgs))

    # Coming back is worth a line too, and a quieter one.
    events.clear()
    for n in config.NODES:
        words[n] = 0x1737
    ctl._poll_telemetry()
    back = [e for e in events.since(0)[1] if "-> Operation enabled" in e["msg"]]
    check("the drives coming back is logged as well",
          len(back) == len(config.NODES), str(back))
    check("...at info, because that direction is the recovery",
          all(e["level"] == "info" for e in back))
    events.clear()


def test_a_safety_stop_holds_the_run_and_resumes_itself():
    """*** This vehicle RESUMES BY ITSELF after a protective-field stop. ***

    That is a deliberate policy choice and the opposite of what every other
    involuntary stop here does, so the properties are pinned rather than left
    to read off the code: the run is HELD and not ended, the wheels are at zero
    for the whole hold, the resume waits auto_start_delay_s, and a latched
    fault stops the whole thing dead.

    The detection matters as much as the resume. An HWTO stop keeps answering
    CAN, keeps the FAULT bit clear and keeps 1001h at zero, so nothing else in
    this file can see it - runs 0048/0049 sat commanding ~950 r/min into
    de-energised drives for 9 and 19 seconds because of exactly that.
    """
    import time
    import canworker
    import config
    import events
    print("\na safety stop holds the run, then resumes it by itself")

    ctl = canworker.Controller()
    ctl._armed, ctl._mode = True, "auto"
    ctl._auto_running = True
    ctl._follower._v_rpm = config.AUTO_RPM

    ok = {"enable": False}
    ctl._reenable_drives = lambda: ok["enable"]

    def drives(state):
        """0x1737 = Operation enabled, 0x1270 = the HWTO signature."""
        for n in config.NODES:
            ctl._telemetry[n]["statusword"] = state

    # -- running normally --------------------------------------------------
    drives(0x1737)
    ctl._eto_scan()
    check("a healthy run is not held", ctl._eto_hold is None)

    # -- the chain takes torque away --------------------------------------
    events.clear()
    drives(0x1270)
    ctl._eto_scan()
    check("*** the run NOTICES - this is what runs 0048/0049 could not do ***",
          ctl._eto_hold is not None, str(ctl._eto_hold))
    check("*** and it is a HOLD, not the end of the run ***",
          ctl._auto_running is True,
          "ending it would close the log and lose the lap")
    check("the wheels go to zero", ctl._target == (0, 0), str(ctl._target))
    check("...and the ramp is collapsed, so the resume starts from rest "
          "rather than from the setpoint it was carrying",
          ctl._follower._v_rpm == 0, f"{ctl._follower._v_rpm}")
    check("the reason names the chain", "safety chain" in ctl._eto_hold)
    check("it says so once, on the edge", len(events.since(0)[1]) == 1,
          str(events.since(0)[1]))
    ctl._eto_scan()
    check("...and holding is silent after that", len(events.since(0)[1]) == 1)

    # -- a chain that stays open just keeps retrying -----------------------
    ctl._arm_retry_at = 0.0
    ctl._eto_scan()
    check("a failed re-enable does not end the run",
          ctl._auto_running is True and ctl._eto_hold is not None)
    check("...and schedules no resume", ctl._eto_resume_at == 0.0)

    # -- a latched fault outranks the whole mechanism ----------------------
    ctl._fault = "somebody pressed something"
    ctl._arm_retry_at = 0.0
    ok["enable"] = True
    ctl._eto_scan()
    check("*** a latched fault blocks the automatic resume ***",
          ctl._eto_resume_at == 0.0,
          "anything that latched a fault wanted a human, and this must not "
          "talk it round")
    ctl._fault = None

    # -- torque comes back -------------------------------------------------
    events.clear()
    ctl._arm_retry_at = 0.0
    ctl._eto_scan()
    check("torque restored schedules a resume", ctl._eto_resume_at > 0)
    check("...after the same delay a Start press gets, not instantly",
          ctl._eto_resume_at - time.monotonic()
          > config.AUTO_START_DELAY_S - 0.05,
          f"{config.AUTO_START_DELAY_S} s")
    check("...and warns that it is about to move on its own",
          any("BY ITSELF" in e["msg"] for e in events.since(0)[1]),
          str([e["msg"] for e in events.since(0)[1]]))
    check("still held until the delay is up", ctl._eto_hold is not None)

    ctl._eto_resume_at = time.monotonic() - 0.001
    ctl._eto_scan()
    check("*** then the run carries on, with no button pressed ***",
          ctl._eto_hold is None and ctl._auto_running is True)
    check("the watchdog deadline is refreshed on the way out, or the resume "
          "would trip it immediately", ctl._deadline > time.monotonic())

    # -- a hold cannot outlive its run -------------------------------------
    drives(0x1270)
    ctl._eto_scan()
    check("it can hold again later in the same run", ctl._eto_hold is not None)
    ctl._end_auto_run("auto run STOP (operator)", hard=True)
    check("ending the run drops the hold", ctl._eto_hold is None
          and ctl._eto_resume_at == 0.0)

    # -- and it only ever applies to an auto run ---------------------------
    ctl._mode, ctl._auto_running = "manual", False
    drives(0x1270)
    ctl._eto_scan()
    check("a manual jog is not held by this - manual has its own re-arm",
          ctl._eto_hold is None)
    events.clear()


TESTS = [
    test_arm_does_not_deadlock,
    test_sensor_starts_in_every_mode,
    test_loop_health,
    test_unsolicited_frames_survive_sdo,
    test_horn_follows_commanded_motion,
    test_a_safety_stop_is_logged_even_though_it_is_not_a_fault,
    test_a_safety_stop_holds_the_run_and_resumes_itself,
]
