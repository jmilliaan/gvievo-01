"""Single-threaded owner of can0. Every CAN frame in this app goes through here.

Flask request handlers never touch the bus. They mutate a setpoint under a lock
(cheap, non-blocking) or push a slow action onto a queue and wait on a Future.
One thread owns the bus because:

  * an SDO transfer is a send/recv PAIR that must not interleave with another
    one - two threads doing SDO at once will read each other's replies;
  * verify_drivers.sdo_read() drains the RX queue before transmitting, so a
    second reader would have its frames eaten out from under it.

Reuses the proven helpers rather than reimplementing CANopen:
  verify_drivers.open_bus / sdo_read / u32     bus discovery + SDO upload
  drive_forward.sdo_write / CW_* / SW_*        SDO download + CiA 402 words
  bus_health.decode_state                      statusword -> state name
  rpdo.pack / configure                        RPDO1 setpoint frames
"""
import os
import queue
import struct
import sys
import threading
import time
from concurrent.futures import Future

# The layer directories are put on sys.path rather than made into packages, so
# every module keeps importing its neighbours by bare name. That is what lets
# drivers/canbus/ still run standalone on a bench: its modules import each other
# as `verify_drivers`, not `drivers.canbus.verify_drivers`, and as a package
# they would resolve twice under two different names.
#
# The cost is that module BASENAMES are one flat namespace across these
# directories. Two modules may never share a name and none may shadow a stdlib
# module; tests/test_layout.py enforces it.
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _d in ("", "core", "drivers", os.path.join("drivers", "canbus")):
    sys.path.insert(0, os.path.join(_ROOT, _d) if _d else _ROOT)

import can  # noqa: E402
from alarms import (decode_emcy, decode_nmt,  # noqa: E402
                    decode_statusword_flags)
from bus_health import decode_state  # noqa: E402
from guard import check as guard_write  # noqa: E402
from drive_forward import (CW_DISABLE_VOLTAGE, CW_ENABLE, CW_SHUTDOWN,  # noqa: E402
                           CW_SWITCH_ON, SW_FAULT, SW_REMOTE,
                           SW_SPEED_IS_ZERO, sdo_write)
import rpdo  # noqa: E402
from verify_drivers import open_bus, sdo_read, u32  # noqa: E402

import canmon  # noqa: E402
import config  # noqa: E402
import events  # noqa: E402
import health  # noqa: E402
import motion  # noqa: E402
import dio  # noqa: E402
import lidar  # noqa: E402
import panel  # noqa: E402
import rfid  # noqa: E402

# Node IDs, driver ramp rates, watchdogs and loop periods all come from the
# vehicle profile - see config.py's TUNING NOTES for the reasoning behind the
# values, and profiles/<AGV_PROFILE>.json to change them.

# How long to wait before retrying an auto-arm that failed. Not a vehicle
# parameter: it is "slow enough not to hammer the bus". An arm attempt is
# ~20 blocking SDO round-trips, and the common reason for failing one is a
# safety chain holding the drives in ETO - a condition that lasts as long as
# it lasts, so retrying it at tick rate would spend the whole bus thread on
# a question whose answer cannot change quickly.
ARM_RETRY_S = 2.0


def _battery(mon):
    """Pack voltage for the shared rail: the WORST of the two drives.

    Both amplifiers sit on the same battery, so the two readings are the same
    quantity measured twice. Showing the lower one is the honest summary - and
    showing an average would let a drive reading 38 V hide behind one reading 49.

    canmon already applies the profile's two-sided thresholds, so the state comes
    from there rather than being re-derived against a second copy of the limits.
    """
    worst_v, state, warn_low = None, "ok", None
    rank = {"ok": 0, "warn": 1, "trip": 2}
    for node in (mon.get("nodes") or {}).values():
        bv = node.get("bus_v") or {}
        v = bv.get("value")
        if v is None:
            continue
        warn_low = bv.get("warn_low") if warn_low is None else warn_low
        if worst_v is None or v < worst_v:
            worst_v = v
        if rank.get(bv.get("state"), 0) > rank.get(state, 0):
            state = bv.get("state")
    return {"volts": worst_v, "state": state, "warn_low": warn_low}


class TpdoTap:
    """Bus wrapper that routes every UNSOLICITED frame before the SDO helpers
    can discard it.

    sdo_read() and sdo_write() only ever call .send() and .recv() on the object
    they are given, so passing this in lets both be reused verbatim while the
    pushed traffic still reaches its decoder.

    *** This is the only thing standing between a pushed frame and the bin. ***
    Both SDO helpers open with a "drain anything stale" loop and then keep only
    frames matching 0x580+node, discarding everything else. So any frame class
    not routed HERE is silently lost for as long as an SDO transfer is in
    flight - which, with a setpoint write most ticks and six telemetry reads
    every 200 ms, is most of the time.

    Routed:
        0x080 + n    EMCY - alarms, pushed one per error event
        0x700 + n    heartbeat - the only thing that tells a dead driver apart
                     from an idle one
    Everything else is handed back to the caller, which is how SDO replies get
    home.

    *** This is where pushed telemetry lands when it arrives. *** The 5 Hz
    _poll_telemetry() burst is six blocking SDO reads inside one 20 ms tick and
    is the largest remaining spike in the loop; moving the statusword and actual
    velocity onto drive TPDOs (0x180+n / 0x280+n) is one more entry in the table
    below, which is exactly what this class was shaped for. See
    manuals/codebase-improvement.md section 3.
    """

    def __init__(self, bus, on_emcy=None, on_heartbeat=None, nodes=()):
        self._bus = bus
        self._on_emcy = on_emcy
        self._on_heartbeat = on_heartbeat
        # Built once: a dict lookup per frame, on a path that sees every frame
        # on the bus at 100+ Hz.
        self._route = {}
        for nid in nodes:
            if on_emcy is not None:
                self._route[0x080 + nid] = ("emcy", nid)
            if on_heartbeat is not None:
                self._route[0x700 + nid] = ("hb", nid)

    def send(self, msg):
        self._bus.send(msg)

    def recv(self, timeout=None):
        deadline = None if timeout is None else time.perf_counter() + timeout
        while True:
            remaining = (None if deadline is None
                         else max(0.0, deadline - time.perf_counter()))
            m = self._bus.recv(timeout=remaining)
            if m is None:
                return None
            hit = self._route.get(m.arbitration_id)
            if hit is not None:
                kind, nid = hit
                # A handler must never break the bus thread, and these run
                # inside somebody else's SDO transfer.
                try:
                    if kind == "emcy":
                        self._on_emcy(nid, bytes(m.data))
                    else:
                        self._on_heartbeat(nid, m.data[0] if m.data else 0)
                except Exception:               # noqa: BLE001
                    pass
                continue
            return m

    def shutdown(self):
        self._bus.shutdown()


