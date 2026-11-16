"""amr_base.mls_imu: mapping-driven TPDO decode, SDO polling fallback, stamp rules."""

import math
import struct

import pytest
from test_mls_track import FakeLink, Frame  # the one SDO/route fake for the MLS tests

from amr_base import mls_imu
from amr_base.mls_imu import MlsImu, StampTracker, decode_mapped, gyro_z_rad_s, parse_mapping

GYRO = 0x2034
STAMP = 0x2035


def test_parse_and_decode_by_mapping():
    entries = [
        (GYRO << 16) | (1 << 8) | 16,
        (GYRO << 16) | (2 << 8) | 16,
        (GYRO << 16) | (3 << 8) | 16,
        (STAMP << 16) | 16,
    ]
    m = parse_mapping(entries + [0])
    assert [(e.index, e.sub, e.bits) for e in m] == [
        (GYRO, 1, 16),
        (GYRO, 2, 16),
        (GYRO, 3, 16),
        (STAMP, 0, 16),
    ]
    data = struct.pack("<hhhH", 5, -6, -1000, 65000)
    f = decode_mapped(data, m)
    assert f[(GYRO, 3)] == 0xFC18 and f[(STAMP, 0)] == 65000
    assert gyro_z_rad_s(f[(GYRO, 3)]) == pytest.approx(-1000 * 125 * 2**-11 * math.pi / 180)
    assert gyro_z_rad_s(f[(GYRO, 3)], sign=-1.0) > 0


def test_stamp_tracker_rejects_duplicates_and_backwards_but_allows_wrap():
    t = StampTracker(gap_s=1.0)
    assert t.accept(65500, 0.00)
    assert t.accept(65530, 0.01) and t.delta_ms == 30
    assert t.accept(10, 0.02) and t.delta_ms == 16  # wrap 65536
    assert not t.accept(10, 0.03) and t.rejected == 1  # duplicate
    assert not t.accept(5, 0.04) and t.rejected == 2  # backwards
    assert t.accept(None, 0.05)  # polled without a stamp this round
    assert t.accept(100, 5.0) and t.resets == 1  # after a gap: chain restarts, no delta trusted


def test_tpdo_mode_when_the_sensor_reports_an_enabled_yaw_rate_pdo():
    objs = {
        (0x2006, 2): 1,
        (mls_imu.TPDO_GYRO_COMM, 1): 0x28A,
        (mls_imu.TPDO_GYRO_MAP, 0): 2,
        (mls_imu.TPDO_GYRO_MAP, 1): (GYRO << 16) | (3 << 8) | 16,
        (mls_imu.TPDO_GYRO_MAP, 2): (STAMP << 16) | 16,
    }
    got = []
    link = FakeLink(objs)
    imu = MlsImu(link, 10, got.append, log=lambda s: None)
    assert imu.start() == "tpdo" and 0x28A in link.routes
    link.routes[0x28A](Frame(struct.pack("<hH", 164, 1000)))  # 164 LSB = 10.01 deg/s
    link.routes[0x28A](Frame(struct.pack("<hH", 164, 1000)))  # duplicate stamp -> dropped
    assert len(got) == 1 and got[0].wz_rad_s == pytest.approx(math.radians(164 * 125 * 2**-11))
    assert got[0].stamp_ms == 1000


def test_sdo_mode_when_the_pdo_is_disabled():
    objs = {(0x2006, 2): 1, (mls_imu.TPDO_GYRO_COMM, 1): 0x80000000, (GYRO, 3): 0xFFFF, (STAMP, 0): 7}
    got = []
    link = FakeLink(objs)
    imu = MlsImu(link, 10, got.append, poll_hz=50.0, stamp_every=2, log=lambda s: None)
    assert imu.start() == "sdo"
    imu.poll(0.0)
    imu.poll(0.01)  # too early
    imu.poll(0.02)
    assert len(got) == 2
    assert got[0].wz_rad_s == pytest.approx(-math.radians(125 * 2**-11))
    assert got[0].stamp_ms is None and got[1].stamp_ms is None
    n = len(link.reads)
    imu.poll(0.04)  # after stamp_every gyro reads: the stamp, in a poll of its own (WP-B1 d)
    assert link.reads[n:] == [(STAMP, 0)] and len(got) == 2 and imu.tracker._last_ms == 7
    imu.poll(0.06)
    assert link.reads[-1] == (GYRO, 3) and len(got) == 3
    assert all(t <= MlsImu.POLL_TIMEOUT_S for t in link.sensor_timeouts)
    assert link.blocking_reads == 2, "poll() used a blocking read"


