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


TESTS = [
    test_arm_does_not_deadlock,
    test_sensor_starts_in_every_mode,
    test_loop_health,
    test_unsolicited_frames_survive_sdo,
]