class _LoopHealth:
    """Rolling loop-timing window for the bus thread.

    Separates two things that a single "loop time" number confuses:

      work_ms   how long the iteration spent doing things - SDO round-trips,
                telemetry, monitoring. This is the number that grows when the
                bus gets slow, and it is the one to watch when the RPDO1 and
                TPDO migrations land: both exist to shrink it.
      period_ms the interval actually achieved between iterations.

    Measured on tape-following runs 0023-0025, this loop ran a p50 of 20.1 ms
    against a 20 ms budget but a p95 of 28.1 and a max of 37.9, and the tail was
    almost entirely the 5 Hz telemetry burst. That measurement is the reason
    work_ms and period_ms are reported separately rather than as one number -
    see manuals/codebase-improvement.md section 1.

    Pure arithmetic on the bus thread; it never touches the lock or the bus.
    """

    def __init__(self, window=50):
        self.window = window          # ~1 s at 50 Hz
        self._reset()
        self._prev_iter = None

    def _reset(self):
        self._work = []
        self._period = []

    def tick(self, t_iter, spent):
        """Returns a stats dict once per window, else None."""
        if self._prev_iter is not None:
            self._period.append((t_iter - self._prev_iter) * 1000.0)
        self._prev_iter = t_iter
        self._work.append(spent * 1000.0)

        if len(self._work) < self.window:
            return None
        stats = {
            "work_avg_ms": sum(self._work) / len(self._work),
            "work_max_ms": max(self._work),
            "period_avg_ms": (sum(self._period) / len(self._period)
                              if self._period else None),
            "period_max_ms": max(self._period) if self._period else None,
        }
        self._reset()
        return stats


