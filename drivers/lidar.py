"""SICK nanoScan3 UDP data stream on its own thread.

*** NOT A SAFETY PATH. *** The stop is the scanner's OSSD pair into the FX3,
dropping STO in hardware. Nothing here may stop, arm or gate the vehicle, and
the health source this registers is deliberately non-critical. See
core/lidarframe.py for the decode and for what has actually been validated.

READ-ONLY AGAINST THE DEVICE
----------------------------
This binds a UDP socket and listens. It opens no CoLa 2 session, sends the
scanner nothing, and cannot change its configuration - which is rule 2 of
lidar_brief.md, and the reason the vendor libraries were not used (they write the
data-output config on every start). The scanner is already set to stream
continuously to this host, so there is nothing to ask it for.

WHY A THREAD, AGAIN
-------------------
Same answer as dio.py and rfid.py: 34 telegrams a second in five datagrams each
is ~172 wakeups a second, and the CAN control tick has a 20 ms budget. Own
thread, own socket, publish an image the control loop reads without blocking.

THE COST MODEL IS DIFFERENT FROM THE OTHER TWO, THOUGH
------------------------------------------------------
A telegram is 6812 bytes and carries 1652 points. Decoding all of them 34 times
a second, to render a picture a browser asks for 5 times a second, is most of a
core spent on nothing. So the split is:

  every telegram   header, block table, zones, geometry - tens of microseconds
  on demand        the point array, decoded in cloud() by the requesting thread

The last telegram is kept as immutable bytes, so cloud() copies a reference
under the lock and decodes outside it. That is the whole reason _last_tel is
bytes rather than a parsed dict.

SILENCE IS THE FAULT
--------------------
_comms_ok keys on recent telegrams, like DioLink and unlike RfidLink: the
scanner streams unconditionally at 34 Hz, so a gap is a failure of the scanner,
the cable, the switch or this process. There is no equivalent of the RFID
reader's legitimate quiet between stations.

sec 4 of the brief - "Absence of data is never 'clear'" - is NOT implemented
here. It is implemented at every consumer, because this module cannot know what
a consumer would do with a stale zone flag. What this module guarantees is that
staleness is always VISIBLE: comms_ok goes false, and zones carries `stale`.
"""
import socket
import threading
import time

import config
import events
import lidarframe