def test_sdo_mode_backs_off_when_the_sensor_is_absent():
    objs = {(0x2006, 2): 1, (mls_imu.TPDO_GYRO_COMM, 1): 0}
    imu = MlsImu(FakeLink(objs), 10, lambda s: None, log=lambda s: None)
    assert imu.start() == "sdo"
    for k in range(3):
        imu.poll(k * 0.02)
    assert imu.misses == 3  # single misses are retried at the next poll
    imu.poll(0.5)
    assert imu.misses == 3 and imu.backoffs == 1  # 3 of the last 10: not retried before 2 s
    imu.poll(2.1)
    assert imu.misses == 4


def test_a_flapping_sensor_reaches_the_backoff_within_ten_polls():
    """WP-B1 d: one miss in three never made 5 in a row, so it was never backed off."""
    objs = {(0x2006, 2): 1, (mls_imu.TPDO_GYRO_COMM, 1): 0, (GYRO, 3): 5}
    link = FakeLink(objs)
    imu = MlsImu(link, 10, lambda s: None, stamp_every=100, log=lambda s: None)
    assert imu.start() == "sdo"
    t = 0.0
    for k in range(10):
        if k % 3 == 2:
            objs.pop((GYRO, 3), None)
        else:
            objs[(GYRO, 3)] = 5
        imu.poll(t)
        t += 0.025
        if imu.backoffs:
            break
    assert imu.backoffs == 1 and imu.misses == 3 and k < 10
    n = len(link.reads)
    imu.poll(t + 1.0)
    assert len(link.reads) == n, "polled during the backoff"


def test_a_refused_token_is_not_a_miss_and_the_read_waits_for_the_next_slot():
    objs = {(0x2006, 2): 1, (mls_imu.TPDO_GYRO_COMM, 1): 0, (GYRO, 3): 5}
    link = FakeLink(objs)
    got = []
    imu = MlsImu(link, 10, got.append, log=lambda s: None)
    assert imu.start() == "sdo"
    link.tokens = [False, True]
    imu.poll(0.0)
    assert not got and imu.misses == 0
    imu.poll(0.001)  # next slot, same poll period: the deferred read goes now
    assert len(got) == 1


# ---- F04: malformed PDOs never become a measurement --------------------------


def _tpdo_objs(bits=16):
    return {
        (0x2006, 2): 1,
        (mls_imu.TPDO_GYRO_COMM, 1): 0x28A,
        (mls_imu.TPDO_GYRO_MAP, 0): 2,
        (mls_imu.TPDO_GYRO_MAP, 1): (GYRO << 16) | (3 << 8) | bits,
        (mls_imu.TPDO_GYRO_MAP, 2): (STAMP << 16) | 16,
    }


@pytest.mark.parametrize("data", [b"", b"\x01", b"\x01\x02", b"\x01\x02\x03"])
def test_a_short_frame_is_rejected_not_zero_padded(data):
    """An empty frame used to decode as yaw rate 0.0 with a fresh receipt
    time - a fabricated measurement that kept the IMU 'fresh' downstream."""
    got = []
    link = FakeLink(_tpdo_objs())
    imu = MlsImu(link, 10, got.append, log=lambda s: None)
    assert imu.start() == "tpdo"
    link.routes[0x28A](Frame(data))
    assert got == [] and imu.samples == 0
    assert imu.rejected == 1 and "mapping needs 4" in imu.last_reject
    assert imu.tracker._last_ms is None, "a rejected frame touched the stamp chain"
    # a whole frame still works, and the value is the signed one
    link.routes[0x28A](Frame(struct.pack("<hH", -164, 1000)))
    assert len(got) == 1 and got[0].wz_rad_s < 0 and imu.samples == 1


def test_decode_mapped_needs_every_mapped_byte():
    m = parse_mapping([(GYRO << 16) | (3 << 8) | 16, (STAMP << 16) | 16])
    with pytest.raises(ValueError):
        mls_imu.decode_mapped(b"\x00\x00\x00", m)
    assert mls_imu.decode_mapped(b"\x00\x00\x00\x00", m)[(GYRO, 3)] == 0
    with pytest.raises(ValueError):
        mls_imu.mapping_bits(parse_mapping([(GYRO << 16) | (3 << 8) | 12]))
    with pytest.raises(ValueError):
        mls_imu.mapping_bits(parse_mapping([(GYRO << 16) | (3 << 8) | 64, (STAMP << 16) | 16]))


