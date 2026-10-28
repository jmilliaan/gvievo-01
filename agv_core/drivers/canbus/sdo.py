"""The SDO client, NMT and bus opening shared by the bus owner and the bench tools.

Expedited transfers only. python-can is imported lazily, so importing this module
(and the decoders that use it) costs nothing on a dev box without it.

*** Every SDO write goes through guard.py. *** guarded_sdo_write() is the bench
path; amr_base.canopen.DriveLink.write/write_sensor are the bus owner's. A raw
sdo_write() call anywhere else is refused by tests/test_canmon.py.
"""
import struct
import time

from agv_core.drivers.canbus import guard
from agv_core.drivers.canbus.cia301 import SDO_REPLY_BASE, SDO_REQUEST_BASE

CHANNEL = "can0"
ADAPTER_VID, ADAPTER_PID = 0x16D0, 0x117E
ADAPTER_SERIAL = "2087327F5548"  # None to accept any matching CANable2
BITRATE = 125000

OK, BAD, WARN = "\033[32mOK\033[0m", "\033[31mFAIL\033[0m", "\033[33mWARN\033[0m"

IDENTITY_SUBS = ((1, "vendor ID"), (2, "product code"), (3, "revision"), (4, "serial number"))


def _message(cob, data):
    import can  # noqa: PLC0415

    return can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=False)


def _drain(bus):
    while bus.recv(timeout=0) is not None:
        pass


def _reply_for(m, node, mux):
    """The 8 reply bytes if `m` answers OUR (index, sub) on `node`, else None.

    A reply counts only if it echoes our multiplexer in a full 8-byte frame. The
    drain before the request does not rule out a late reply to an EARLIER request
    landing now, and one accepted on node ID + command byte alone would be read as
    this object's value (C04, tests/test_invariants.py).
    """
    if m.arbitration_id != SDO_REPLY_BASE + node:
        return None
    data = bytes(m.data)
    if len(data) != 8 or data[1:4] != mux:
        return None
    return data


def sdo_read(bus, node, index, sub, timeout=0.4, collision_window=0.01):
    """Expedited SDO upload. Returns (status, payload, note, latency_ms).

    status: True=data, False=SDO abort, None=timeout
    Collects *all* responses in the window so two devices answering on the same
    Node-ID are detected.

    collision_window is how long to keep listening AFTER the first reply, purely
    to catch a second responder. That check is worth 10 ms during discovery and
    worthless in a control loop, where it is pure dead time on every read - pass
    0 to return as soon as the first reply lands (DriveLink.read does).
    """
    _drain(bus)
    bus.send(_message(SDO_REQUEST_BASE + node, [0x40, index & 0xFF, (index >> 8) & 0xFF, sub, 0, 0, 0, 0]))

    # Once the first reply lands, linger only briefly to catch a second
    # responder - waiting the full timeout every time would make the measured
    # latency meaningless and the whole scan glacial.
    mux = bytes([index & 0xFF, (index >> 8) & 0xFF, sub])
    replies, first_at, stale = [], None, 0
    t0 = time.perf_counter()
    deadline = t0 + timeout
    while time.perf_counter() < deadline:
        m = bus.recv(timeout=max(0.0, deadline - time.perf_counter()))
        if m is None:
            break
        data = _reply_for(m, node, mux)
        if data is None:
            stale += m.arbitration_id == SDO_REPLY_BASE + node
            continue
        replies.append(data)
        if first_at is None:
            first_at = time.perf_counter()
            deadline = min(deadline, first_at + collision_window)

    if not replies:
        return None, None, ("timeout" if not stale
                            else f"timeout ({stale} reply(s) for another object)"), None

    latency_ms = (first_at - t0) * 1000.0
    note = "ok" if len(replies) == 1 else f"{len(replies)} REPLIES - ID COLLISION?"
    cs = replies[0][0]
    if cs == 0x80:
        return False, struct.unpack_from("<I", replies[0], 4)[0], note, latency_ms
    if cs & 0xE0 == 0x40:
        size = 4 - ((cs >> 2) & 0x03) if cs & 0x02 else 4
        return True, replies[0][4:4 + size], note, latency_ms
    return False, None, f"unexpected SCS 0x{cs:02X}", latency_ms


def sdo_write(bus, node, index, sub, value, size, timeout=0.5):
    """Expedited SDO download, UNGUARDED. Returns (ok, detail).

    Callers outside this module and DriveLink use guarded_sdo_write().
    """
    cs = {1: 0x2F, 2: 0x2B, 3: 0x27, 4: 0x23}[size]
    payload = struct.pack("<i" if value < 0 else "<I", value)[:size]
    _drain(bus)
    bus.send(_message(SDO_REQUEST_BASE + node,
                      bytes([cs, index & 0xFF, (index >> 8) & 0xFF, sub]) + payload.ljust(4, b"\0")))

    mux = bytes([index & 0xFF, (index >> 8) & 0xFF, sub])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        m = bus.recv(timeout=max(0.0, deadline - time.monotonic()))
        if m is None:
            break
        data = _reply_for(m, node, mux)
        if data is None:
            continue
        if data[0] == 0x60:
            return True, "ok"
        if data[0] == 0x80:
            return False, f"abort 0x{struct.unpack_from('<I', data, 4)[0]:08X}"
        return False, f"unexpected 0x{data[0]:02X}"
    return False, "timeout"


