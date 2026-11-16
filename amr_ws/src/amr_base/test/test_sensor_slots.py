"""Unified plan WP-B1 (H-P0-6): sensor work on the bus thread is bounded.

The real DriveLink over the FakeBus of test_canopen, with the real MlsImu and MlsTrack on node
10, driven the way drive_node's loop drives them: link.idle() (the IMU poll) then track.poll(),
once per iteration. Each iteration may carry ONE MLS SDO of at most 0.05 s, on the rediscovery
path too, and the two readers take turns instead of one starving the other.
"""

import pytest
from test_canopen import FakeBus, _arm, _link

from amr_base import canopen, mls_imu
from amr_base.canopen import SensorToken
from amr_base.mls_imu import MlsImu
from amr_base.mls_track import MlsTrack

MLS = 10
SDO_TO_MLS = 0x600 + MLS


def _mls_objects(bus, imu_sdo=True, track_tpdo=False):
    o = bus.objects
    o[(MLS, 0x2006, 2)] = 1  # MEMS on
    o[(MLS, mls_imu.TPDO_GYRO_COMM, 1)] = 0x80000000 if imu_sdo else 0x28A
    o[(MLS, 0x2034, 3)] = 0x0010
    o[(MLS, 0x2035, 0)] = 7
    o[(MLS, 0x2006, 1)] = 0  # variant Standard
    o[(MLS, 0x1800, 1)] = 0x18A if track_tpdo else 0
    for i, sub, v in ((0x2021, 1, 0), (0x2021, 2, 20), (0x2021, 3, 0), (0x2021, 4, 2), (0x2022, 0, 3)):
        o[(MLS, i, sub)] = v


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


def _rig(bus, monkeypatch, track_mode="auto"):
    """link + imu + track, with every sdo_read to the MLS recorded as (index, timeout)."""
    link = _link(bus)
    timeouts = []
    real = canopen.sdo_read

    def spy(router, node, index, sub, timeout=0.4, collision_window=0.01):
        if node == MLS:
            timeouts.append((index, timeout))
        return real(router, node, index, sub, timeout=timeout, collision_window=collision_window)

    monkeypatch.setattr(canopen, "sdo_read", spy)
    clk = Clock()
    got = {"imu": [], "track": []}
    imu = MlsImu(link, MLS, got["imu"].append, poll_hz=50.0, log=lambda s: None)
    track = MlsTrack(link, MLS, got["track"].append, mode=track_mode, sdo_hz=10.0, clock=clk,
                     log=lambda s: None)
    return link, imu, track, clk, got, timeouts


def _iteration(link, imu, track, bus, clk):
    """One loop iteration as drive_node runs it. -> MLS SDO requests it put on the bus."""
    before = sum(m.arbitration_id == SDO_TO_MLS for m in bus.sent)
    # The sensor's clock runs: a stamp that never advances is a frozen sensor (WP-E7, 2026-11-16)
    bus.objects[(MLS, 0x2035, 0)] = (bus.objects[(MLS, 0x2035, 0)] + 20) & 0xFFFF
    link.idle_hook = lambda: imu.poll(clk.t)
    link.idle()
    track.poll(clk.t)
    return sum(m.arbitration_id == SDO_TO_MLS for m in bus.sent) - before


def test_both_readers_polling_by_sdo_share_one_sdo_per_iteration_and_take_turns(monkeypatch):
    bus = FakeBus()
    _mls_objects(bus)
    link, imu, track, clk, got, timeouts = _rig(bus, monkeypatch, track_mode="sdo")
    assert imu.start(clk.t) == "sdo" and track.start() == "sdo"
    timeouts.clear()
    per_iteration = []
    for _ in range(100):  # 2 s at 50 Hz
        clk.t += 0.02
        per_iteration.append(_iteration(link, imu, track, bus, clk))
    assert max(per_iteration) == 1 and link.sensor_token.max_reads == 1
    assert all(t <= canopen.DriveLink.SENSOR_TIMEOUT_S for _, t in timeouts)
    assert all(t <= MlsImu.POLL_TIMEOUT_S for i, t in timeouts if i in (0x2034, 0x2035))
    # Neither starves: the IMU keeps a sample rate, and the track still completes its 5-read cycles.
    assert len(got["imu"]) >= 30 and len(got["track"]) >= 5
    assert link.sensor_token.refusals > 0 and imu.misses == 0 and track.misses == 0


