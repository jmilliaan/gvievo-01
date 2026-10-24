"""CPU (2026-10-24): scan_gate's poll timer runs only while a scan is pending.

An empty 50 Hz poll still cost an executor wakeup each. The timer is armed by a
queued scan and cancelled once nothing is pending (released or expired); a scan
thinned at the door must not arm it. Node built with __new__ around the real ScanGate.
"""

from __future__ import annotations

import pytest

pytest.importorskip("rclpy")
from amr_localization.scan_gate import ScanGate  # noqa: E402
from sensor_msgs.msg import LaserScan  # noqa: E402

from amr_localization import scan_gate_node as sgn  # noqa: E402


class FakeTimer:
    def __init__(self) -> None:
        self.canceled, self.resets = True, 0

    def is_canceled(self) -> bool:
        return self.canceled

    def cancel(self) -> None:
        self.canceled = True

    def reset(self) -> None:
        self.canceled, self.resets = False, self.resets + 1


class FakeTf:
    ok = False

    def can_transform(self, *_a) -> bool:
        return self.ok


def node():
    n = sgn.ScanGateNode.__new__(sgn.ScanGateNode)
    n.gate = ScanGate(min_period_s=0.1, settle_s=0.02, hold_max_s=0.5)
    n.odom_frame = "odom"
    n.tf_buffer = FakeTf()
    n._poll_timer = FakeTimer()
    n.published = []
    n._pub = type("P", (), {"publish": staticmethod(n.published.append)})()
    n.clock_s = 100.0
    n._now = lambda: n.clock_s
    return n


def scan(t: float) -> LaserScan:
    m = LaserScan()
    m.header.frame_id = "laser"
    m.header.stamp.sec, m.header.stamp.nanosec = int(t), int(round((t % 1) * 1e9))
    return m


def test_a_queued_scan_arms_the_poll_and_a_release_disarms_it():
    n = node()
    n._on_scan(scan(100.0))
    assert not n._poll_timer.canceled and n._poll_timer.resets == 1
    n._poll()  # TF not there yet: keep polling
    assert not n._poll_timer.canceled and n.published == []
    n.tf_buffer.ok = True
    n._poll()
    assert len(n.published) == 1 and n._poll_timer.canceled, "nothing pending: no more wakeups"


def test_a_second_scan_while_armed_does_not_restart_the_schedule():
    n = node()
    n._on_scan(scan(100.0))
    n._on_scan(scan(100.2))
    assert n._poll_timer.resets == 1, "a reset per scan would push the poll out under a fast scanner"


def test_a_scan_thinned_at_the_door_does_not_arm():
    n = node()
    n.tf_buffer.ok = True
    n._on_scan(scan(100.0))
    n._poll()
    assert n._poll_timer.canceled and len(n.published) == 1
    n._on_scan(scan(100.05))  # inside min_period_s of the last release
    assert n._poll_timer.canceled and n._poll_timer.resets == 1


def test_a_scan_that_never_gets_tf_expires_and_disarms():
    n = node()
    n._on_scan(scan(100.0))
    n.clock_s = 100.6  # past hold_max_s
    n._poll()
    assert n.published == [] and n.gate.stats.expired == 1 and n._poll_timer.canceled


def test_a_stray_poll_with_nothing_pending_disarms():
    n = node()
    n._poll_timer.canceled = False
    n._poll()
    assert n._poll_timer.canceled
