"""verify_bus.run(), which verify_drivers now calls too: the exit code and the hints,
against a scripted bus (no hardware)."""
import contextlib
import io
import struct

from helpers import check


class _Bus:
    """Answers SDO uploads for the nodes in `devices` {node: device type}."""

    def __init__(self, devices):
        self.devices = devices
        self.queue = []

    def send(self, m):
        import can

        node = m.arbitration_id - 0x600
        if not 0 < node < 128 or node not in self.devices or m.data[0] != 0x40:
            return
        index, sub = m.data[1] | (m.data[2] << 8), m.data[3]
        value = {0x1000: self.devices[node], 0x1018: 0x100 + sub}.get(index)
        if value is None:
            reply = bytes([0x80, m.data[1], m.data[2], sub]) + struct.pack("<I", 0x06020000)
        else:
            reply = bytes([0x43, m.data[1], m.data[2], sub]) + struct.pack("<I", value)
        self.queue.append(can.Message(arbitration_id=0x580 + node, data=reply, is_extended_id=False))

    def recv(self, timeout=None):
        return self.queue.pop(0) if self.queue else None


def _run(devices, **kw):
    from agv_core.drivers.canbus import verify_bus, verify_drivers
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = verify_bus.run(_Bus(devices), verify_drivers.EXPECTED, verify_drivers.SCAN_RANGE,
                            scan_timeout=0.01, listen_s=0.0, strict_type=True,
                            hints=verify_drivers.HINTS, **kw)
    return rc, out.getvalue()


def test_verify_run():
    from agv_core.drivers.canbus import verify_drivers
    print("\nverify_bus.run: exit code and hints (verify_drivers' expectations)")
    dt = verify_drivers.DEVICE_TYPE_EXPECTED

    rc, out = _run({1: dt, 2: dt})
    check("both drivers with the right type: exit 0", rc == 0 and "exactly nodes [1, 2]" in out, out[-80:])
    rc, out = _run({1: dt})
    check("right driver missing: exit 1 with the ID-SEL hint",
          rc == 1 and "missing [2]" in out and "ID-SEL0" in out)
    rc, out = _run({1: dt, 2: 0x00020191})
    check("a wrong device type fails under strict_type", rc == 1 and "expected 0x00020192" in out)
    rc, out = _run({})
    check("nothing on the bus: exit 1 with the termination help", rc == 1 and "TERMINATION" in out)


TESTS = [test_verify_run]