def test_the_rediscovery_of_both_readers_is_one_short_read_per_iteration(monkeypatch):
    bus = FakeBus()  # the MLS is not on the bus at start
    link, imu, track, clk, got, timeouts = _rig(bus, monkeypatch)
    assert imu.start(clk.t) == "off" and track.start() == "off"
    _mls_objects(bus, track_tpdo=True)  # (FakeBus answers 16 bits: no 32-bit PDO mapping here)
    timeouts.clear()
    per_iteration = []
    for _ in range(int(6.0 / 0.02)):
        clk.t += 0.02
        per_iteration.append(_iteration(link, imu, track, bus, clk))
    assert imu.mode == "sdo" and imu.restarts == 1 and got["imu"]
    assert track.mode == "tpdo" and track.restarts == 1
    assert max(per_iteration) == 1
    assert timeouts and all(t <= 0.05 for _, t in timeouts)


def test_nmt_nowait_sends_one_frame_and_never_pumps(monkeypatch):
    link = _link(FakeBus())
    pumps = []
    monkeypatch.setattr(link.router, "pump", lambda s: pumps.append(s))
    link.nmt_nowait(0x01, MLS)
    m = link.router._bus.sent[-1]
    assert (m.arbitration_id, bytes(m.data)) == (0x000, bytes([0x01, MLS])) and not pumps
    with pytest.raises(ValueError):
        link.nmt_nowait(0x01, 0)  # never a broadcast: it would start the drives too
    link.nmt(0x80, 1)
    assert pumps == [0.05]  # the drives' nmt() is unchanged


def test_read_sensor_caps_its_timeout_and_never_runs_the_idle_hook(monkeypatch):
    bus = FakeBus()
    _mls_objects(bus)
    link, *_ = _rig(bus, monkeypatch)
    seen = []
    monkeypatch.setattr(canopen, "sdo_read", lambda r, n, i, s, timeout=0.4, collision_window=0.01: (
        seen.append(timeout), (True, bytes([5, 0, 0, 0]), "ok", 1.0))[1])
    calls = []
    link.idle_hook = lambda: calls.append(1)
    assert link.read_sensor(MLS, 0x2034, 3, timeout=0.4) == 5
    assert seen == [canopen.DriveLink.SENSOR_TIMEOUT_S] and calls == []
    slots = link.sensor_token.slots
    link.read_sensor(MLS, 0x2034, 3)
    assert link.sensor_token.slots == slots, "a sensor read opened a slot"


def test_a_sensor_write_is_guarded_capped_and_runs_no_idle_hook(monkeypatch):
    from agv_core.drivers.canbus import guard

    link = _link(FakeBus())
    seen = []
    monkeypatch.setattr(canopen, "sdo_write", lambda r, n, i, s, v, size, timeout=0.4: (
        seen.append(timeout), (True, ""))[1])
    calls = []
    link.idle_hook = lambda: calls.append(1)
    assert link.write_sensor(MLS, 0x2080, 1, 0, 1, timeout=1.0)[0]
    assert seen == [canopen.DriveLink.SENSOR_TIMEOUT_S] and calls == []
    with pytest.raises(guard.ForbiddenWrite):
        link.write_sensor(MLS, 0x60FF, 0, 0, 4)
    assert len(seen) == 1


def test_a_monitor_read_from_the_loop_opens_no_second_slot():
    link = _link(FakeBus())
    link.idle()
    slots = link.sensor_token.slots
    link.read(1, 0x1001, 0, timeout=0.05, idle=False)
    assert link.sensor_token.slots == slots
    link.read(1, 0x1001)  # a drive read in a blocking sequence: one slot per drive SDO
    assert link.sensor_token.slots == slots + 1


def test_the_imu_keeps_its_slot_between_the_drive_sdos_of_an_arm(monkeypatch):
    """The 2026-10-09 starvation (engage held the IMU off for 0.35 s) stays fixed: inside a
    blocking sequence every drive SDO opens a slot, and the IMU poll takes it."""
    bus = FakeBus(statusword=0x1637)
    _mls_objects(bus)
    link, imu, track, clk, got, timeouts = _rig(bus, monkeypatch)
    assert imu.start(clk.t) == "sdo"

    def hook():
        clk.t += 0.02
        imu.poll(clk.t)

    link.idle_hook = hook
    _arm(link, 20, None, 0, 30.0, False, False)
    assert link.state == canopen.ARMED and len(got["imu"]) > 10
    assert link.sensor_token.max_reads == 1


def test_the_token_alternates_under_contention_and_a_lone_reader_gets_every_slot():
    tok = SensorToken()
    order = []
    for _ in range(6):
        tok.new_slot()
        for who in ("imu", "mls"):  # the loop's order: the IMU asks first
            if tok.take(who):
                order.append(who)
    assert order == ["imu", "mls"] * 3
    tok = SensorToken()
    for _ in range(5):
        tok.new_slot()
        assert tok.take("imu")
        assert not tok.take("imu"), "two in one slot"