class Controller:
    """Owns the bus thread and the vehicle state machine."""

    def __init__(self):
        # RLock, not Lock. Any bus read can re-enter this class: sdo_read()
        # drains the RX queue, TpdoTap hands pushed frames to _on_emcy() /
        # _on_heartbeat(), and both take this lock. Holding a plain Lock across
        # a bus call
        # therefore self-deadlocks the bus thread, which wedges every Flask
        # request too (snapshot() and keepalive() both take it). Bus I/O is kept
        # out of locked sections as the real fix; this is the backstop.
        self._lock = threading.RLock()
        self._q = queue.Queue()
        self._stop_evt = threading.Event()
        self._thread = None

        self.bus = None
        self.how = None
        self.error = None

        self._armed = False
        self._mode = "idle"          # idle | manual
        self._direction = "stop"
        self._target = (0, 0)
        self._applied = None
        self._deadline = 0.0
        self._last_stop_reason = None

        self._telemetry = {n: {"statusword": None, "state": "-", "rpm": None,
                               "error_reg": None} for n in config.NODES}
        # Last reported fault state per node, so _poll_telemetry emits one event
        # per edge rather than one per 5 Hz poll. This is the driver's OWN fault
        # bit; whether the driver is still answering at all is health.py's job.
        self._fault_seen = {n: False for n in config.NODES}

        # Hardware health. One table, one place to add the next device - see
        # health.py for why this is not three more if-statements, and for why it
        # is emphatically not the browser watchdog above.
        self._hw = health.HealthMonitor()
        self._src_node = {
            n: self._hw.add(health.HealthSource(f"driver:{n}", critical=True,
                                                detail=f"node {n} "
                                                       f"({config.NODES[n]})"),
                            config.DRIVER_TIMEOUT_S)
            for n in config.NODES}
        self._health = {}

        # Drive monitoring. Diagnostic only - see manuals/can-monitoring-plan.txt
        # and canmon.py. The poller is pure bookkeeping; this class does the
        # actual SDO read, one object per node per tick.
        self._mon = canmon.MonitorPoller(config.NODES)
        self._alarms = {n: None for n in config.NODES}   # latest decoded EMCY
        self._nmt_state = {n: None for n in config.NODES}
        self._emcy_seen = 0

        # Loop health, published for the UI. Answers "is the tick late, and if so
        # is it the controller or the bus?" - work_ms is time spent doing things,
        # period_ms is the interval actually achieved. We diagnosed a 70 ms
        # telemetry stall by hand from a CSV column once; this makes it visible.
        self._loop = {"work_avg_ms": None, "work_max_ms": None,
                      "period_avg_ms": None, "period_max_ms": None,
                      "target_ms": config.LOOP_PERIOD_S * 1000.0}

        # Station tags. Its own thread and its own socket - the control tick
        # only ever reads rfid.snapshot(), never touches the network.
        #
        # The reader survives tape following, but its JOB changes. It used to
        # drive the junction ladder; under SLAM it answers the kidnapped-robot
        # problem - a known tag collapses the pose hypothesis space to one
        # region and lets a localiser converge. It returns IDENTITY, not pose,
        # so anything downstream must treat a read as a wide-covariance seed
        # rather than a correction (hardware-reconciliation.md D-4).
        self._rfid = rfid.RfidLink()
        # Pulled rather than pushed: the link already tracks its own health on
        # its own thread, and copying that verdict beats defining "healthy" for
        # the reader twice. Registered unconditionally - snapshot() reports a
        # None verdict while rfid.enabled is false, which health.py reads as
        # "not in use" and never counts against a mode.
        self._hw.add(health.PullSource("rfid", self._rfid.snapshot),
                     config.RFID_SILENT_WARN_S)

        # Digital I/O, same arrangement: its own thread, its own socket, pulled
        # for health. Non-critical, so a dead module never holds manual
        # jogging hostage to a device manual does not use.
        #
        # Note the shared cable: the RFID reader is daisy-chained through this
        # module, so losing it reports BOTH sources at once. That pairing is
        # the signature of a cable or a power fault rather than two devices
        # failing together, and it is only visible because both are registered.
        self._dio = dio.DioLink()
        self._hw.add(health.PullSource("dio", self._dio.snapshot),
                     config.DIO_SILENT_WARN_S)

        # Safety lidar, data output only. Same arrangement again: own thread,
        # own socket, pulled for health.
        #
        # NON-CRITICAL, and more than that: nothing consumes it. The scanner
        # stops the vehicle through its OSSD pair into the FX3, in hardware,
        # and the manual is explicit that this Ethernet data must not be used
        # for safety. So a dead scanner here is a display fault - it must not
        # stop the vehicle, and must not block arming either, because doing so
        # would put a non-safety data path in the way of manual recovery.
        #
        # The sec 4 rule ("absence of data is never clear") is therefore
        # enforced at the CONSUMERS - today only the /lidar page, which renders
        # a stale stream as occupied rather than as clear.
        self._lidar = lidar.LidarLink()
        self._hw.add(health.PullSource("lidar", self._lidar.snapshot),
                     config.LIDAR_SILENT_WARN_S)

        # Operator panel. Scanned from the DI image every tick in _run(), in
        # every state - the panel is what ENTERS a state, so it has to be read
        # while idle.
        self._panel = panel.PanelScan(
            config.PANEL_DI_RESET, config.PANEL_DI_START, config.PANEL_DI_AUTO,
            config.PANEL_DEBOUNCE_SCANS)
        # A latched involuntary stop. Start is refused until Reset clears it, so
        # a vehicle that stopped itself cannot be restarted by somebody who did
        # not see why. A DELIBERATE stop is not a fault and does not latch.
        self._fault = None
        # MANUAL is an armed state (panel.manual_auto_arm): the selector sitting
        # there is the arm command, so arming is a level to be maintained rather
        # than an edge somebody presses. _arm_retry_at backs off a failed attempt
        # - see ARM_RETRY_S - and _arm_fail carries the last reason for the UI.
        self._arm_retry_at = 0.0
        self._arm_fail = None
        self._last_action = None        # (what, source) for the UI

    # ---- lifecycle ------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="can", daemon=True)
        self._thread.start()
        self._rfid.start()          # no-op while rfid.enabled is false
        self._dio.start()           # likewise while dio.enabled is false
        self._lidar.start()         # likewise while lidar.enabled is false

    def shutdown(self):
        self._stop_evt.set()
        self._rfid.stop()
        self._dio.stop()
        self._lidar.stop()
        if self._thread:
            self._thread.join(timeout=6.0)

    def submit(self, action, *args, timeout=15.0):
        """Run a slow action on the bus thread and wait for it."""
        fut = Future()
        self._q.put((action, args, fut))
        return fut.result(timeout=timeout)

    # ---- called from Flask threads --------------------------------------

    def drive(self, direction):
        """Set a manual direction and refresh the watchdog. Non-blocking."""
        if not motion.is_direction(direction):
            raise ValueError(f"unknown direction {direction!r}")
        with self._lock:
            if self._mode != "manual":
                raise RuntimeError("not in manual mode")
            if not self._armed:
                raise RuntimeError("not armed")
            self._direction = direction
            self._target = motion.velocities(direction)
            self._deadline = time.monotonic() + config.MANUAL_WATCHDOG_S
            self._last_stop_reason = None

    def halt(self):
        """Zero the setpoint but stay armed."""
        with self._lock:
            self._direction = "stop"
            self._target = (0, 0)
            self._deadline = time.monotonic() + config.MANUAL_WATCHDOG_S

    def lidar_cloud(self, step=None):
        """The decimated point cloud, decoded on the CALLING (Flask) thread.

        Deliberately not part of snapshot() and deliberately not held under this
        object's lock: decoding 1652 points costs ~250 us, and doing that on the
        bus thread - or while holding the lock the bus thread needs - would put a
        browser refresh inside the control tick's 20 ms budget.
        """
        return self._lidar.cloud(step)

    def _alarm(self, mon, flags):
        """The one-line verdict every page shows. Caller holds the lock.

        Ranked, because "something is wrong" is useless if it cannot say how
        wrong. The order is the order an operator acts in:

          error  a latched fault, a lost critical device, an EMCY alarm still
                 standing, or a monitored value past its TRIP limit. The vehicle
                 has stopped or should.
          warn   a non-critical device lost (auto unavailable, manual fine), a
                 statusword warning flag, or a value past its WARN limit.
          ok     nothing outstanding.

        Deliberately reports the FIRST reason at each level rather than all of
        them: the rail is one line, and the alarms page carries the full list.
        """
        hw = self._health or {}

        if self._fault:
            return {"level": "error", "active": True, "detail": self._fault,
                    "source": "fault"}
        if hw.get("system_error"):
            return {"level": "error", "active": True,
                    "detail": hw.get("system_detail") or "critical device lost",
                    "source": "health"}
        for nid in config.NODES:
            al = self._alarms.get(nid)
            if al and al.get("level") == "error":
                return {"level": "error", "active": True,
                        "detail": f"node {nid} {al.get('name') or al.get('hex')}",
                        "source": "emcy"}
        for node_id, vals in (mon.get("nodes") or {}).items():
            for key, v in vals.items():
                if v.get("state") == "trip":
                    return {"level": "error", "active": True,
                            "detail": f"node {node_id} {v.get('label')} "
                                      f"{v.get('value')}{v.get('unit')}",
                            "source": "monitor"}

        if hw.get("sensor_error"):
            return {"level": "warn", "active": True,
                    "detail": hw.get("sensor_detail") or "sensor lost",
                    "source": "health"}
        for node_id, vals in (mon.get("nodes") or {}).items():
            for key, v in vals.items():
                if v.get("state") == "warn":
                    return {"level": "warn", "active": True,
                            "detail": f"node {node_id} {v.get('label')} "
                                      f"{v.get('value')}{v.get('unit')}",
                            "source": "monitor"}
        for node_id, fl in (flags or {}).items():
            for f in fl:
                if f.get("level") in ("warn", "error"):
                    return {"level": "warn", "active": True,
                            "detail": f"node {node_id} {f.get('name')}",
                            "source": "statusword"}

        return {"level": "ok", "active": False, "detail": "", "source": None}

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            # Built once and shared: the rail below and the /monitor detail read
            # the same sweep, so they can never disagree about a voltage.
            mon = self._mon.snapshot(config.MONITOR_THRESHOLDS)
            flags = {str(n): decode_statusword_flags(
                         self._telemetry[n].get("statusword"))
                     for n in config.NODES}
            return {
                "connected": self.bus is not None,
                "how": self.how,
                "error": self.error,
                "armed": self._armed,
                "mode": self._mode,
                "direction": self._direction,
                "target": {"left": self._target[0], "right": self._target[1]},
                "watchdog_s": max(0.0, self._deadline - now) if self._armed else 0.0,
                "stop_reason": self._last_stop_reason,
                "nodes": {
                    str(n): dict(self._telemetry[n], label=config.NODES[n]) for n in config.NODES
                },
                "rpm_profile": {"full": config.MANUAL_FULL_RPM,
                                "half": config.MANUAL_HALF_RPM},
                "loop": dict(self._loop),
                # Just the high-water mark. The UI fetches /api/events only when
                # this moves, so a quiet vehicle costs no extra requests.
                "rfid": self._rfid.snapshot(),
                "dio": self._dio.snapshot(),
                # Summary only - never the 1652-point cloud. Every page polls
                # /api/state five times a second; the cloud goes out on
                # /api/lidar, which only the lidar page asks for.
                "lidar": self._lidar.snapshot(),
                "panel": {"enabled": config.PANEL_ENABLED,
                          "selector": self._panel.mode(),
                          "fault": self._fault,
                          "auto_arm": config.PANEL_MANUAL_AUTO_ARM,
                          "arm_fail": self._arm_fail,
                          "last_action": self._last_action},
                "health": self._health,
                # The shared rail every page shows. Derived here rather than in
                # the browser so all four pages agree on what "alarm" means -
                # three pages computing it three ways is three chances to have
                # one of them quietly say everything is fine.
                "battery": _battery(mon),
                "alarm": self._alarm(mon, flags),
                "can": {
                    "alarms": {str(n): self._alarms[n] for n in config.NODES},
                    "nmt": {str(n): self._nmt_state[n] for n in config.NODES},
                    "emcy_seen": self._emcy_seen,
                    "heartbeat_ms": config.CAN_HEARTBEAT_MS,
                    "monitor": mon,
                    "flags": flags,
                },
                "event_seq": events.latest_seq(),
            }

    # ---- bus thread ------------------------------------------------------

    def _run(self):
        try:
            raw, how = open_bus(config.CAN_BITRATE, config.CAN_CHANNEL,
                                config.CAN_ADAPTER_SERIAL)
        except Exception as e:
            with self._lock:
                self.error = str(e)
            events.error(f"CAN bus unavailable: {e}")
            return
        self.bus = TpdoTap(raw, self._on_pdo, self._on_emcy,
                           self._on_heartbeat, nodes=config.NODES)
        with self._lock:
            self.how = how
            self.error = None
        events.info(f"bus up on {how} at {config.CAN_BITRATE // 1000} kbps · "
                    f"profile {config.PROFILE_NAME}")
        # Here, not at arm time: liveness has to work before, during and after
        # arming, and must not depend on having armed. Without this call 1017h
        # keeps its factory default of 0 = OFF, can.heartbeat_ms is inert, and
        # the only evidence a drive is alive is the 5 Hz telemetry poll.
        self._enable_heartbeat()

        t_tel = t_mon = 0.0
        # loop_health, not health: `health` is the hardware-health module. Loop
        # timing and device liveness are different questions.
        loop_health = _LoopHealth()
        self._hw.reset()      # a reopened bus starts with no liveness history
        try:
            while not self._stop_evt.is_set():
                t_iter = time.perf_counter()
                self._drain_queue()
                # A queued action runs on THIS thread, so a long one is a window
                # in which nothing polled and nothing could have marked
                # liveness. Judging it would report every source as lost.
                # reset() makes them "never seen" instead, which evaluate()
                # already treats as not-a-fault.
                if 0 < self._hw.min_timeout() < time.perf_counter() - t_iter:
                    self._hw.reset()

                self._panel_scan()

                now = time.monotonic()
                with self._lock:
                    armed, target, deadline, mode = (
                        self._armed, self._target, self._deadline, self._mode)

                if armed and now > deadline and target != (0, 0):
                    reason = "watchdog: no keepalive from the browser"
                    # A manual watchdog stop does NOT latch a fault. The
                    # setpoint is already zero, and going again means HOLDING a
                    # control that re-POSTs every 100 ms with the operator's
                    # hand on it - so there is no "restarted by somebody who did
                    # not see why", which is the hazard _set_fault() exists for.
                    # Latching a dropped packet would cost a walk to the panel,
                    # and under panel.manual_auto_arm it would block re-arming.
                    #
                    # *** When an autonomous mode returns this changes. ***
                    # Latched motion that would otherwise resume on its own is
                    # the opposite case and must latch. Tape following did, and
                    # whatever navigates next has to make that choice again
                    # rather than inherit this one by default.
                    #
                    # Emitted here rather than through _set_fault, which is safe
                    # on this 50 Hz path only because the branch is
                    # self-clearing - it zeroes the target below, which makes
                    # its own condition false on the very next tick.
                    events.warn(f"{reason} - setpoint zeroed, "
                                f"hold again to drive")
                    with self._lock:
                        self._direction = "stop"
                        self._target = target = (0, 0)
                        self._last_stop_reason = reason

                # Device liveness, a separate question from the operator
                # watchdog above. Pure arithmetic, no bus I/O, deliberately
                # outside the lock.
                hw = self._hw.evaluate(now)
                if hw["changed"] or hw["system_edge"] is not None:
                    target = self._apply_health(hw, armed, target)
                with self._lock:
                    self._health = hw

                if armed and self._target_moved(target):
                    self._write_target(target)

                if now - t_tel >= config.TELEMETRY_PERIOD_S:
                    t_tel = now
                    self._poll_telemetry()
                # Diagnostic monitoring runs whether armed or not: a drive
                # overheating or a battery sagging while parked is exactly what
                # you want to have seen BEFORE the next run. Paced like the
                # other polls - at tick rate it would spend two SDO round-trips
                # of every 20 ms budget on values that move thermally.
                if config.MONITOR_ENABLED and now - t_mon >= config.MONITOR_PERIOD_S:
                    t_mon = now
                    self._poll_monitor()

                # Pump only the REMAINDER of the period, not a further fixed
                # 20 ms on top of the work. Telemetry and setpoint writes already
                # spend time on the bus - and absorb pushed frames through the
                # tap while they do - so adding a full period afterwards
                # stretched the tick instead of pacing it. The 1 ms floor
                # guarantees the thread always yields.
                spent = time.perf_counter() - t_iter
                stats = loop_health.tick(t_iter, spent)
                if stats:
                    with self._lock:
                        self._loop.update(stats)
                self._pump(max(0.001, config.LOOP_PERIOD_S - spent))
        finally:
            try:
                self._do_disarm()
            except Exception:
                pass
            try:
                self.bus.shutdown()
            except Exception:
                pass

    def _pump(self, seconds):
        """Idle for `seconds`, routing any sensor frames that turn up."""
        end = time.perf_counter() + seconds
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return
            m = self.bus.recv(timeout=left)   # tap consumes TPDO1 internally
            if m is None:
                return

    def _drain_queue(self):
        while True:
            try:
                action, args, fut = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(getattr(self, "_do_" + action)(*args))
            except Exception as e:
                fut.set_exception(e)

    # ---- primitives ------------------------------------------------------

    def _mark_alive(self, node):
        """A completed SDO transfer proves that node is on the bus.

        Liveness used to be marked ONLY from _poll_telemetry and the heartbeat,
        so the ~20 round-trips inside _do_arm counted for nothing: the monitor
        declared both drives silent while we were mid-conversation with them,
        and an arm - 700-900 ms of blocking work against a 0.6 s timeout -
        reliably produced a false "driver silent" fault the moment it returned.

        .get() rather than [] on purpose: the MLS is node 10 and has no entry
        here, and its liveness is TPDO1 frames, not SDO replies.
        """
        src = self._src_node.get(node)
        if src is not None:
            src.mark_rx()

    def _read(self, node, index, sub=0, fast=False, timeout=None):
        """fast=True skips sdo_read's post-reply collision window.

        That window is 10 ms of pure dead time per read. Six telemetry reads at
        5 Hz therefore stalled the control loop for ~96 ms every 215 ms, which at
        0.8 m/s is 77 mm travelled with no steering update. Collision detection
        belongs in preflight and discovery, not in a loop that has to keep a
        vehicle on a line - so those paths keep the default.

        timeout overrides sdo_read's 0.4 s default. Used where a NON-answer is an
        expected outcome rather than a fault, so waiting the full default would
        just be dead time on a path that has already lost.
        """
        kw = {} if timeout is None else {"timeout": timeout}
        st, val, _, _ = sdo_read(self.bus, node, index, sub,
                                 collision_window=0.0 if fast else 0.01, **kw)
        if st:
            self._mark_alive(node)
        return u32(val) if st else None

    def _read_i32(self, node, index, sub=0, fast=False, timeout=None):
        kw = {} if timeout is None else {"timeout": timeout}
        st, val, _, _ = sdo_read(self.bus, node, index, sub,
                                 collision_window=0.0 if fast else 0.01, **kw)
        if st:
            self._mark_alive(node)
        return struct.unpack("<i", val.ljust(4, b"\0"))[0] if st else None

    def _write(self, node, index, sub, value, size, what):
        # Section 8 of the monitoring plan: the nav stack is READ-MOSTLY. A
        # denied index raises rather than being silently dropped - a command a
        # caller believed had landed is its own hazard.
        #
        # `sub` is passed because an RPDO mapping entry cannot be judged without
        # it: sub 0 is the entry count, sub 1-8 are object references, and the
        # guard applies the deny-list recursively to the object being mapped.
        guard_write(index, value, sub)
        ok, detail = sdo_write(self.bus, node, index, sub, value, size)
        if not ok:
            raise RuntimeError(f"node {node}: {what} ({index:04X}h) failed: {detail}")
        self._mark_alive(node)

    def _nmt(self, command, node):
        self.bus.send(can.Message(arbitration_id=0x000, data=[command, node],
                                  is_extended_id=False))
        time.sleep(0.05)

    def _write_target(self, target):
        """Push the setpoint to both drives. The hot path of the whole loop.

        Two routes, chosen by can.use_rpdo:

          RPDO1  one 6-byte frame per node, unacknowledged. A queue append.
          SDO    a blocking round trip per node, ~1.8 ms each.

        The SDO path is what shipped and stays the default until the RPDO path
        has been through the bench checklist - see config.py's can.use_rpdo. The
        cost of keeping both is one branch on a path that is about to get 3.6 ms
        cheaper, which is not a trade worth agonising over.

        rpdo.pack() puts the controlword through the same deny-list the SDO path
        uses, so bit 7 cannot reach a drive by this route either.
        """
        if config.CAN_USE_RPDO:
            for nid, rpm in zip((config.LEFT, config.RIGHT), target):
                rpdo.send(self.bus, nid, rpdo.CW_OPERATION_ENABLED, int(rpm))
        else:
            for nid, rpm in zip((config.LEFT, config.RIGHT), target):
                self._write(nid, 0x60FF, 0, int(rpm), 4, "target velocity")
        self._applied = target

    def _sdo_write_for_rpdo(self, bus, node, index, sub, value, size):
        """The SDO writer rpdo.configure() drives. Guarded, like every other write.

        Adapts _write()'s raise-on-failure style to the (ok, detail) tuple
        rpdo.configure() understands, so that module stays free of this class's
        conventions - it has to serve the ROS drive node too.
        """
        try:
            self._write(node, index, sub, value, size, "RPDO1 setup")
        except Exception as e:                  # noqa: BLE001
            return False, str(e)
        return True, ""

    def _target_moved(self, target):
        """Deadband the setpoint writes - see config.TARGET_DEADBAND_RPM."""
        if self._applied is None:
            return True
        if target == (0, 0) and self._applied != (0, 0):
            return True          # a stop is never deadbanded away
        return any(abs(a - b) >= config.TARGET_DEADBAND_RPM
                   for a, b in zip(target, self._applied))

    # ---- hardware health -------------------------------------------------



    def _apply_health(self, hw, armed, target):
        """React to a hardware-health TRANSITION. Returns the setpoint to write.

        Only called when something actually changed, so the events below fire
        once per edge - the rule events.py exists to protect, since this sits on
        a 50 Hz path where a per-tick emit would flush the whole ring in about
        four seconds.

        A critical loss is treated exactly like a watchdog trip: zero the
        setpoint outright rather than running the profile down. There is no
        point easing to a stop through a driver that has stopped answering.
        """
        for _name, detail, ok in hw["changed"]:
            if ok:
                events.info(f"{detail} is answering again")
            else:
                events.error(f"{detail} stopped answering")

        if hw["system_edge"] is True:
            reason = f"driver silent - {hw['system_detail']}, stopping"
            self._set_fault(reason)
            with self._lock:
                self._direction = "stop"
                self._target = target = (0, 0)
                self._last_stop_reason = reason
            events.error(reason)
        elif hw["system_edge"] is False:
            events.info("drivers answering again - re-arm to continue")
        return target

    # ---- operator panel --------------------------------------------------

    def _set_fault(self, reason):
        """Latch an INVOLUNTARY stop.

        Deliberate stops - Reset, web STOP, the selector - never come through
        here. Only things the vehicle decided for itself: a failed arm, a silent
        driver, a lost line, a dead DI link, a watchdog trip. Start stays
        refused until Reset acknowledges it, so a vehicle that stopped itself
        cannot be restarted with one press by somebody who did not see why.
        """
        with self._lock:
            first = self._fault is None
            self._fault = reason
        if first:                       # edge only; this is reachable at 50 Hz
            events.error(f"FAULT: {reason} - press Reset to clear")

    def _clear_fault(self):
        with self._lock:
            was, self._fault = self._fault, None
        if was:
            events.info(f"fault cleared: {was}")
        return was

    def _note_action(self, what, source):
        with self._lock:
            self._last_action = {"what": what, "source": source}

    def _panel_scan(self):
        """One panel scan. Called every tick from _run(), in every state."""
        if not config.PANEL_ENABLED:
            return
        snap = self._dio.snapshot()
        intent = self._panel.scan(snap.get("di"), bool(snap.get("comms_ok")))
        if not intent.valid:
            # No trusted image, so no decisions. The operator's panel is the
            # thing that just went away.
            return

        # Order matters: a selector move disarms, so evaluate it before the
        # buttons decide what to do about the new mode.
        if intent.mode_changed:
            self._panel_mode_changed(intent.mode)
        if intent.reset:
            self._panel_reset(intent.mode)
        if intent.start:
            self._panel_start(intent.mode)

        # A LEVEL, not an edge: what the selector is resting on decides whether
        # the vehicle should be energised, so it is evaluated every scan rather
        # than only when something is pressed.
        self._hold_arm_state(intent.mode)

    def _panel_start(self, mode):
        """Start has nothing to run. Kept live, and deliberately not removed.

        *** This is a stub with a reason. *** Start used to arm and then launch
        a tape-following run; that run is gone and no autonomous mode has
        replaced it yet. The button, its debounced edge in core/panel.py, and
        the anti-tie-down rule that stops a taped-down Start acting at power-on
        are all still correct and still tested - what is missing is something to
        start.

        So it reports rather than silently doing nothing: an operator pressing a
        button that does nothing needs to be told which of the two it is. When
        navigation lands, this is where it hooks in, and the fault gate below is
        the behaviour it must keep - a vehicle that stopped itself is not
        restarted by somebody who did not see why.
        """
        with self._lock:
            fault = self._fault
        if fault:
            events.warn(f"Start ignored - fault latched: {fault}. Press Reset.")
            return
        if mode != panel.AUTO:
            events.info("Start ignored - selector is in MANUAL")
            return
        events.warn("Start ignored - this build has no autonomous mode. "
                    "Tape following is retired; navigation is not here yet.")
        self._note_action("start ignored (no autonomous mode)", "panel")

    def _panel_mode_changed(self, mode):
        events.info(f"selector -> {mode.upper()}")
        # A move INTO manual re-arms through _hold_arm_state on this same scan,
        # so the disarm below is not a round trip to idle and back - it is the
        # mode change itself, which _do_arm cannot do in place.
        self._arm_retry_at = 0.0
        with self._lock:
            armed = self._armed
        if not armed:
            return
        # Mode is fixed at arm time, so a selector move has to go back to
        # idle. It is a deliberate operator action, so it stops without
        # latching a fault.
        self._do_disarm()
        self._note_action(f"disarmed (selector -> {mode})", "panel")

    def _panel_reset(self, mode):
        """Reset now only ever STOPS and ACKNOWLEDGES.

        It used to arm as well, which is why it was being pressed before every
        jog - and a button pressed by reflex has stopped being a decision.
        Arming is a consequence of the selector sitting in MANUAL, so what is
        left here is to stop and to acknowledge.

        Clearing the fault is what lets MANUAL arm itself again, so Reset is
        still the way back from anything the vehicle latched.
        """
        # Stop first, whatever else is true. Reset is the button somebody
        # presses when they want motion to end, and it must not be conditional
        # on which mode happens to be live.
        with self._lock:
            moving = self._target != (0, 0)
            self._direction = "stop"
            self._target = (0, 0)
        if moving:
            self._note_action("stopped", "panel")
            return

        was = self._clear_fault()
        # The backoff is cleared with the fault so the next scan retries at
        # once: somebody has just pressed the button that means "try again".
        self._arm_retry_at = 0.0
        self._note_action("fault cleared" if was else "reset", "panel")




    def _hold_arm_state(self, mode):
        """Keep the vehicle energised iff the selector says it should be.

        MANUAL is an armed state and AUTO is a disarmed one, so this is a level
        held every scan rather than an edge somebody presses:

          MANUAL  arm, and re-arm if anything de-energised the drives
          AUTO    disarm - there is nothing autonomous to be armed for

        Blocking work - an arm is ~20 SDO round-trips - but it runs on the bus
        thread from the panel scan, which is where every other arm has always
        happened.
        """
        if not config.PANEL_MANUAL_AUTO_ARM:
            return
        with self._lock:
            armed, cur, fault = self._armed, self._mode, self._fault

        if mode == panel.AUTO:
            # Nothing autonomous exists to be armed for, so AUTO is the resting
            # state. When navigation lands this is where it has to decide to
            # stay armed instead.
            if armed:
                self._do_disarm()
                self._note_action("disarmed (auto is idle)", "panel")
            return

        # MANUAL from here on.
        if fault:
            return                      # a latched fault is cleared by a human
        now = time.monotonic()
        if now < self._arm_retry_at:
            return

        if armed and cur == "manual":
            # Armed in software is not the same as torque at the wheels. If the
            # safety chain took the drives out from under us they are sitting in
            # ETO, and re-arming is how the vehicle comes back on its own once
            # the chain is restored - see _drives_ready().
            if self._drives_ready() is False:
                self._arm_retry_at = now + ARM_RETRY_S
                events.warn("drives are no longer enabled - re-arming")
                self._do_disarm()
                self._try_arm("manual")
            return

        if armed:
            self._do_disarm()           # armed in the other mode
        self._try_arm("manual")

    def _drives_ready(self):
        """Are both drives in Operation enabled? None while it cannot be known.

        Read from the 5 Hz telemetry rather than asking the bus, so this costs
        nothing on a path that runs every tick. None - not False - when a
        statusword has not been read yet, because "unknown" must not be allowed
        to trigger a re-arm.
        """
        with self._lock:
            words = [self._telemetry[n].get("statusword") for n in config.NODES]
        if any(w is None for w in words):
            return None
        return all((w & 0x6F) == 0x27 for w in words)

    def _try_arm(self, mode):
        """One auto-arm attempt, with backoff. Never latches a fault.

        A failed arm here is usually the safety chain holding the drives in ETO,
        which is a condition rather than a mistake: latching it would demand a
        Reset for something no operator did, and this whole change exists to
        stop asking for that. So it backs off and tries again, and the vehicle
        re-arms by itself once the chain is restored.
        """
        self._arm_retry_at = time.monotonic() + ARM_RETRY_S
        try:
            self._do_arm(mode)
            if self._arm_fail:
                self._arm_fail = None
            self._note_action(f"armed in {mode}", "panel")
        except Exception as e:          # noqa: BLE001 - a condition, not a fault
            why = str(e)
            if why != self._arm_fail:   # edge only; this retries every 2 s
                self._arm_fail = why
                events.warn(f"cannot arm in {mode}: {why} - retrying")







    def _on_emcy(self, node, data):
        """An alarm was PUSHED by a drive. Routed here by TpdoTap.

        EMCY is itself an event, not a poll, so emitting one line per frame does
        not violate the events.py rule - the drive only sends on a change. A
        repeated identical alarm would come from a drive genuinely re-raising it.
        """
        a = decode_emcy(data)
        label = config.NODES.get(node, node)
        with self._lock:
            self._emcy_seen += 1
            self._alarms[node] = dict(a, node=node, label=label,
                                      t=time.time())
        if a["cleared"]:
            events.info(f"node {node} ({label}) alarms cleared")
            return
        msg = f"node {node} ({label}) ALARM {a['hex']} - {a['name']}"
        if a["note"]:
            msg += f": {a['note']}"
        (events.error if a["level"] == "error" else events.warn)(msg)

    def _on_heartbeat(self, node, state_byte):
        """A drive's producer heartbeat (1017h) landed. Routed by TpdoTap.

        This is the liveness signal health.py actually wants: without it a
        driver that has stopped responding looks identical to one that is idle,
        which is why the plan calls enabling 1017h a MUST.
        """
        src = self._src_node.get(node)
        if src is not None:
            src.mark_rx()
        with self._lock:
            self._nmt_state[node] = decode_nmt(state_byte)

    def _poll_monitor(self):
        """One monitored object per node, round-robin. See canmon.py.

        Deliberately NOT a burst: _poll_telemetry() below already spends most of
        a 20 ms tick, and a late tick is a steering update the vehicle does not
        get. Bounded at two SDO round-trips however long the table grows.
        """
        nxt = self._mon.next_object()
        if nxt is None:
            return
        index, key, ctype = nxt
        for nid in config.NODES:
            st, val, _, _ = sdo_read(self.bus, nid, index, 0,
                                     collision_window=0.0)
            self._mon.store(nid, key, canmon._decode(ctype, val) if st else None)

    def _poll_telemetry(self):
        for nid in config.NODES:
            sw = self._read(nid, 0x6041, fast=True)
            rpm = self._read_i32(nid, 0x606C, fast=True)
            err = self._read(nid, 0x1001, fast=True)
            # Any answer at all proves the driver is still on the bus. Without
            # this the stale values below simply persist and a driver that has
            # stopped replying looks healthy for as long as the process runs.
            if sw is not None or rpm is not None or err is not None:
                self._src_node[nid].mark_rx()
            with self._lock:
                t = self._telemetry[nid]
                if sw is not None:
                    t["statusword"] = sw & 0xFFFF
                    t["state"] = decode_state(sw)
                    t["fault"] = bool(sw & SW_FAULT)
                    t["remote"] = bool(sw & SW_REMOTE)
                    t["speed_zero"] = bool(sw & SW_SPEED_IS_ZERO)
                if rpm is not None:
                    t["rpm"] = rpm
                if err is not None:
                    t["error_reg"] = err & 0xFF
                label = config.NODES[nid]
                faulted = bool(t.get("fault")) or bool(t.get("error_reg"))
                sw_now = t.get("statusword") or 0
                err_now = t.get("error_reg") or 0
            # Edge only. This runs at 5 Hz, so reporting a standing fault every
            # poll would bury every other event within a minute.
            if faulted != self._fault_seen.get(nid, False):
                self._fault_seen[nid] = faulted
                if faulted:
                    events.error(f"node {nid} ({label}) FAULT - statusword "
                                 f"0x{sw_now:04X}, error reg 0x{err_now:02X}")
                else:
                    events.info(f"node {nid} ({label}) fault cleared")


    # ---- queued actions --------------------------------------------------

    def _do_preflight(self):
        report = []
        ok = True
        for nid, label in config.NODES.items():
            st, _, note, _ = sdo_read(self.bus, nid, 0x1000, 0)
            if st is None:
                report.append(f"node {nid} ({label}): not responding")
                ok = False
                continue
            if "COLLISION" in note:
                report.append(f"node {nid} ({label}): {note}")
                ok = False
                continue
            err = self._read(nid, 0x1001)
            sw = self._read(nid, 0x6041)
            if err is None or sw is None:
                report.append(f"node {nid} ({label}): diagnostics unreadable")
                ok = False
                continue
            report.append(f"node {nid} ({label}): error reg 0x{err:02X}, "
                          f"statusword 0x{sw:04X} ({decode_state(sw)})")
            if err:
                report.append(f"  node {nid}: driver reports a fault - clear it first")
                ok = False
            if not sw & SW_REMOTE:
                report.append(f"  node {nid}: Remote bit clear - controlword ignored "
                              f"(S-ON active, or MEXE02 has the driver)")
                ok = False
            if sw & SW_FAULT:
                report.append(f"  node {nid}: FAULT state")
                ok = False
        return {"ok": ok, "report": report}


    def _enable_heartbeat(self):
        """Turn on the drives' producer heartbeat (1017h). Never fatal.

        The driver default is 0 = OFF, and with it off a drive that has stopped
        responding is indistinguishable from one that is idle. 1017h is a
        standard CANopen object and is on the permitted-write list; it cannot
        influence motion.

        A drive that refuses the write is logged and left alone - health.py
        still has the telemetry-reply fallback, just with coarser resolution.
        """
        if not config.CAN_HEARTBEAT_MS:
            return
        for nid in config.NODES:
            try:
                self._write(nid, 0x1017, 0, config.CAN_HEARTBEAT_MS, 2,
                            "producer heartbeat time")
            except Exception as e:                  # noqa: BLE001
                events.warn(f"node {nid} ({config.NODES[nid]}) would not accept "
                            f"a heartbeat interval ({e}) - liveness falls back "
                            f"to telemetry replies")

    def _do_arm(self, mode):
        """Energise the drives. `mode` is "manual" today - see _hold_arm_state.

        *** Arming excites the motor; it does not free it. *** Reaching CiA 402
        "Operation enabled" excites the motor (opman_can:1391) and the velocity
        loop then holds zero - a servo lock, not a free shaft - and a
        non-excited brake motor has the brake clamped instead (opman_fun:2021).
        Only the FREE input releases it, and FREE (403Eh bit 6) is on the write
        deny-list. So a disarmed vehicle cannot be pushed either.
        """
        # A driver that is not answering blocks every mode, dry run included -
        # the preflight below would fail anyway, but this says why in the terms
        # the event log has already been using.
        with self._lock:
            hw = self._health
        if hw.get("system_error"):
            raise RuntimeError(f"driver not answering: {hw['system_detail']}")

        pre = self._do_preflight()
        if not pre["ok"]:
            raise RuntimeError("preflight failed: " + "; ".join(pre["report"]))

        # PDO mapping belongs in PRE-OPERATIONAL (CiA 301), so this runs before
        # the NMT start below rather than beside the 6060h/6083h writes further
        # down. The sequence disables the PDO before remapping it, so a drive
        # that tolerates a live remap is not relied on to.
        if config.CAN_USE_RPDO:
            for nid in config.NODES:
                rpdo.configure(self.bus, nid, self._sdo_write_for_rpdo)

        for nid in config.NODES:
            self._nmt(0x01, nid)

        ramp = config.RAMP[mode]
        for nid in config.NODES:
            self._write(nid, 0x6060, 0, 3, 1, "modes of operation = pv")
            self._write(nid, 0x6083, 0, ramp["accel"], 4, "profile acceleration")
            self._write(nid, 0x6084, 0, ramp["decel"], 4, "profile deceleration")
            self._write(nid, 0x60FF, 0, 0, 4, "target velocity = 0")
            for cw, name in ((CW_SHUTDOWN, "Shutdown"),
                             (CW_SWITCH_ON, "Switch On"),
                             (CW_ENABLE, "Enable Operation")):
                self._write(nid, 0x6040, 0, cw, 2, name)
                time.sleep(0.05)
            sw = self._read(nid, 0x6041) or 0
            if (sw & 0x6F) != 0x27:
                self._do_disarm()
                raise RuntimeError(f"node {nid} did not reach Operation enabled "
                                   f"(statusword 0x{sw:04X}, {decode_state(sw)})")

        self._applied = None
        with self._lock:
            self._armed = True
            self._mode = mode
            self._direction = "stop"
            self._target = (0, 0)
            self._last_stop_reason = None
            self._deadline = time.monotonic() + config.MANUAL_WATCHDOG_S
        report = list(pre["report"])
        events.info(f"armed in {mode} mode")
        return {"ok": True, "report": report}

    def _do_disarm(self):
        """Zero the setpoint, wait for the ramp, then de-energise. Never raises."""
        with self._lock:
            was_armed = self._armed
            self._armed = False
            self._direction = "stop"
            self._target = (0, 0)
        if not was_armed:
            return {"ok": True}
        self._clear_fault()             # web disarm is an acknowledgement too
        events.info("disarmed")

        for nid in config.NODES:
            try:
                sdo_write(self.bus, nid, 0x60FF, 0, 0, 4)
            except Exception:
                pass
        end = time.time() + 4.0
        while time.time() < end:
            try:
                if all((self._read(n, 0x6041) or 0) & SW_SPEED_IS_ZERO for n in config.NODES):
                    break
            except Exception:
                break
            time.sleep(0.05)
        for nid in config.NODES:
            for cw in (CW_SHUTDOWN, CW_DISABLE_VOLTAGE):
                try:
                    sdo_write(self.bus, nid, 0x6040, 0, cw, 2)
                except Exception:
                    pass
        try:
            self._nmt(0x80, 0)            # everything back to Pre-operational
        except Exception:
            pass
        self._applied = None
        with self._lock:
            self._mode = "idle"
        return {"ok": True}



