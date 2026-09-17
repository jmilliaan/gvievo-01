"""R04: a fault stop reaches each drive independently, retries a failed send a
bounded number of times, and reports a stop it cannot deliver or confirm."""

import struct
import time

import can
from test_canopen import FakeBus, _link

from amr_base.canopen import FAULT, SW_SPEED_IS_ZERO


class RpdoFailBus(FakeBus):
    """RPDO1 sends to the nodes in `fail` raise, `fail[node]` times (None = always)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.fail = {}

    def send(self, m):
        n = m.arbitration_id - 0x200
        if n in self.fail and self.fail[n] != 0:
            if self.fail[n] is not None:
                self.fail[n] -= 1
            raise can.CanOperationError("ENOBUFS")
        super().send(m)


def _rpdos(bus):
    return [
        (m.arbitration_id - 0x200, struct.unpack("<Hi", bytes(m.data))[1])
        for m in bus.sent
        if 0x201 <= m.arbitration_id <= 0x202
    ]


def _armed(bus):
    link = _link(bus)
    link.arm(20, None, 0, 30.0, False, False)
    bus.sent.clear()
    return link


def test_first_node_send_failure_does_not_skip_the_second_and_is_retried():
    bus = RpdoFailBus(statusword=0x1637)
    link = _armed(bus)
    bus.fail = {1: 1}
    link.fault("drive silent")
    assert link.state == FAULT
    assert _rpdos(bus) == [(2, 0)]  # node 2 stopped although node 1 raised
    assert link.stop_pending == {1}
    link.fault_tick(time.monotonic(), 0.05)
    assert _rpdos(bus) == [(2, 0), (1, 0)] and not link.stop_pending
    link.fault_tick(time.monotonic(), 0.05)
    assert _rpdos(bus) == [(2, 0), (1, 0)]  # nothing more once delivered
    assert link.stop_unconfirmed == []


def test_persistent_failure_is_bounded_and_reported_unconfirmed():
    bus = RpdoFailBus(statusword=0x1637)
    link = _armed(bus)
    bus.fail = {2: None}
    link.fault("drive fault")
    for _ in range(link.STOP_RETRIES + 3):
        link.fault_tick(time.monotonic(), 0.05)
    assert _rpdos(bus) == [(1, 0)]
    assert link.stop_unconfirmed == ["node 2: zero not delivered"]
    assert all(v == 0 for _, v in _rpdos(bus))  # no nonzero refresh in FAULT
    link.disarm()
    assert link.stop_unconfirmed == [] and not link.heartbeat_withheld


def test_standstill_is_measured_from_fresh_status_only():
    bus = FakeBus(statusword=0x1637)
    link = _armed(bus)
    link.fault("drive fault")
    now = link.t_fault + link.STOP_CONFIRM_S
    t1, t2 = link.telemetry[1], link.telemetry[2]
    t1.statusword, t1.rpm, t1.t_status = 0x0637, 900, now  # fresh, still turning
    t2.statusword, t2.rpm, t2.t_status = 0x0637, 900, now - 10.0  # stale: not escalated
    link.fault_tick(now, 0.05)
    assert link.stop_unconfirmed == ["node 1: still turning (900 r/min)"]
    t1.statusword, t1.rpm = 0x0637 | SW_SPEED_IS_ZERO, 0
    link.fault_tick(now, 0.05)
    assert link.stop_unconfirmed == []


def test_withheld_heartbeat_is_not_sent_by_the_keepalive():
    bus = FakeBus(statusword=0x1637)
    link = _link(bus)
    link.pc_node, link.pc_heartbeat_s = 100, 0.0
    link.keepalive()
    assert sum(m.arbitration_id == 0x764 for m in bus.sent) == 1
    link.heartbeat_withheld = True
    link.keepalive()
    assert sum(m.arbitration_id == 0x764 for m in bus.sent) == 1