class LidarLink:
    """Owns the UDP socket on its own thread. start() once, read snapshot()."""

    def __init__(self, sock_factory=None):
        # Injectable for the tests, the same way DioLink takes a client_factory
        # and RfidLink takes a codec: the whole reader can then be driven from a
        # captured telegram with no network.
        self._sock_factory = sock_factory or self._default_socket
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sock = None

        self._asm = lidarframe.Reassembler(config.LIDAR_REASSEMBLY_TIMEOUT_S)
        self._connected = False
        self._last_ok = None            # monotonic, last COMPLETE telegram
        self._last_tel = None           # bytes; decoded on demand by cloud()
        self._summary = None            # cheap per-telegram decode
        self._telegrams = 0
        self._gaps = 0                  # missing telegram counter values
        self._errors = 0
        self._prev_ident = None
        self._rate = 0.0
        self._rate_t0 = None
        self._rate_n = 0
        self._detail = "disabled" if not config.LIDAR_ENABLED else "starting"

    # ---- public ----------------------------------------------------------

    @staticmethod
    def _default_socket():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # A telegram is five datagrams; the default buffer is generous but a
        # busy PC can still coalesce a burst. Ask for room for ~30 telegrams.
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        except OSError:                 # noqa: BLE001 - advisory only
            pass
        s.settimeout(0.5)               # so stop() is honoured promptly
        s.bind((config.LIDAR_HOST_IP, config.LIDAR_PORT))
        return s

    def start(self):
        if not config.LIDAR_ENABLED or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="lidar",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    def zone_spec(self):
        """The profile's provisional cut-off-path mapping. See lidarframe.zones."""
        return (config.LIDAR_ZONE_BLOCK, config.LIDAR_ZONE_BYTES,
                config.LIDAR_ZONE_ACTIVE_LOW, config.LIDAR_ZONES_VALIDATED)

    def snapshot(self):
        """Cheap summary, safe to call at tick rate. No point array."""
        now = time.monotonic()
        with self._lock:
            age = (now - self._last_ok) if self._last_ok else None
            summary = self._summary
            snap = {
                "enabled": config.LIDAR_ENABLED,
                "connected": self._connected,
                "comms_ok": self._comms_ok(age),
                "rx_age_s": age,
                "telegrams": self._telegrams,
                "gaps": self._gaps,
                "errors": self._errors,
                "dropped": self._asm.dropped,
                "rate_hz": self._rate,
                "detail": self._detail,
                "sensor_ip": config.LIDAR_SENSOR_IP,
                "silent_warn_s": config.LIDAR_SILENT_WARN_S,
            }
        # Outside the lock: summary is a plain dict this thread never mutates
        # in place - _decode publishes a NEW one every telegram.
        if summary:
            snap.update(summary)
        # Staleness is decided here, once, so no consumer has to re-derive it
        # from rx_age_s and get the comparison the wrong way round.
        stale = bool(config.LIDAR_ENABLED) and not snap["comms_ok"]
        snap["stale"] = stale
        # Never connected is not the same fault as went silent, and the two
        # want different words in front of an operator: an unplugged scanner
        # is a cable to go and look at, while a stream that stopped mid-run is
        # a scanner that died with the vehicle moving. Decided here, once, for
        # the same reason `stale` is - so no page re-derives it and gets the
        # comparison backwards.
        #
        # This changes what is DISPLAYED and nothing else. Both cases remain
        # non-critical (the stop is the OSSD pair into the FX3, in hardware),
        # and both still render the zone lamps as occupied - absence of data is
        # never clear, whatever the reason for the absence.
        snap["never_seen"] = bool(config.LIDAR_ENABLED) and age is None
        z = dict(snap.get("zones") or {})
        z["stale"] = stale
        snap["zones"] = z
        return snap

    def cloud(self, step=None):
        """The point array, decoded by the CALLING thread. See the class docstring."""
        step = config.LIDAR_DECIMATE if step is None else step
        now = time.monotonic()
        with self._lock:
            tel = self._last_tel        # immutable; safe to use outside the lock
            age = (now - self._last_ok) if self._last_ok else None
            ok = self._comms_ok(age)
        if tel is None:
            return {"points": None, "stale": True, "rx_age_s": age}
        try:
            full = lidarframe.decode(tel, self.zone_spec(), step=step)
        except Exception as e:          # noqa: BLE001 - a page must never 500
            return {"points": None, "stale": True, "error": f"{type(e).__name__}: {e}"}
        m = full.get("measurement") or {}
        d = full.get("derived") or {}
        return {
            # Diagnostics travel with the cloud rather than with the snapshot:
            # this is the payload `lidar_scan.py raw` and the page's detail
            # panel read when somebody is sitting with document 8022706.
            "blocks": full.get("blocks"),
            "raw": full.get("raw"),
            "zones": full.get("zones"),
            "points": m.get("dist_mm"),
            "status": m.get("status"),
            "rssi": m.get("rssi"),
            "step": m.get("step", 1),
            "beams": full.get("beams"),
            # The browser reconstructs each bearing as start + i*res*step, which
            # is why these travel with the points and are not a page constant.
            "start_angle_deg": d.get("start_angle_deg"),
            "resolution_deg": d.get("resolution_deg"),
            "no_echo_mm": lidarframe.NO_ECHO_MM,
            "rx_age_s": age,
            "stale": not ok,
        }

    # ---- internals -------------------------------------------------------

    def _comms_ok(self, age):
        """Recent COMPLETE telegrams. Caller holds the lock."""
        if not config.LIDAR_ENABLED:
            return None                 # not in use; not a fault
        if age is None:
            return False                # never received one
        return age <= config.LIDAR_SILENT_WARN_S

    def _close(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except Exception:           # noqa: BLE001 - teardown only
                pass

    def _drop(self, why):
        """Lose the socket, once, on the edge."""
        with self._lock:
            was, self._connected = self._connected, False
            self._detail = why
        self._close()
        if was:
            events.warn(f"lidar lost: {why}")

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._sock is None:
                    self._sock = self._sock_factory()
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue                # normal: settimeout only exists for stop()
            except Exception as e:      # noqa: BLE001 - thread must survive
                with self._lock:
                    self._errors += 1
                self._drop(f"{type(e).__name__}: {e}")
                if self._stop.wait(config.LIDAR_RECONNECT_PERIOD_S):
                    return
                continue

            # Filter by source. The port is ours, but a bind is not a promise
            # about who sends to it, and a decode is a poor place to find out.
            if addr[0] != config.LIDAR_SENSOR_IP:
                with self._lock:
                    self._asm.foreign += 1
                continue

            try:
                done = self._asm.push(data, time.monotonic())
            except Exception:           # noqa: BLE001 - one bad datagram only
                with self._lock:
                    self._errors += 1
                continue
            if done is not None:
                self._on_telegram(*done)

    def _on_telegram(self, ident, tel):
        now = time.monotonic()
        try:
            # points=False: the expensive half is left for cloud().
            full = lidarframe.decode(tel, self.zone_spec(), points=False)
        except Exception as e:          # noqa: BLE001 - a bad telegram is not fatal
            with self._lock:
                self._errors += 1
                self._detail = f"decode: {type(e).__name__}: {e}"
            return

        # Lean, because health.PullSource calls snapshot() on the bus thread at
        # tick rate: the 80 bytes of undecoded diagnostic blocks have no business
        # being copied 50 times a second to answer "is it alive". They stay
        # available through cloud(), which is polled 5 times a second by one page.
        summary = {"beams": full["beams"], "derived": full["derived"],
                   "zones": full["zones"]}

        with self._lock:
            was = self._connected
            # sec 3.5: a gap in the counter is datagram loss, which is a network
            # or CPU-load problem that is otherwise completely invisible.
            if self._prev_ident is not None:
                step = (ident - self._prev_ident) & 0xFFFFFFFF
                if 1 < step < 0x80000000:
                    self._gaps += step - 1
            self._prev_ident = ident

            self._last_tel = tel
            self._summary = summary
            self._connected = True
            self._last_ok = now
            self._telegrams += 1
            self._detail = f"{config.LIDAR_SENSOR_IP}:{config.LIDAR_PORT}"

            # Rate over a sliding second, so the page shows what is arriving now
            # rather than the average since boot.
            if self._rate_t0 is None:
                self._rate_t0, self._rate_n = now, 0
            self._rate_n += 1
            span = now - self._rate_t0
            if span >= 1.0:
                self._rate = self._rate_n / span
                self._rate_t0, self._rate_n = now, 0

        if not was:
            events.info(f"lidar connected {config.LIDAR_SENSOR_IP} "
                        f"({summary.get('beams')} beams)")
