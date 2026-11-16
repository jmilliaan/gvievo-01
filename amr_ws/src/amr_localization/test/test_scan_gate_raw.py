"""CPU 2026-11-16 (cpu-load plan §4a d): scan_gate passes /scan through as raw bytes.

The gate reads only the stamp and frame from the CDR buffer (cdr_header) and the bytes
it publishes are the bytes it received: no LaserScan deserialise/serialise. The
serialize_message round trip against the real message type needs rclpy (vehicle only).
"""

from __future__ import annotations

import struct

import pytest
from amr_localization.scan_gate import ScanGate, cdr_header


def cdr_scan(sec: int, nanosec: int, frame: str, little: bool = True, tail: bytes = b"\x00" * 40) -> bytes:
    """A LaserScan-shaped CDR buffer: encapsulation, Header, then any body."""
    e = "<" if little else ">"
    name = frame.encode() + b"\x00"
    pad = b"\x00" * (-len(name) % 4)
    head = bytes([0, 1 if little else 0, 0, 0]) + struct.pack(e + "iII", sec, nanosec, len(name))
    return head + name + pad + tail


def test_header_is_read_from_the_cdr_buffer():
    stamp, frame = cdr_header(cdr_scan(1731740000, 123456789, "laser"))
    assert frame == "laser"
    assert stamp == (1731740000 * 1_000_000_000 + 123456789) * 1e-9, "as Time.from_msg().nanoseconds"
    assert cdr_header(cdr_scan(5, 500_000_000, "base_laser", little=False)) == (5.5, "base_laser")
    assert cdr_header(cdr_scan(0, 0, "")) == (0.0, "")


def test_a_truncated_buffer_is_refused_not_misread():
    raw = cdr_scan(1, 0, "laser_frame")
    for n in (0, 4, 15, 20):
        with pytest.raises(ValueError):
            cdr_header(raw[:n])
    bogus = bytearray(raw)
    bogus[12:16] = struct.pack("<I", 10_000)  # string length past the end
    with pytest.raises(ValueError):
        cdr_header(bytes(bogus))


def test_bytes_in_equal_bytes_out():
    g = ScanGate(min_period_s=0.1, settle_s=0.02, hold_max_s=0.5)
    sent = [cdr_scan(100, i * 30_000_000, "laser", tail=bytes(range(i, i + 50))) for i in range(10)]
    out = []
    for i, raw in enumerate(sent):
        stamp, frame = cdr_header(raw)
        g.push(stamp, raw, now=100.0 + i * 0.03, frame=frame)
        assert g.frame_of_oldest() in ("laser", None), "None: thinned at the door"
        out += g.poll(100.0 + i * 0.03 + 0.001, lambda t: True)
    assert out and all(any(o is s for s in sent) for o in out), "the very objects that came in"
    assert out == [sent[0], sent[4], sent[8]], "same bytes, thinned to >= 0.1 s as before"


def test_a_deserialised_message_still_works_without_a_frame_argument():
    class M:
        class header:  # noqa: N801
            frame_id = "laser"

    g = ScanGate(min_period_s=0.0, settle_s=0.0)
    g.push(1.0, M, now=1.0)
    assert g.frame_of_oldest() == "laser" and g.poll(1.0, lambda t: True) == [M]


def test_the_real_message_round_trips_through_the_header_reader():
    pytest.importorskip("rclpy")
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import LaserScan

    m = LaserScan()
    m.header.frame_id = "laser"
    m.header.stamp.sec, m.header.stamp.nanosec = 1731740000, 987654321
    m.ranges = [1.0, 2.0, 3.0]
    raw = serialize_message(m)
    assert cdr_header(raw) == ((1731740000 * 1_000_000_000 + 987654321) * 1e-9, "laser")
