"""The gyro inside the SICK MLS (CAN node 10), for /imu/data_raw (T10).

Two acquisition modes, chosen at start by reading the sensor:

  TPDO   if the yaw-rate TPDO (1806h) has a COB-ID and is enabled, its
         frames are decoded by the MAPPING THE SENSOR REPORTS (1A06h), not by
         an assumed layout. Enabling that TPDO is a commissioning write
         (`read_imu.py tpdo gyro --go` + sensor restart); this module only
         ever reads.
  SDO    otherwise, one 2034h:3 read per poll (yaw rate, the only axis the
         EKF fuses) and, after every `stamp_every` of them, a 2035h stamp read
         in a poll of its own. ~4 ms of bus time per sample at 125 kbps.

Bus-thread bounds (unified plan WP-B1, 2026-11-16): start() blocks and runs before
the bus loop only; poll() makes at most one DriveLink.read_sensor of POLL_TIMEOUT_S,
with the sensor slot's token (shared with the track reader), rediscovers through
start()'s chain one read per poll, and backs off on a miss RATE (3 of the last 10).

Scaling and the 16-bit millisecond stamp are drivers/canbus/read_imu.py's.
The stamp is only used to reject out-of-order/duplicate samples and to
measure the delivered rate; the ROS header stamp is the receive time, because
the sensor clock and the PC clock are not related (spec §2.4).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from agv_core.drivers.canbus import read_imu  # repo module
from agv_core.drivers.canbus.cia301 import COB_MASK

from amr_base.mls_track import SdoProbe, _Job, _step

OBJ_GYRO_Z = (read_imu.OBJ_GYRO, 3)
OBJ_STAMP = read_imu.OBJ_STAMP
TPDO_GYRO_COMM = read_imu.TPDO_SLOTS["gyro"][0]  # 1806h
TPDO_GYRO_MAP = TPDO_GYRO_COMM + 0x200  # 1A06h
DPS_TO_RAD_S = math.pi / 180.0


@dataclass(frozen=True)
class MapEntry:
    index: int
    sub: int
    bits: int


def parse_mapping(entries: list[int]) -> list[MapEntry]:
    """1A06h:1..n raw u32 entries -> ordered fields (index, sub, bit length)."""
    out = []
    for e in entries:
        if e == 0:
            continue
        out.append(MapEntry((e >> 16) & 0xFFFF, (e >> 8) & 0xFF, e & 0xFF))
    return out


def mapping_bits(mapping: list[MapEntry]) -> int:
    """Total mapped payload width. Raises on a mapping this decoder cannot
    honour (unaligned or wider than one CAN frame)."""
    bits = 0
    for m in mapping:
        if m.bits % 8 or m.bits == 0:
            raise ValueError(
                f"mapping entry {m.index:04X}h:{m.sub:02X} is {m.bits} bits; only byte-aligned handled"
            )
        bits += m.bits
    if bits > 64:
        raise ValueError(f"mapping is {bits} bits, more than one PDO carries")
    return bits


def decode_mapped(data: bytes, mapping: list[MapEntry]) -> dict[tuple[int, int], int]:
    """Slice a PDO payload by its mapping. Values are UNSIGNED; scale later.

    A frame shorter than the mapping is REJECTED, not zero-padded: a padded
    short frame decodes as a yaw rate of exactly 0.0 with a fresh receipt
    time, which is a fabricated measurement (review 2026-09-21, F04).
    """
    need = mapping_bits(mapping)
    data = bytes(data)
    if len(data) * 8 < need:
        raise ValueError(f"PDO is {len(data)} bytes, mapping needs {need // 8}")
    out, bit = {}, 0
    raw = int.from_bytes(data.ljust(8, b"\0"), "little")
    for m in mapping:
        out[(m.index, m.sub)] = (raw >> bit) & ((1 << m.bits) - 1)
        bit += m.bits
    return out


def gyro_z_rad_s(raw16: int, sign: float = 1.0) -> float:
    return read_imu.gyro_dps(raw16 & 0xFFFF) * DPS_TO_RAD_S * sign


class StampTracker:
    """Unwraps the u16 millisecond stamp and flags samples that go backwards.

    A wrap and a 65 s gap are indistinguishable (read_imu.stamp_delta_ms), so
    `accept` also requires the local receive interval to be short; a sample
    that arrives after a long silence resets the chain rather than being
    trusted as a continuation (spec §2.4: discard the first delta after a gap).

    `frozen` (H-P1-7, WP-E7, 2026-11-16) latches on a duplicate stamp - the sensor's clock did
    not move, so neither did the value read beside it - and clears only on a stamp that
    advances. MlsImu publishes no SDO-polled sample while it is set (`frozen_events` counts the
    latches). A stamp after a gap is a new baseline, not evidence of a running clock.
    """

    def __init__(self, gap_s: float = 1.0):
        self.gap_s = gap_s
        self._last_ms: int | None = None
        self._last_t: float | None = None
        self.delta_ms: int | None = None
        self.rejected = 0
        self.resets = 0
        self.frozen = False
        self.frozen_events = 0

    def accept(self, stamp_ms: int | None, t_recv: float) -> bool:
        if stamp_ms is None:
            return True  # polled without a stamp this round
        if self._last_t is not None and t_recv - self._last_t > self.gap_s:
            self.resets += 1
            self._last_ms = None
        if self._last_ms is not None:
            d = read_imu.stamp_delta_ms(stamp_ms, self._last_ms)
            if d == 0 or d > 32768:  # duplicate, or "backwards" read as a huge forward wrap
                self.rejected += 1
                if d == 0 and not self.frozen:
                    self.frozen, self.frozen_events = True, self.frozen_events + 1
                return False
            self.delta_ms = d
            self.frozen = False
        self._last_ms, self._last_t = stamp_ms, t_recv
        return True


@dataclass
class ImuSample:
    t_mono: float
    wz_rad_s: float
    stamp_ms: int | None


class MlsImu:
    """Acquisition state for one MLS. Bus-thread only; `on_sample` is called
    from within the bus loop with each accepted sample."""

    def __init__(
        self,
        link,
        node: int,
        on_sample,
        sign: float = 1.0,
        poll_hz: float = 50.0,
        stamp_every: int = 10,
        log=print,
    ):
        self.link, self.node, self.on_sample, self.sign, self.log = link, node, on_sample, sign, log
        self.poll_period = 1.0 / poll_hz
        self.stamp_every = max(1, int(stamp_every))
        self.mode = "off"
        self.mapping: list[MapEntry] = []
        self.cob_id: int | None = None
        self.tracker = StampTracker()
        self.samples = 0
        self.frozen_drops = 0  # SDO samples withheld while the stamp is frozen (WP-E7)
        self._sdo = SdoProbe(rate=self.MISS_RATE)
        self.rejected = 0  # malformed TPDO payloads (F04)
        self.last_reject = ""
        self.restarts = 0  # rediscoveries after an absent start (F08)
        self._rediscover_at: float | None = None
        self._chain: _Job | None = None  # a rediscovery in progress, one read per poll (WP-B1 b)
        self._next_poll = 0.0
        self._since_stamp = 0  # gyro samples since the last stamp read

    # Retry, backoff and rediscovery: SdoProbe's, shared with the track reader.
    REDISCOVER_S = SdoProbe.REDISCOVER_S
    PROBE_TIMEOUT_S = SdoProbe.PROBE_TIMEOUT_S
    POLL_TIMEOUT_S = 0.012  # one gyro or stamp read in the bus loop (WP-B1 d); ~4 ms is typical
    MISS_RATE = (3, 10)  # back off on 3 misses among the last 10 polls, not 5 in a row (WP-B1 d)

    @property
    def misses(self) -> int:
        return self._sdo.misses

    @property
    def backoffs(self) -> int:
        return self._sdo.backoffs

    @property
    def frozen(self) -> bool:
        return self.tracker.frozen

    # -- start --

    def start(self, now: float | None = None) -> str:
        """The blocking discovery, for BEFORE the bus loop only (WP-B1 b): reads of up to 0.4 s.
        poll() rediscovers through the same chain of reads, one short read per poll."""
        now = time.monotonic() if now is None else now
        self._rediscover_at = None
        job = _Job("discover", [read_imu.OBJ_ENABLE], self._got_enable, failed=self._no_enable)
        while job is not None:
            job = _step(job, lambda key: self.link.read(self.node, *key), now)
        return self.mode

    # The discovery chain: 2006h:02 MEMS enable -> 1806h:01 COB-ID -> 1A06h:00 count -> entries.

    def _no_enable(self, key, now: float) -> None:
        self.log(f"MLS node {self.node} did not answer 2006h:02 - IMU off, probing again")
        self.mode = "off"
        self._rediscover_at = now + self.REDISCOVER_S

    def _probe_answered(self, vals: dict, now: float) -> _Job:
        self.restarts += 1
        self._rediscover_at = None
        return self._got_enable(vals, now)

    def _got_enable(self, vals: dict, now: float) -> _Job:
        self.tracker = StampTracker()  # a re-start must not chain onto the old stamps
        if vals[read_imu.OBJ_ENABLE] == 0:
            self.log("MLS 2006h:02 MEMS = 0: the IMU is disabled in the sensor configuration")
        key = (TPDO_GYRO_COMM, 1)
        return _Job("discover", [key], lambda vals, t: self._got_comm(vals[key]),
                    failed=lambda _key, t: self._got_comm(None))

    def _got_comm(self, raw: int | None) -> _Job | None:
        cob = None if raw is None else raw & COB_MASK
        if raw is None or (raw & read_imu.COB_DISABLED) or not cob:
            return self._poll_by_sdo()
        key = (TPDO_GYRO_MAP, 0)
        # An unreadable count is no mapping (the old `or 0`): no 2034h:03, so polling.
        return _Job("discover", [key], lambda vals, t: self._got_count(cob, vals[key]),
                    failed=lambda _key, t: self._got_count(cob, 0))

    def _got_count(self, cob: int, count: int) -> _Job | None:
        if not count:
            return self._got_mapping(cob, [])
        keys = [(TPDO_GYRO_MAP, i) for i in range(1, count + 1)]
        return _Job("discover", list(keys), lambda vals, t: self._got_mapping(cob, [vals[k] for k in keys]),
                    failed=lambda key, t: self._entry_failed(cob, key))

    def _entry_failed(self, cob: int, key) -> None:
        # A missing entry shifts every field after it: no mapping is safer than a wrong one.
        self.log(f"MLS TPDO 0x{cob:03X} mapping {key[0]:04X}h:{key[1]:02X} unreadable; polling instead")
        self.mapping = []
        return self._poll_by_sdo()

    def _got_mapping(self, cob: int, entries: list[int]) -> None:
        self.mapping = parse_mapping(entries)
        try:
            mapping_bits(self.mapping)
        except ValueError as e:
            self.log(f"MLS TPDO 0x{cob:03X} mapping unusable ({e}); polling instead")
            self.mapping = []
        gyro = next((m for m in self.mapping if (m.index, m.sub) == OBJ_GYRO_Z), None)
        if gyro is not None and gyro.bits != 16:
            self.log(f"MLS TPDO 0x{cob:03X} maps 2034h:03 as {gyro.bits} bits, not 16; polling instead")
            gyro = None
        if gyro is not None:
            self.cob_id = cob
            self.link.router.add(cob, self._on_tpdo)
            self.mode = "tpdo"
            self.log(
                f"MLS yaw rate on TPDO 0x{cob:03X}: "
                + ", ".join(f"{m.index:04X}h:{m.sub:02X}/{m.bits}" for m in self.mapping)
            )
            return None
        self.log(f"MLS TPDO 0x{cob:03X} is enabled but does not carry 2034h:03; polling instead")
        return self._poll_by_sdo()

    def _poll_by_sdo(self) -> None:
        self.mode = "sdo"
        self.log(f"MLS yaw rate by SDO polling at {1.0 / self.poll_period:.0f} Hz (1806h disabled)")
        return None

    # -- TPDO path --

    def _on_tpdo(self, m) -> None:
        try:
            fields = decode_mapped(m.data, self.mapping)
        except ValueError as e:
            # Nothing else moves: no sample, no receipt time, no stamp chain.
            # Downstream freshness expires on its own.
            self.rejected += 1
            self.last_reject = str(e)
            return
        t = time.monotonic()
        stamp = fields.get(OBJ_STAMP)
        if not self.tracker.accept(stamp, t):
            return
        self.samples += 1
        self.on_sample(ImuSample(t, gyro_z_rad_s(fields[OBJ_GYRO_Z], self.sign), stamp))

    # -- SDO path --

    def _read(self, key, timeout: float):
        return self.link.read_sensor(self.node, *key, timeout=timeout)

    def poll(self, now: float) -> None:
        """Once per sensor slot: at most ONE short SDO (WP-B1), and only with the slot's token.
        A refused token is not a miss: the same read is tried at the next slot."""
        if self._chain is None and self.mode == "off" and self._rediscover_at is not None \
                and now >= self._rediscover_at:
            self._rediscover_at = now + self.REDISCOVER_S
            self._chain = _Job("rediscover", [read_imu.OBJ_ENABLE], self._probe_answered)
        if self._chain is not None:
            if self.link.take_sensor("imu"):
                self._chain = _step(self._chain, lambda key: self._read(key, self.PROBE_TIMEOUT_S), now)
            return
        if self.mode != "sdo" or now < self._next_poll or not self.link.take_sensor("imu"):
            return
        self._next_poll = now + self.poll_period
        if self._since_stamp >= self.stamp_every:
            # The stamp in a poll of its own, never beside the gyro (WP-B1 d). It feeds only the
            # tracker (sensor-clock rate, a stuck clock); the SDO samples carry no stamp.
            s = self._read(OBJ_STAMP, self.POLL_TIMEOUT_S)
            if s is None:
                self._missed(now)
                return
            self._sdo.hit()
            self._since_stamp = 0
            self.tracker.accept(s & 0xFFFF, time.monotonic())
            return
        raw = self._read(OBJ_GYRO_Z, self.POLL_TIMEOUT_S)
        if raw is None:
            self._missed(now)
            return
        self._sdo.hit()
        self._since_stamp += 1
        if self.tracker.frozen:
            # The last stamp read repeated the one before: until one advances, this value may be
            # a stuck register, not a measurement (H-P1-7). Not a miss: the sensor answered.
            self.frozen_drops += 1
            return
        self.samples += 1
        self.on_sample(ImuSample(time.monotonic(), gyro_z_rad_s(raw, self.sign), None))

    def _missed(self, now: float) -> None:
        backoff = self._sdo.miss(now)
        if backoff is not None:
            self._next_poll = backoff
