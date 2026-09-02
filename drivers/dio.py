"""Digital I/O over Modbus TCP (16 in / 16 out) on its own thread.

The module answers at DIO_IP:502. Discrete inputs and coils both start at
address 0, and device_id is ignored - 1, 0 and 255 all reply - so the id in the
profile is documentation rather than addressing.

WHY A THREAD AND NOT THE CONTROL TICK
-------------------------------------
A read measures 2.0 ms on this link, so a scan (DI then DO) is ~4 ms. The CAN
control tick has a 20 ms budget, so scanning there would spend a fifth of it on
network I/O in the good case - and a network stall, which no timeout makes
instant, would blow the tick outright. Same reasoning as rfid.py: own thread,
own socket, publish an image the control loop reads without ever blocking.

WHAT "LIKE A PLC" ACTUALLY BUYS
------------------------------
Not the loop - the INPUT IMAGE. Every consumer sees one coherent set of bits
sampled at one instant, instead of reading a live socket at whatever moment it
happens to ask. snapshot() under a lock is exactly that, and it is the same
discipline canworker._branch_scan() already follows for the RFID reader.

The write phase of a real PLC scan is absent rather than stubbed. Nothing in
this system energises an output yet, and a dormant write path on a 150 kg
vehicle is a liability rather than a convenience. When one is wanted it belongs
here, after the reads, behind an arm-state interlock - not as a click handler on
a web page.

HEALTH IS THE OPPOSITE OF THE RFID READER'S
-------------------------------------------
RfidLink._comms_ok() keys on CONNECTION state and deliberately ignores data
flow, because the reader is push-only and silence between stations is normal.
Here silence IS the fault: we poll every scan_period_s, so a scan that has not
succeeded recently means the module, the cable or the switch has gone, whatever
the socket believes. Keying on the socket would report a half-open connection as
healthy for as long as the OS kept it.

TOPOLOGY
--------
The RFID reader is daisy-chained THROUGH this module's second port, so both sit
behind one cable to enp2s0. This module failing takes the reader with it, and
RfidLink.carrier() cannot see that - the PC's link partner is this module, so
carrier stays up. Two sources reporting at once is the signature of the shared
cause; either alone is the device itself.
"""
import threading
import time

import config
import events


class DioLink:
    """Owns the Modbus socket on its own thread. start() once, read snapshot()."""

    def __init__(self, client_factory=None):
        # Injectable so the tests can drive a fake without a network or a
        # pymodbus import - the same reason RfidLink takes a codec.
        self._client_factory = client_factory or self._default_client
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._client = None

        self._connected = False
        self._di = [False] * config.DIO_NUM_DI
        self._do = [False] * config.DIO_NUM_DO
        self._last_ok = None                # monotonic, last SUCCESSFUL scan
        self._scans = 0
        self._errors = 0
        self._detail = "disabled" if not config.DIO_ENABLED else "starting"

    # ---- public ----------------------------------------------------------

    @staticmethod
    def _default_client():
        # Imported lazily: pymodbus costs ~40 ms and is dead weight in a process
        # running with dio.enabled false.
        from pymodbus.client import ModbusTcpClient
        return ModbusTcpClient(config.DIO_IP, port=config.DIO_PORT,
                               timeout=config.DIO_TIMEOUT_S)

    def start(self):
        if not config.DIO_ENABLED or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="dio",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            age = (now - self._last_ok) if self._last_ok else None
            return {
                "enabled": config.DIO_ENABLED,
                "connected": self._connected,
                "comms_ok": self._comms_ok(age),
                # Copies. A caller that mutated the live lists would corrupt
                # the image every other consumer is reading.
                "di": list(self._di),
                "do": list(self._do),
                "di_names": list(config.DIO_DI_NAMES),
                "do_names": list(config.DIO_DO_NAMES),
                "rx_age_s": age,
                "scans": self._scans,
                "errors": self._errors,
                "scan_period_s": config.DIO_SCAN_PERIOD_S,
                "detail": self._detail,
            }

    # ---- internals -------------------------------------------------------

    def _comms_ok(self, age):
        """Recent SUCCESSFUL scans, not socket state. See the module docstring.

        Caller holds the lock.
        """
        if not config.DIO_ENABLED:
            return None                     # not a fault; simply not in use
        if age is None:
            return False                    # never completed a scan
        return age <= config.DIO_SILENT_WARN_S

    def _set_detail(self, text):
        with self._lock:
            self._detail = text

    def _close(self):
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:               # noqa: BLE001 - teardown only
                pass

    def _drop(self, why):
        """Lose the connection, once, on the edge."""
        with self._lock:
            was, self._connected = self._connected, False
            self._detail = why
        self._close()
        if was:
            events.warn(f"DIO lost: {why}")

    def _run(self):
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._scan()
            except Exception as e:          # noqa: BLE001 - thread must survive
                with self._lock:
                    self._errors += 1
                self._drop(f"{type(e).__name__}: {e}")
                if self._stop.wait(config.DIO_RECONNECT_PERIOD_S):
                    return

            # Pace on elapsed time, not a flat sleep, so a slow scan does not
            # push the period out and a fast one does not busy-wait.
            rest = config.DIO_SCAN_PERIOD_S - (time.monotonic() - started)
            if self._stop.wait(max(0.0, rest)):
                return

    def _scan(self):
        """One PLC scan: read inputs, read the coil readback, publish."""
        if self._client is None:
            self._client = self._client_factory()
        if not self._client.connect():
            raise ConnectionError(f"no answer at {config.DIO_IP}:{config.DIO_PORT}")

        di = self._read_bits(self._client.read_discrete_inputs,
                             config.DIO_DI_BASE, config.DIO_NUM_DI, "inputs")
        # Read the coils back rather than trusting a shadow copy. Nothing here
        # writes them today, but a readback is what would make a FAILED write
        # visible rather than showing the value we wished for.
        do = self._read_bits(self._client.read_coils,
                             config.DIO_DO_BASE, config.DIO_NUM_DO, "coils")

        if config.DIO_DI_FLIPPED:
            di = [not b for b in di]

        now = time.monotonic()
        with self._lock:
            was = self._connected
            self._di, self._do = di, do
            self._connected = True
            self._last_ok = now
            self._scans += 1
            self._detail = f"{config.DIO_IP}:{config.DIO_PORT}"
        # Edge only. This runs every scan_period_s; emitting per scan would
        # empty the 200-entry event ring in ten seconds.
        if not was:
            events.info(f"DIO connected {config.DIO_IP}:{config.DIO_PORT}")

    def _read_bits(self, fn, address, count, what):
        r = fn(address, count=count, device_id=config.DIO_DEVICE_ID)
        if r.isError():
            raise IOError(f"{what} read at {address}: {r}")
        bits = list(r.bits[:count])
        if len(bits) != count:
            # pymodbus pads to a byte boundary, so a short reply means the
            # module answered for fewer channels than the profile claims.
            raise IOError(f"{what}: asked {count}, got {len(bits)}")
        return [bool(b) for b in bits]