def guarded_sdo_write(bus, node, index, sub, value, size, timeout=0.5, sensor=False):
    """The bench write path: guard first, then the SDO. Returns (ok, detail).

    sensor=False checks the drive list (guard.check), sensor=True the line-sensor
    list (guard.check_sensor). A refused object never reaches the bus; the refusal
    comes back as (False, reason) so the tool reports it and stops.
    """
    try:
        if sensor:
            guard.check_sensor(index, sub)
        else:
            guard.check(index, value, sub)
    except guard.ForbiddenWrite as e:
        return False, str(e)
    return sdo_write(bus, node, index, sub, value, size, timeout=timeout)


def u32(b):
    return struct.unpack("<I", b.ljust(4, b"\0"))[0]


def s16(v):
    """A raw 16-bit object as signed (the SDO layer hands back unsigned). None stays None."""
    return v - 0x10000 if v is not None and v >= 0x8000 else v


def s8(v):
    """The low byte of a raw object as signed. None stays None."""
    return None if v is None else (v & 0xFF) - 0x100 if v & 0x80 else v & 0xFF


def sdo_int(bus, node, index, sub=0, signed=False):
    """One object as an int (little-endian, `signed` as asked), or None on abort/timeout."""
    st, val, _, _ = sdo_read(bus, node, index, sub)
    if not st or not val:
        return None
    return int.from_bytes(val, "little", signed=signed)


def read_identity(bus, node):
    """1018h subs 1-4 -> [(name, status, value)]; value is the u32 or the abort code."""
    out = []
    for sub, name in IDENTITY_SUBS:
        st, val, _, _ = sdo_read(bus, node, 0x1018, sub)
        out.append((name, st, u32(val) if st else val))
    return out


def nmt(bus, command, node=0):
    """0x01 start, 0x02 stop, 0x80 pre-operational. node 0 = broadcast."""
    bus.send(_message(0x000, [command, node]))
    time.sleep(0.05)


def socketcan_ready(iface):
    """True if the interface exists and IFF_UP is set."""
    try:
        with open(f"/sys/class/net/{iface}/flags") as f:
            return bool(int(f.read().strip(), 16) & 0x1)
    except OSError:
        return False


def find_adapter(serial=None):
    """Locate the CANable by USB VID/PID/serial - immune to ttyACM renumbering.

    serial defaults to this module's ADAPTER_SERIAL. Empty string or None means
    accept any matching CANable2, which is what a bench with one adapter wants.
    """
    serial = ADAPTER_SERIAL if serial is None else (serial or None)
    from serial.tools import list_ports  # noqa: PLC0415
    return [p for p in list_ports.comports()
            if p.vid == ADAPTER_VID and p.pid == ADAPTER_PID
            and (serial is None or p.serial_number == serial)]


def claim_bus(who):
    """Take the CAN owner lock the ROS drive node holds.

    Returns the lock - keep a reference for as long as the bus is in use - or
    None after printing who owns can0, in which case the caller must exit
    WITHOUT opening the bus. socketcan admits any number of openers, so this
    lock is the only thing that stops a bench tool's SDO requests or controlword
    writes interleaving with the running stack's.

    Imported lazily so importing this module costs nothing: agv_core.ownerlock
    needs no vehicle profile, and a bench run that never takes the lock never
    pays for it.
    """
    from agv_core import ownerlock  # noqa: PLC0415
    try:
        return ownerlock.acquire("can", who)
    except ownerlock.OwnerBusy as e:
        print(f"{BAD}: {e} - stop it first (sudo systemctl stop amr.service). Nothing was sent.")
    except OSError as e:
        print(f"{BAD}: cannot take the CAN owner lock ({e}). Nothing was sent.")
    return None


def open_bus(bitrate=None, channel=None, adapter_serial=None):
    """Prefer SocketCAN; fall back to slcan on the auto-discovered port.

    Every argument defaults to this module's own constant, so the bench tools
    stay standalone and never import the vehicle profile. drive_node passes
    config.CAN_BITRATE / CAN_CHANNEL / CAN_ADAPTER_SERIAL, so the running system
    has a single source for all three.

    adapter_serial="" means accept any matching CANable2.
    """
    import can  # noqa: PLC0415

    bitrate = BITRATE if bitrate is None else bitrate
    channel = CHANNEL if channel is None else channel
    if socketcan_ready(channel):
        return can.Bus(interface="socketcan", channel=channel), f"socketcan:{channel}"

    ports = find_adapter(adapter_serial)
    if not ports:
        want = ADAPTER_SERIAL if adapter_serial is None else adapter_serial
        raise RuntimeError(
            f"no CANable ({ADAPTER_VID:#06x}:{ADAPTER_PID:#06x}"
            f"{'/' + want if want else ''}) found on USB, "
            f"and {channel} is not up")
    if len(ports) > 1:
        raise RuntimeError(f"ambiguous: {len(ports)} matching adapters "
                           f"({[p.device for p in ports]}) - set "
                           f"can.adapter_serial in the profile")
    dev = ports[0].device
    return can.Bus(interface="slcan", channel=dev, bitrate=bitrate), f"slcan:{dev}"


def bench_bus(who, bitrate=None, channel=None, note="", lock=True):
    """A bench tool's opening: owner lock, then the bus. Returns (lock, bus) or None.

    None means the reason was printed and the tool exits 2 with nothing sent.
    Keep the returned lock referenced until the bus is shut down. lock=False is
    for read_mls's listen-only `stream` (no --nmt), which runs beside the service on purpose.
    """
    held = None
    if lock:
        held = claim_bus(who)
        if held is None:
            return None
    try:
        bus, how = open_bus(bitrate, channel)
    except Exception as e:  # noqa: BLE001 - a bench tool reports and exits
        print(f"{BAD}: {e}")
        return None
    print(f"connected via {how}{note}\n")
    return held, bus
