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
  read_mls.decode_tpdo1 / COMBI_VARIANTS       sensor frame decode
"""
import os
import queue
import struct
import sys
import threading
import time
from concurrent.futures import Future

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
# canbus/ is the CAN layer: SDO transfers, bus discovery, CiA 402 words and the
# MLS frame decoder. It is a RUNTIME dependency of the web app - moving or
# renaming that directory breaks the server. It stays a plain directory on
# sys.path rather than a package, because its modules import each other by bare
# name so they also run standalone on a bench; as a package they would resolve
# twice, once as `verify_drivers` and once as `canbus.verify_drivers`.
sys.path.insert(0, os.path.join(_ROOT, "canbus"))

import can  # noqa: E402
from alarms import (decode_emcy, decode_nmt,  # noqa: E402
                    decode_statusword_flags)
from bus_health import decode_state  # noqa: E402
from guard import check as guard_write  # noqa: E402
from drive_forward import (CW_DISABLE_VOLTAGE, CW_ENABLE, CW_SHUTDOWN,  # noqa: E402
                           CW_SWITCH_ON, SW_FAULT, SW_REMOTE,
                           SW_SPEED_IS_ZERO, sdo_write)
from read_mls import COMBI_VARIANTS, decode_tpdo1  # noqa: E402
from verify_drivers import open_bus, sdo_read, u32  # noqa: E402

import autopilot  # noqa: E402
import canmon  # noqa: E402
import config  # noqa: E402
import events  # noqa: E402
import health  # noqa: E402
import motion  # noqa: E402
import rfid  # noqa: E402
import runlog  # noqa: E402

# Node IDs, driver ramp rates, watchdogs and loop periods all come from the
# vehicle profile - see config.py's TUNING NOTES for the reasoning behind the
# values, and profiles/<AGV_PROFILE>.json to change them.

# The MLS answers an SDO in single-digit ms. This is not a tunable: it is "long
# enough that a healthy sensor always replies", and it is short because a manual
# arm pays it too and a missing sensor must not tax a mode that does not need one.
SENSOR_PROBE_TIMEOUT_S = 0.15
SENSOR_SILENT_MSG = (f"MLS (node {config.SENSOR_NODE}) is not responding - auto "
                     f"mode is unavailable. Manual jogging still works, without "
                     f"the tape display.")


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
        TPDO1_COB    the MLS sensor stream, 100 Hz
        0x080 + n    EMCY - alarms, pushed one per error event
        0x700 + n    heartbeat - the only thing that tells a dead driver apart
                     from an idle one
    Everything else is handed back to the caller, which is how SDO replies get
    home.
    """

    def __init__(self, bus, on_pdo, on_emcy=None, on_heartbeat=None,
                 nodes=()):
        self._bus = bus
        self._on_pdo = on_pdo
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
            if m.arbitration_id == config.TPDO1_COB:
                self._on_pdo(m)
                continue           # not our reply - keep waiting for the SDO
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

      work_ms   how long the iteration spent doing things (SDO round-trips,
                the PID tick, logging). This is the number that grows when the
                bus gets slow.
      period_ms the interval actually achieved between iterations. This is what
                the control law experiences as dt.

    Also counts sensor frames per tick, because a starved tick - armed, but no
    new TPDO1 since the last one - means the loop is outrunning the sensor and
    the PID is being asked to act on a frame it has already seen.

    Pure arithmetic on the bus thread; it never touches the lock or the bus.
    """

    def __init__(self, window=50):
        self.window = window          # ~1 s at 50 Hz
        self._reset()
        self._prev_iter = None
        self._prev_seen = 0

    def _reset(self):
        self._work = []
        self._period = []
        self._frames = []
        self._starved = 0

    def tick(self, t_iter, spent, sensor_seen, armed):
        """Returns a stats dict once per window, else None."""
        if self._prev_iter is not None:
            self._period.append((t_iter - self._prev_iter) * 1000.0)
        self._prev_iter = t_iter
        self._work.append(spent * 1000.0)

        new_frames = sensor_seen - self._prev_seen
        self._prev_seen = sensor_seen
        self._frames.append(new_frames)
        if armed and new_frames == 0:
            self._starved += 1

        if len(self._work) < self.window:
            return None
        stats = {
            "work_avg_ms": sum(self._work) / len(self._work),
            "work_max_ms": max(self._work),
            "period_avg_ms": (sum(self._period) / len(self._period)
                              if self._period else None),
            "period_max_ms": max(self._period) if self._period else None,
            "frames_per_tick": sum(self._frames) / len(self._frames),
            "starved": self._starved,
        }
        self._reset()
        return stats


class Controller:
    """Owns the bus thread and the vehicle state machine."""

    def __init__(self):
        # RLock, not Lock. Any bus read can re-enter this class: sdo_read()
        # drains the RX queue, TpdoTap hands sensor frames to _on_pdo(), and
        # _on_pdo() takes this lock. Holding a plain Lock across a bus call
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
        self._mode = "idle"          # idle | manual | auto
        self._direction = "stop"
        self._target = (0, 0)
        self._applied = None
        self._deadline = 0.0
        self._combi = False
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
        self._src_mls = self._hw.add(
            health.HealthSource("mls", detail=f"MLS (node {config.SENSOR_NODE})"),
            config.SENSOR_TIMEOUT_S)
        self._health = {}

        # Drive monitoring. Diagnostic only - see manuals/can-monitoring-plan.txt
        # and canmon.py. The poller is pure bookkeeping; this class does the
        # actual SDO read, one object per node per tick.
        self._mon = canmon.MonitorPoller(config.NODES)
        self._alarms = {n: None for n in config.NODES}   # latest decoded EMCY
        self._nmt_state = {n: None for n in config.NODES}
        self._emcy_seen = 0
        self._sensor = None
        self._sensor_seen = 0
        self._sensor_last = 0.0
        self._field_level = None
        self._min_level = None

        # Loop health, published for the UI. Answers "is the tick late, and if so
        # is it the controller or the bus?" - work_ms is time spent doing things,
        # period_ms is the interval actually achieved. We diagnosed a 70 ms
        # telemetry stall by hand from a CSV column once; this makes it visible.
        self._loop = {"work_avg_ms": None, "work_max_ms": None,
                      "period_avg_ms": None, "period_max_ms": None,
                      "frames_per_tick": None, "starved": None,
                      "target_ms": config.LOOP_PERIOD_S * 1000.0}

        # Auto (line following). _auto_running is the START/STOP latch; the
        # follower keeps its own ramp and PID state across ticks.
        self._follower = autopilot.LineFollower()
        self._auto_running = False
        self._auto_tick = 0.0        # perf_counter of the previous PID tick
        self._auto_seen = -1         # _sensor_seen at the previous PID tick
        self._pid = None             # last diag dict, for snapshot()
        self._log = runlog.RunLog()
        self._log_close_at = 0.0     # keep logging through the deceleration

        # Station tags. Its own thread and its own socket - the control tick
        # only ever reads rfid.snapshot(), never touches the network.
        self._rfid = rfid.RfidLink()
        # Pulled rather than pushed: the link already tracks its own health on
        # its own thread, and copying that verdict beats defining "healthy" for
        # the reader twice. Registered unconditionally - snapshot() reports a
        # None verdict while rfid.enabled is false, which health.py reads as
        # "not in use" and never counts against a mode.
        self._hw.add(health.PullSource("rfid", self._rfid.snapshot),
                     config.RFID_SILENT_WARN_S)

    # ---- lifecycle ------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="can", daemon=True)
        self._thread.start()
        self._rfid.start()          # no-op while rfid.enabled is false

    def shutdown(self):
        self._stop_evt.set()
        self._rfid.stop()
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

    def keepalive(self):
        """Auto mode heartbeat, refreshed by the telemetry poll."""
        with self._lock:
            if self._mode == "auto" and self._armed:
                self._deadline = time.monotonic() + config.AUTO_WATCHDOG_S

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
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
                "sensor": self._sensor,
                "sensor_frames": self._sensor_seen,
                "sensor_age_s": (now - self._sensor_last) if self._sensor_last else None,
                "field_level": self._field_level,
                "min_level": self._min_level,
                "rpm_profile": {"full": config.MANUAL_FULL_RPM, "half": config.MANUAL_HALF_RPM,
                                "auto": config.AUTO_RPM},
                "auto_running": self._auto_running,
                "pid": self._pid,
                "dry_run": config.DRY_RUN,
                "loop": dict(self._loop),
                # Just the high-water mark. The UI fetches /api/events only when
                # this moves, so a quiet vehicle costs no extra requests.
                "rfid": self._rfid.snapshot(),
                "health": self._health,
                "can": {
                    "alarms": {str(n): self._alarms[n] for n in config.NODES},
                    "nmt": {str(n): self._nmt_state[n] for n in config.NODES},
                    "emcy_seen": self._emcy_seen,
                    "heartbeat_ms": config.CAN_HEARTBEAT_MS,
                    "monitor": self._mon.snapshot(config.MONITOR_THRESHOLDS),
                    "flags": {
                        str(n): decode_statusword_flags(
                            self._telemetry[n].get("statusword"))
                        for n in config.NODES},
                },
                "event_seq": events.latest_seq(),
                "log_path": self._log.path,
                "log_dir": self._log.dir,
                "log_plot": self._log.plot_path,
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

        t_tel = t_field = t_mon = 0.0
        # loop_health, not health: `health` is the hardware-health module. Loop
        # timing and device liveness are different questions.
        loop_health = _LoopHealth()
        self._hw.reset()      # a reopened bus starts with no liveness history
        try:
            while not self._stop_evt.is_set():
                t_iter = time.perf_counter()
                self._drain_queue()

                now = time.monotonic()
                with self._lock:
                    armed, target, deadline, mode = (
                        self._armed, self._target, self._deadline, self._mode)

                if armed and now > deadline and (target != (0, 0)
                                                 or self._auto_running):
                    reason = ("watchdog: no keepalive from the browser"
                              if mode == "manual" else
                              "watchdog: auto page stopped polling")
                    # A watchdog is a safety stop, so it zeroes outright rather
                    # than running the profile down - and it has to clear both
                    # the latch and the ramp, or the PID would re-command on the
                    # very next tick.
                    self._end_auto_run(reason, hard=True)
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

                if armed and mode == "auto":
                    target = self._run_autopilot()

                if armed and self._target_moved(target):
                    self._write_target(target)

                if now - t_tel >= config.TELEMETRY_PERIOD_S:
                    t_tel = now
                    self._poll_telemetry()
                if armed and now - t_field >= config.FIELD_PERIOD_S:
                    t_field = now
                    self._poll_field()
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
                # spend time on the bus - and absorb sensor frames through the
                # tap while they do - so adding a full period afterwards
                # stretched the tick instead of pacing it. The 1 ms floor
                # guarantees the thread always yields and always services TPDO1.
                spent = time.perf_counter() - t_iter
                stats = loop_health.tick(t_iter, spent, self._sensor_seen, armed)
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
        return u32(val) if st else None

    def _read_i32(self, node, index, sub=0, fast=False, timeout=None):
        kw = {} if timeout is None else {"timeout": timeout}
        st, val, _, _ = sdo_read(self.bus, node, index, sub,
                                 collision_window=0.0 if fast else 0.01, **kw)
        return struct.unpack("<i", val.ljust(4, b"\0"))[0] if st else None

    def _write(self, node, index, sub, value, size, what):
        # Section 8 of the monitoring plan: the nav stack is READ-MOSTLY. A
        # denied index raises rather than being silently dropped - a command a
        # caller believed had landed is its own hazard.
        guard_write(index, value)
        ok, detail = sdo_write(self.bus, node, index, sub, value, size)
        if not ok:
            raise RuntimeError(f"node {node}: {what} ({index:04X}h) failed: {detail}")

    def _nmt(self, command, node):
        self.bus.send(can.Message(arbitration_id=0x000, data=[command, node],
                                  is_extended_id=False))
        time.sleep(0.05)

    def _write_target(self, target):
        for nid, rpm in zip((config.LEFT, config.RIGHT), target):
            self._write(nid, 0x60FF, 0, int(rpm), 4, "target velocity")
        self._applied = target

    def _target_moved(self, target):
        """Deadband the setpoint writes - see config.TARGET_DEADBAND_RPM."""
        if self._applied is None:
            return True
        if target == (0, 0) and self._applied != (0, 0):
            return True          # a stop is never deadbanded away
        return any(abs(a - b) >= config.TARGET_DEADBAND_RPM
                   for a, b in zip(target, self._applied))

    # ---- autopilot -------------------------------------------------------

    def _run_autopilot(self):
        """One PID tick. Returns the setpoint to write this pass."""
        tick = time.perf_counter()
        with self._lock:
            sensor, seen, running = (self._sensor, self._sensor_seen,
                                     self._auto_running)
            age = ((time.monotonic() - self._sensor_last)
                   if self._sensor_last else None)

        # Never act twice on the same frame. While driving, a tick with no new
        # TPDO1 holds the previous command and lets the elapsed time roll into
        # the next real tick, where the clamped dt absorbs it. While stopping we
        # keep ticking regardless, so the ramp-down still completes.
        if running and seen == self._auto_seen:
            return self._target

        dt = (tick - self._auto_tick) if self._auto_tick else config.DT_NOMINAL_S
        self._auto_seen, self._auto_tick = seen, tick

        left, right, diag = self._follower.update(sensor, age, dt, running)
        commanded = (int(round(left)), int(round(right)))
        # DRY_RUN still computes and logs everything; only the wheels go quiet.
        target = (0, 0) if config.DRY_RUN else commanded

        with self._lock:
            self._target = target
            self._pid = diag
            self._direction = ("forward" if diag["state"] in ("run", "coast")
                               else "stop")
            tel = {"rpm_l": self._telemetry[config.LEFT]["rpm"],
                   "rpm_r": self._telemetry[config.RIGHT]["rpm"],
                   "sw_l": self._telemetry[config.LEFT]["statusword"],
                   "sw_r": self._telemetry[config.RIGHT]["statusword"]}
        tel["loop_ms"] = dt * 1000.0
        self._log.write(diag, tel)

        if running and diag["state"] in ("line_lost", "sensor_lost"):
            # A fault stops as hard as a STOP does - there is no reason to
            # coast gently toward whatever the AGV has just lost sight of.
            self._end_auto_run(
                f"line lost - no track for "
                f"{config.LINE_LOSS_GRACE_M * 1000:.0f} mm of travel, stopping"
                if diag["state"] == "line_lost" else
                "sensor silent - no TPDO1, stopping", hard=True)
        elif (not running and self._log_close_at
                and time.monotonic() >= self._log_close_at):
            self._log.close()
            self._log_close_at = 0.0
        return target

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
            self._end_auto_run(reason, hard=True)
            with self._lock:
                self._direction = "stop"
                self._target = target = (0, 0)
                self._last_stop_reason = reason
            events.error(reason)
        elif hw["system_edge"] is False:
            events.info("drivers answering again - re-arm to continue")
        return target

    def _end_auto_run(self, reason=None, hard=False, close_log_now=False):
        """Clear the START latch. Safe to call repeatedly.

        hard collapses the software profile to zero at once, so the setpoint
        goes straight to 0 and the DRIVERS do the stopping at 6084h - much
        faster than running the software ramp down, which is what a stop should
        be. Logging carries on for config.LOG_TAIL_S so that deceleration lands in the
        CSV; it is the most interesting part of a stop and none of it is
        visible to the software otherwise.
        """
        with self._lock:
            was_running = self._auto_running
            self._auto_running = False
            if reason:
                self._last_stop_reason = reason
        # Emit on the EDGE only. This is reachable from _run_autopilot(), which
        # is a 50 Hz path - without the was_running guard a fault would refill
        # the whole ring buffer with copies of itself in four seconds.
        if reason and was_running:
            events.warn(reason)
        if hard:
            self._follower.hard_stop()
        if close_log_now:
            self._log.close()
            self._log_close_at = 0.0
        elif self._log_close_at == 0.0:
            self._log_close_at = time.monotonic() + config.LOG_TAIL_S

    def _on_pdo(self, msg):
        r = decode_tpdo1(bytes(msg.data), self._combi)
        if r is None:
            return
        now = time.monotonic()
        self._src_mls.mark_rx(now)
        with self._lock:
            self._sensor = _sensor_json(r)
            self._sensor_seen += 1
            self._sensor_last = now

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

    def _poll_field(self):
        field = self._read(config.SENSOR_NODE, 0x2024, fast=True)
        with self._lock:
            if field is not None:
                self._field_level = field

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

    def _start_sensor(self):
        """NMT-start node 10 and resolve its TPDO1 layout. Returns True if it
        answered.

        Bus I/O only, so the caller must NOT hold _lock: sdo_read drains RX
        through TpdoTap, which re-enters _on_pdo, which takes the same lock.
        That is the deadlock this codebase has already been bitten by once.

        _combi decides how decode_tpdo1() unpacks each 16-bit field (2006h:01
        selects a packed position+width layout), so it has to be resolved before
        the first frame is decoded rather than assumed.

        Runs on EVERY arm, including manual, so a missing sensor must be cheap:
        the MLS answers in single-digit ms, so a 0.15 s timeout is generous, and
        the second read is skipped once the first has already told us nobody is
        home. Worst case ~0.15 s instead of the ~0.82 s two full timeouts cost.
        """
        self._nmt(0x01, config.SENSOR_NODE)   # Operational -> TPDO1 starts
        variant = self._read(config.SENSOR_NODE, 0x2006, 1,
                             timeout=SENSOR_PROBE_TIMEOUT_S)
        if variant is None:
            return False
        min_level = self._read(config.SENSOR_NODE, 0x2025,
                               timeout=SENSOR_PROBE_TIMEOUT_S)
        with self._lock:
            self._combi = variant in COMBI_VARIANTS
            self._min_level = min_level
        return True

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
        # Sensor-only arm. In DRY_RUN nothing is ever commanded to move, so the
        # drivers are deliberately left NON-EXCITED: reaching "Operation
        # enabled" excites the motor (opman_can:1391) and the velocity loop then
        # holds zero, which is a servo lock, not a free shaft. Leaving them out
        # also means a driver that is unreachable, faulted, or held by MEXE02
        # cannot block a check that does not involve the drivers at all.
        dry = mode == "auto" and config.DRY_RUN

        # A driver that is not answering blocks every mode, dry run included -
        # the preflight below would fail anyway, but this says why in the terms
        # the event log has already been using.
        with self._lock:
            hw = self._health
        if hw.get("system_error"):
            raise RuntimeError(f"driver not answering: {hw['system_detail']}")

        pre = self._do_preflight()
        if not pre["ok"] and not dry:
            raise RuntimeError("preflight failed: " + "; ".join(pre["report"]))

        if dry:
            if not self._start_sensor():
                raise RuntimeError(SENSOR_SILENT_MSG)
            with self._lock:
                self._armed = True
                self._mode = mode
                self._direction = "stop"
                self._target = (0, 0)
                self._last_stop_reason = None
                self._deadline = time.monotonic() + config.AUTO_WATCHDOG_S
            self._applied = None
            report = list(pre["report"])
            report.append("DRY RUN: drivers left de-energised, sensor only. "
                          "Nothing can move. Move a magnet under the sensor to "
                          "check the sign of e.")
            if not pre["ok"]:
                report.append("(preflight issues above are not blocking a dry run)")
            events.warn("armed DRY RUN - drivers de-energised, sensor only")
            return {"ok": True, "report": report, "dry_run": True}

        for nid in config.NODES:
            self._nmt(0x01, nid)          # per-node; the sensor starts separately
        # Every mode, not just auto: manual needs the tape position too, to line
        # the AGV up before handing over. Streaming it cannot engage the PID -
        # _run() gates _run_autopilot() on mode == "auto" independently.
        #
        # A silent sensor degrades AUTO ONLY. Auto without it would arm and then
        # trip sensor_lost on the first tick of START, so refuse up front and say
        # why. Manual does not need the sensor at all and must not be held
        # hostage to it - it just loses the tape strip.
        sensor_ok = self._start_sensor()
        if not sensor_ok and mode == "auto":
            raise RuntimeError(SENSOR_SILENT_MSG)

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
            self._deadline = time.monotonic() + (
                config.AUTO_WATCHDOG_S if mode == "auto" else config.MANUAL_WATCHDOG_S)
        report = list(pre["report"])
        if not sensor_ok:
            report.append(SENSOR_SILENT_MSG)
            events.warn(SENSOR_SILENT_MSG)
        events.info(f"armed in {mode} mode")
        return {"ok": True, "report": report, "sensor_ok": sensor_ok}

    def _do_disarm(self):
        """Zero the setpoint, wait for the ramp, then de-energise. Never raises."""
        # close_log_now: disarm clears _armed, so _run_autopilot stops being
        # called and nothing would ever flush the deferred close.
        self._end_auto_run(hard=True, close_log_now=True)
        with self._lock:
            was_armed = self._armed
            self._armed = False
            self._direction = "stop"
            self._target = (0, 0)
        if not was_armed:
            return {"ok": True}
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
            self._sensor = None
        return {"ok": True}

    def _do_auto_run(self, running):
        with self._lock:
            if self._mode != "auto" or not self._armed:
                raise RuntimeError("auto mode is not armed")

        if running:
            # Fresh integral, derivative and ramp state for every run, and a
            # fresh log - gains are file constants, so one run is one datapoint.
            self._follower.reset()
            self._auto_tick = 0.0
            self._auto_seen = -1
            self._log.close()            # a restart abandons any pending tail
            self._log_close_at = 0.0
            self._log = runlog.RunLog()
            self._log.open(
                f"profile={config.PROFILE_NAME} "
                f"K_RATIO={config.K_RATIO} KD={config.KD} "
                f"KI={config.KI} TAU_D={config.TAU_D_S} "
                f"AUTO_RPM={config.AUTO_RPM} zeta={autopilot.predicted_zeta():.3f} "
                f"6083h={config.ACCEL_RPM_S} 6084h={config.DECEL_RPM_S} "
                f"sw_ramp={config.RAMP_ACCEL_RPM_S} "
                f"DRY_RUN={config.DRY_RUN}")
            events.info(f"auto run START at {config.AUTO_RPM:.0f} r/min "
                        f"(K={config.K_RATIO} Kd={config.KD}) -> "
                        f"{os.path.basename(self._log.dir or '?')}")
            with self._lock:
                self._auto_running = True
                self._direction = "forward"
                self._deadline = time.monotonic() + config.AUTO_WATCHDOG_S
                self._last_stop_reason = None
        else:
            # STOP is a high-deceleration stop, not a run-down of the profile:
            # the setpoint goes to 0 immediately and the drivers brake at
            # 6084h (auto decel), roughly 2.5x faster than the software ramp.
            self._end_auto_run("auto run STOP (operator)", hard=True)

        return {"ok": True, "running": running,
                "dry_run": config.DRY_RUN,
                "log": self._log.path if running else None,
                "log_dir": self._log.dir if running else None}


def _sensor_json(r):
    """decode_tpdo1() output -> something JSON and the browser can use."""
    st = r["status"]
    tracks = []
    for i in r["valid"]:
        pos, width = r["lcp"][i - 1]
        tracks.append({"index": i, "pos_mm": pos, "width": width})
    return {
        "nlcp": r["nlcp"],
        "label": r["nlcp_label"],
        "tracks": tracks,
        "has_track": bool(r["valid"]),
        "line_good": st["line_good"],
        "track_level": st["track_level"],
        "polarity": st["polarity"],
        "flipped": st["sensor_flipped"],
        "reading_code": st["reading_code"],
        "event_flag": st["event_flag"],
        "marker": r["marker"],
    }