def test_a_mapping_with_the_wrong_gyro_width_falls_back_to_polling():
    link = FakeLink(_tpdo_objs(bits=32))
    imu = MlsImu(link, 10, lambda s: None, log=lambda s: None)
    assert imu.start() == "sdo" and not link.routes


# ---- F08: a sensor absent at boot is picked up later -----------------------


def test_an_absent_sensor_is_rediscovered_with_one_short_probe_per_period():
    link = FakeLink({})
    got = []
    imu = MlsImu(link, 10, got.append, log=lambda s: None)
    assert imu.start(now=0.0) == "off"
    assert link.blocking_reads == 1
    imu.poll(1.0)
    assert len(link.reads) == 1, "polled while off before the rediscovery period"
    imu.poll(5.0)
    assert link.reads[-1] == (0x2006, 2) and imu.mode == "off"
    assert link.sensor_timeouts == [MlsImu.PROBE_TIMEOUT_S]
    imu.poll(7.0)
    assert len(link.reads) == 2, "probed more than once per period"
    # the sensor comes up: start()'s chain, ONE short read per poll (WP-B1 b)
    link.objects.update(_tpdo_objs())
    for k in range(5):  # enable, 1806h:01, 1A06h:00, two entries
        n = len(link.reads)
        imu.poll(10.0 + 0.02 * k)
        assert len(link.reads) - n == 1
    assert imu.mode == "tpdo" and imu.restarts == 1 and 0x28A in link.routes
    assert link.blocking_reads == 1, "the rediscovery used a blocking read"
    assert all(t <= 0.05 for t in link.sensor_timeouts)
    link.routes[0x28A](Frame(struct.pack("<hH", 164, 1000)))
    assert len(got) == 1


def test_an_unreadable_mapping_entry_polls_instead_of_shifting_the_fields():
    o = _tpdo_objs()
    del o[(mls_imu.TPDO_GYRO_MAP, 1)]
    link = FakeLink(o)
    imu = MlsImu(link, 10, lambda s: None, log=lambda s: None)
    assert imu.start() == "sdo" and not link.routes and imu.mapping == []

def test_a_duplicate_stamp_latches_frozen_until_the_stamp_advances():
    """H-P1-7 (WP-E7): a repeated 2035h stamp means the sensor's clock stopped, so the 2034h:03
    value beside it may be a stuck register: no SDO sample is published until a stamp advances."""
    t = StampTracker(gap_s=1.0)
    assert t.accept(100, 0.0) and not t.frozen
    assert not t.accept(100, 0.1) and t.frozen and t.frozen_events == 1
    assert not t.accept(100, 0.2) and t.frozen_events == 1  # one latch, not one per repeat
    assert t.accept(None, 0.25) and t.frozen  # an unstamped poll proves nothing
    assert t.accept(220, 0.3) and not t.frozen


def test_sdo_samples_stop_while_the_stamp_is_frozen():
    objs = {(0x2006, 2): 1, (mls_imu.TPDO_GYRO_COMM, 1): 0x80000000, (GYRO, 3): 0x0010, (STAMP, 0): 7}
    got = []
    link = FakeLink(objs)
    imu = MlsImu(link, 10, got.append, poll_hz=50.0, stamp_every=1, log=lambda s: None)
    assert imu.start() == "sdo"
    t = 0.0
    for _ in range(4):  # gyro, stamp 7, gyro, stamp 7 again (duplicate)
        imu.poll(t)
        t += 0.02
    assert imu.frozen and len(got) == 2
    imu.poll(t)  # gyro read, withheld
    t += 0.02
    assert len(got) == 2 and imu.frozen_drops == 1
    objs[(STAMP, 0)] = 30
    imu.poll(t)  # the stamp advances
    t += 0.02
    imu.poll(t)
    assert not imu.frozen and len(got) == 3


def test_fault_with_a_stop_owed_runs_no_imu_poll_and_resumes_once_settled():
    """H-P1-7 (WP-E7): link.idle() skips the IMU hook in FAULT while stop_pending or
    stop_unconfirmed is non-empty, and runs it in FAULT once both are empty."""
    from test_canopen import FakeBus, _link

    from amr_base import canopen

    link = _link(FakeBus())
    polls = []
    link.idle_hook = lambda: polls.append(1)
    link.state = canopen.FAULT
    link.stop_pending = {1}
    link.idle()
    link.stop_pending, link.stop_unconfirmed = set(), ["node 2: still turning (40 r/min)"]
    link.idle()
    assert polls == [] and link.sensor_paused
    link.stop_unconfirmed = []
    link.idle()
    assert polls == [1] and not link.sensor_paused
