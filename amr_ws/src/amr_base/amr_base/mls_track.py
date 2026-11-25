"""The track (line) reading of the SICK MLS (CAN node 10), for /amr/line_track.

Line-follow plan §1.1. Writes no configuration to the sensor; it sends NMT Start
addressed to the MLS node, so TPDO1 flows (see _nmt_start), and - only when the
profile sets mls.event_clear - the reset of the latched event flag (2080h:01,
through guard.check_sensor; manuals/mls-diagnostics-plan.md E2).
Decoding is drivers/canbus/read_mls.py's (TPDO1 layout, Standard/Combi, #LCP).

Acquisition, chosen by `mode`:

  tpdo  listen on TPDO1 (0x180+node). Frames only flow while the sensor is
        Operational; in Pre-operational this mode sees nothing (stale).
  sdo   read the TPDO1 fields over SDO (2021h:01..04, 2022h), ONE read per
        bus tick so the drive setpoint is never held up; a sample completes
        every five reads (10 Hz at most on a 50 Hz loop). Good for the
        Monitor, too slow and too skewed for control.
  auto  tpdo, falling back to sdo polling when no TPDO1 frame arrived within
        `tpdo_wait_s`; the first TPDO1 frame switches back to tpdo.
  off   nothing.

Whatever the mode, start() reads the variant (2006h:01), the TPDO1 COB-ID
(1800h:01), its event timer (1800h:05, WP-E8) and one live SDO sample, so a restart
alone shows whether a tape is under the sensor.

Bus-thread bounds (unified plan WP-B1, 2026-11-16). start() blocks (0.4 s reads) and
runs before the bus loop only. Inside poll() every SDO is DriveLink.read_sensor
(<= 0.05 s, no nested IMU poll), takes the slot's one sensor token shared with the
IMU (DriveLink.take_sensor), and a rediscovery is start()'s chain of reads run ONE
per poll. NMT Start is nmt_nowait: sent, never pumped for.

Marker configuration (mls-marker-plan 5.2, 2026-10-09). When the profile turns
markers on, the sensor's marker objects (2028h:01-03, 2029h, 202Dh:05) are READ
and compared with what the profile expects - never written. Not in start()'s
chain: it also runs from _rediscover() inside poll() while the drives may be
moving. The check is a queue drained ONE read per poll, with
the short probe timeout, and only in tpdo mode (sdo mode already spends its read).
It runs after every start, again whenever the TPDO stream returns after a gap (a
sensor reboot never reaches _rediscover), and every MARKER_RECHECK_S.
`markers_ok` is true only when the check passed and the stream is TPDO.

SDO jobs (mls-diagnostics-plan E4). The marker check, the event cause and the
temperature share ONE queue: one SDO operation per poll, TPDO mode only, the short
probe timeout. A job that times out is dropped and retried later; it never blocks
the others for longer than that one read.

Event detection (mls-diagnostics-plan M1/M2, manual 8.8). A rising event flag
(TPDO1 status bit 7) queues the cause reads 2080h:02/:04/:05. A magnetic-field
event is reported through `on_event` only if a track was under the sensor on the
sample before (E5: leaving the tape is not a weak tape); otherwise it is counted
as `events_no_track`. The flag latches, so with mls.event_clear set the job then
writes 2080h:01; a flag still high CLEAR_MIN_S after a clear is a new event. A
failed or refused clear turns the clearing off for the rest of the run. Without
the clear only the first event after the flag was last reset is seen.
The temperature (2070h:01 and its thresholds :06/:07) is read every TEMP_PERIOD_S
and at once after a temperature event; `temp` holds the last decode.

Every sample carries its `source`; the line follower accepts only fresh ones,
which the SDO path cannot deliver at control rate.

TPDO1 holes (unified plan WP-E8, H-P1-8, 2026-11-16). The discovery chain also reads the
event timer 1800h:05 (read-only). A frame more than GAP_FACTOR x that period after the one
before is a hole: `tpdo_gaps`, `max_gap_ms`, and the sample's reading carries "gap": True,
on which the marker detector breaks continuity (no event across a hole). Holes shorter than
the stale time leave `stale_periods` alone. While the vehicle stands (`moving` says so) a
hole is not counted unless GAPS_WHILE_STATIONARY: if 1800h:05 reads 0 the sensor sends on
change only and a standing vehicle sends nothing. Diagnostic only, never a stop here:
byte-identical frames in a row (`max_identical_s`), short frames (`rejected_frames`),
reserved #LCP values (`reserved_nlcp`).

Reboots (WP-P9, H-P2-3). The MLS boot-up frame (0x700+node, data 0x00) is routed, read only:
`reboots`, a new start (new marker generation, markers untrusted until re-checked, event flag
re-armed) and the discovery chain again, one read per poll - 2006h:01 variant, 1800h:01,
1800h:05 - without the SDO snapshot. Nothing is written to the sensor (no 1017h).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from agv_core.drivers.canbus import mls_markers, read_mls  # repo module
from agv_core.drivers.canbus.cia301 import HEARTBEAT_COB_BASE

SOURCE_TPDO, SOURCE_SDO = mls_markers.SOURCE_TPDO, mls_markers.SOURCE_SDO
BOOT_UP = 0x00  # the NMT boot-up frame's one data byte (CiA 301)
TPDO1_TIMER = (read_mls.TPDO1_COMM, 5)  # event timer, ms; 0 = on change only
MODES = (SOURCE_TPDO, SOURCE_SDO, "auto", "off")
SDO_ITEMS = read_mls.TRACK_SDO_ITEMS

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass
class TrackSample:
    t_mono: float
    reading: dict  # read_mls.decode_tpdo1's dict
    source: str  # "tpdo" | "sdo"

    @property
    def lcp_mm(self) -> list[int]:
        return [p for p, _w in self.reading["lcp"]]

    @property
    def nlcp(self) -> int:
        return self.reading["nlcp"]


class RateLimit:
    """At most one report per `min_s`; the ones in between are counted into the next.
    Pure and clock-fed: allow(now) -> None (hold it back) or the number held back
    since the last report."""

    def __init__(self, min_s: float):
        self.min_s, self._t, self._held = min_s, None, 0

    def allow(self, now: float) -> int | None:
        if self._t is not None and now - self._t < self.min_s:
            self._held += 1
            return None
        held, self._t, self._held = self._held, now, 0
        return held


@dataclass
class _Job:
    """One SDO job: read `keys` in order, then `done(vals, now)`; then, if set, the
    write (index, sub, value, size) and `wrote(ok, detail, now)`."""

    purpose: str
    keys: list
    done: object
    write: tuple | None = None
    wrote: object = None
    vals: dict = field(default_factory=dict)
    failed: object = None  # failed(key, now) when a read gets no answer


def _step(job: _Job, read, now: float) -> _Job | None:
    """ONE read of a discovery-chain job (unified plan WP-B1 b). A chain job's done(vals, now) and
    failed(key, now) return the next job, or None when the chain ends. -> the job to carry on
    with: the same one (keys left), the next one, or None.

    start() runs a chain to the end with blocking reads (before the bus loop only); poll() runs
    the same chain one short read per bus tick, so a rediscovery never stalls the loop."""
    key = job.keys[0]
    v = read(key)
    if v is None:
        return job.failed(key, now) if job.failed else None
    job.vals[key] = v
    job.keys.pop(0)
    return job if job.keys else job.done(job.vals, now)


class SdoProbe:
    """Miss bookkeeping for one polled SDO stream on the MLS. Clock-fed.

    One late reply (a busy bus) is retried at the next poll; only a sensor that
    keeps not answering is backed off. A sensor that did not answer at start is
    probed again every REDISCOVER_S with one PROBE_TIMEOUT_S read, so a
    late-booting MLS is picked up without starving the wheel loop.

    Backoff on MISSES_BEFORE_BACKOFF misses in a row, or - with `rate=(n, window)` - on n
    misses among the last `window` polls, which also catches a sensor that answers two polls
    in three (WP-B1 d, the IMU). The window starts empty after a backoff.
    """

    MISSES_BEFORE_BACKOFF = 5
    BACKOFF_S = 2.0  # an absent sensor costs one short timeout every 2 s
    REDISCOVER_S = 5.0
    PROBE_TIMEOUT_S = 0.05

    def __init__(self, rate: tuple[int, int] | None = None) -> None:
        self.misses = 0
        self.consecutive = 0
        self.rate = rate
        self._window: list[bool] = []  # True = a miss, newest last
        self.backoffs = 0

    def miss(self, now: float) -> float | None:
        """Count a miss; the time to back off until, or None to retry next poll."""
        self.misses += 1
        self.consecutive += 1
        if self.rate is None:
            backoff = self.consecutive >= self.MISSES_BEFORE_BACKOFF
        else:
            self._record(True)
            backoff = sum(self._window) >= self.rate[0]
        if not backoff:
            return None
        self.backoffs += 1
        self._window = []
        return now + self.BACKOFF_S

    def hit(self) -> None:
        self.consecutive = 0
        if self.rate is not None:
            self._record(False)

    def _record(self, missed: bool) -> None:
        self._window = (self._window + [missed])[-self.rate[1]:]


@dataclass
class _SdoCycle:
    index: int = 0
    values: list = field(default_factory=list)



NMT_RESET_NODE = 0x81
# Boot-up plus the IMU's 640 ms initialisation (MLS OI 8.6, all zeros until then), with margin.
RESET_SETTLE_S = 1.5
RESET_STEP_S = 0.05


def reset_mls(link, node: int, log=print, settle_s: float = RESET_SETTLE_S, clock=time.monotonic) -> None:
    """NMT Reset Node to the MLS alone, once the bus is up and before its IMU and track readers start
    (profile mls.reset_at_start). 2026-11-25, agv-02: after a power-up its MLS read one tape as two
    tracks ~22 mm apart, past J-BMERGE, for whole trips; after a software reset it read one track, every
    time it was tried. Only `node` is addressed (nmt_nowait refuses a broadcast). The wait routes what
    arrives, so the boot-up frame is gone before MlsTrack listens for reboots, and keeps the PC heartbeat
    going: the drives must not see a silent PC."""
    link.nmt_nowait(NMT_RESET_NODE, node)
    log(f"MLS node {node}: NMT Reset Node at start (mls.reset_at_start), waiting {settle_s:.1f} s")
    end = clock() + settle_s
    while clock() < end:
        link.keepalive()
        link.router.pump(RESET_STEP_S)


class MlsTrack:
    """Acquisition state for one MLS. Bus-thread only; `on_sample` is called
    from within the bus loop with every decoded sample."""

    # A sensor that did not answer at start (or whose TPDO1 configuration could
    # not be read) is probed again; see SdoProbe.
    REDISCOVER_S = SdoProbe.REDISCOVER_S
    PROBE_TIMEOUT_S = SdoProbe.PROBE_TIMEOUT_S
    MARKER_RECHECK_S = 60.0
    MARKER_RETRY_S = 5.0
    TEMP_FIRST_S = 10.0  # the first temperature read, after start (the marker check goes first)
    TEMP_PERIOD_S = 60.0
    EVENT_RETRY_S = 5.0  # a flag whose cause could not be read is tried again this often
    CLEAR_MIN_S = 1.0  # a flag still high this long after a clear is a new event
    # TPDO1 holes (WP-E8). 3x, not 1.5x: the frame stamp is the kernel's only on socketcan.
    GAP_FACTOR = 3.0
    DEFAULT_PERIOD_MS = 10  # 1800h:05 default (MLS OI 8.1.3), until it is read or when it reads 0
    # WP-E8 gate, profile-free: True counts holes while the vehicle stands too. False until the
    # bench reads 1800h:05 on each unit (unified plan §5): if it reads 0 (on change), a standing
    # vehicle sends nothing and every restart of motion would look like a hole. False can only
    # hide a hole while stopped, where no marker passes.
    GAPS_WHILE_STATIONARY = False

    def __init__(
        self,
        link,
        node: int,
        on_sample,
        mode: str = "auto",
        sdo_hz: float = 10.0,
        tpdo_wait_s: float = 1.0,
        stale_tpdo_s: float = 0.1,
        expected_variant: int | None = 0,
        markers: dict | None = None,
        on_event=None,
        event_clear: int | None = None,
        moving=None,
        clock=time.monotonic,
        log=print,
    ):
        if mode not in MODES:
            raise ValueError(f"mls track mode {mode!r} not in {MODES}")
        self.link, self.node, self.on_sample, self.log, self.clock = link, node, on_sample, log, clock
        self.want = mode
        self.mode = "off"
        self.sdo_period = 1.0 / max(0.1, sdo_hz)
        self.tpdo_wait_s = tpdo_wait_s
        self.stale_tpdo_s = stale_tpdo_s
        self.expected_variant = expected_variant
        self.cob_id = read_mls.TPDO1_COB + node
        self.variant: int | None = None
        self.combi = False
        self.tpdo_enabled: bool | None = None
        self.last: TrackSample | None = None
        self.samples = 0
        self.tpdo_frames = 0
        self._sdo = SdoProbe()
        self.stale_periods = 0
        self.nmt_starts = 0
        self.restarts = 0  # rediscoveries after an incomplete start (F08)
        self._rediscover_at: float | None = None
        self._chain: _Job | None = None  # a rediscovery in progress, one read per poll (WP-B1 b)
        self._next_nmt = 0.0
        self._last_tpdo_t: float | None = None
        self.variant_mismatches = 0
        self.start_count = 0  # every start() is a new marker generation
        # marker configuration check: {(index, sub): wanted value} or None (markers off)
        self.marker_expect = dict(markers) if markers else None
        self.marker_status = "off" if not markers else "checking"
        self.marker_checks = 0
        self._jobs: list[_Job] = []
        self._mnext: float | None = None
        self._mrearm = False
        # event detection and temperature (mls-diagnostics-plan)
        self.on_event = on_event
        self.event_clear = event_clear if event_clear in (0, 1) else None
        self.clear_state = "off" if self.event_clear is None else "on"
        self.events_field = 0
        self.events_no_track = 0
        self.events_temp = 0
        self.events_other = 0  # flag set, source neither field nor temperature
        self.events_unread = 0
        self.clears = 0
        self.temp: dict | None = None
        self.temp_unread = 0
        self.track_level_min: int | None = None
        self._temp_next: float | None = None
        self._ev_prev_flag: bool | None = None
        self._ev_prev_nlcp: int | None = None
        self._ev_retry_at: float | None = None
        self._ev_cleared_at: float | None = None
        self._stale = True
        self._t_start = 0.0
        self._next_cycle = 0.0
        self._cycle = _SdoCycle()
        # TPDO1 holes and frozen frames (WP-E8); `moving` is a callable -> bool, None = unknown
        # (every hole counts)
        self.moving = moving
        self.tpdo_period_ms: int | None = None  # 1800h:05 as read
        self.tpdo_gaps = 0
        self.max_gap_ms = 0.0
        self.gaps_stationary = 0  # holes not counted because the vehicle stood
        self.rejected_frames = 0  # TPDO1 frames too short to decode
        self.reserved_nlcp = 0  # frames with a #LCP value the manual reserves
        self.max_identical_s = 0.0
        self._prev_frame_t: tuple | None = None  # (frame-stamped?, t) of the last frame
        self._prev_data: bytes | None = None
        self._ident_since = 0.0
        # reboots (WP-P9)
        self.reboots = 0
        self._rebooting = False  # the chain after a boot-up frame skips the SDO snapshot

    @property
    def misses(self) -> int:
        return self._sdo.misses

    # -- start --

    def start(self) -> str:
        """The blocking discovery, for BEFORE the bus loop only (WP-B1 b): its reads wait up to
        0.4 s each. poll() rediscovers through the same chain, one short read per poll."""
        self._begin(self.clock())
        if self.want == "off":
            self.mode = "off"
            return self.mode
        self.link.router.add(HEARTBEAT_COB_BASE + self.node, self._on_boot)  # read-only (WP-P9)
        job = _Job("discover", [read_mls.OBJ_VARIANT], self._got_variant, failed=self._no_variant)
        while job is not None:
            job = _step(job, lambda key: self.link.read(self.node, *key), self.clock())
        return self.mode

    def _begin(self, now: float) -> None:
        self._t_start = now
        self._rediscover_at = None
        self.start_count += 1
        if self.marker_expect:
            self._arm_marker_check(self._t_start, reset=True)
        self._ev_prev_flag = None  # a (re)started sensor: a flag already up is an event
        self._temp_next = self._t_start + self.TEMP_FIRST_S

    # The discovery chain: 2006h:01 variant -> 1800h:01 TPDO1 -> the five-read snapshot.

    def _no_variant(self, key, now: float) -> None:
        self.log(f"MLS node {self.node} did not answer 2006h:01 - track reading off, probing again")
        self.mode = "off"
        self._rediscover_at = self._t_start + self.REDISCOVER_S

    def _probe_answered(self, vals: dict, now: float) -> _Job:
        """Rediscovery: the probe answered, so this is a (re)start from here on."""
        self.restarts += 1
        self._begin(now)
        return self._got_variant(vals, now)

    def _got_variant(self, vals: dict, now: float) -> _Job:
        v = vals[read_mls.OBJ_VARIANT]
        self.variant, self.combi = v, v in read_mls.COMBI_VARIANTS
        if self.expected_variant is not None and v != self.expected_variant:
            self.variant_mismatches += 1
            self.log(
                f"MLS 2006h:01 variant {v} ({read_mls.VARIANT_NAMES.get(v, '?')}), "
                f"commissioned {self.expected_variant}: decoding as reported"
            )
        key = (read_mls.TPDO1_COMM, 1)
        return _Job("discover", [key], lambda vals, t: self._got_comm(vals[key], t),
                    failed=lambda _key, t: self._got_comm(None, t))

    def _got_comm(self, raw: int | None, now: float) -> _Job:
        if raw is None:
            # One failed read must not pin the reader to SDO for the rest of
            # the run: try the whole discovery again later.
            self.log("MLS 1800h:01 did not answer: TPDO1 unknown, rediscovering later")
            self._rediscover_at = self._t_start + self.REDISCOVER_S
        self.tpdo_enabled = raw is not None and not (raw & read_mls.COB_DISABLED)
        if self.tpdo_enabled and (raw & 0x7FF) != self.cob_id:
            self.log(f"MLS TPDO1 COB-ID 0x{raw & 0x7FF:03X}, not 0x{self.cob_id:03X}: listening there")
            self.cob_id = raw & 0x7FF
        if self.want in ("tpdo", "auto") and self.tpdo_enabled:
            self.link.router.add(self.cob_id, self._on_tpdo)
            self._nmt_start(self._t_start)
        return _Job("discover", [TPDO1_TIMER], lambda vals, t: self._got_timer(vals[TPDO1_TIMER], t),
                    failed=lambda _key, t: self._got_timer(None, t))

    def _got_timer(self, raw: int | None, now: float) -> _Job | None:
        """1800h:05, the TPDO1 event timer (WP-E8). Unanswered: the manual default is assumed."""
        if raw is not None:
            self.tpdo_period_ms = int(raw) & 0xFFFF
            if self.tpdo_period_ms == 0:
                self.log("MLS 1800h:05 = 0: TPDO1 on change only - TPDO1 holes not counted while standing")
        if self._rebooting:
            self._rebooting = False
            self._finish()
            return None  # after a reboot: no SDO snapshot inside a TPDO stream
        return _Job("discover", list(SDO_ITEMS), self._got_snapshot, failed=self._no_snapshot)

    def _got_snapshot(self, vals: dict, now: float) -> None:
        r = read_mls.decode_sdo_values([vals[k] for k in SDO_ITEMS], self.combi)
        self.log(f"MLS track at start (SDO): #LCP {r['nlcp']} {r['nlcp_label']}; {read_mls.fmt_reading(r)}")
        self._emit(r, SOURCE_SDO, self.clock())
        self._finish()

    def _no_snapshot(self, key, now: float) -> None:
        self.log("MLS track: start snapshot incomplete (SDO)")
        self._finish()

    def _finish(self) -> None:
        v = self.variant
        if self.want == "sdo" or (self.want == "auto" and not self.tpdo_enabled):
            self.mode = "sdo"
        elif self.tpdo_enabled:
            self.mode = "tpdo"  # auto: falls back in poll() if nothing arrives
        else:
            self.mode = "off"
            self.log("MLS TPDO1 (1800h:01) is disabled - track reading off (mode tpdo)")
        self.log(
            f"MLS track: variant {v} ({'Combi' if self.combi else 'Standard'}), TPDO1 "
            f"{f'0x{self.cob_id:03X}' if self.tpdo_enabled else 'disabled'}, mode {self.mode}"
        )

    # -- samples --

    def _emit(self, reading: dict, source: str, t: float) -> None:
        self.last = TrackSample(t, reading, source)
        self.samples += 1
        self._stale = False
        self.on_sample(self.last)

    def _on_tpdo(self, m) -> None:
        data = bytes(m.data)
        r = read_mls.decode_tpdo1(data, self.combi)
        if r is None:
            self.rejected_frames += 1
            return
        if r["nlcp"] not in read_mls.NLCP_MEANING:
            self.reserved_nlcp += 1
        self.tpdo_frames += 1
        self._last_tpdo_t = self.clock()
        if self._hole(getattr(m, "timestamp", None)):
            r["gap"] = True  # the marker detector breaks continuity on it
        self._frozen(data, self._last_tpdo_t)
        if self._mrearm:
            # The stream is back after a gap: the sensor may have rebooted (to other
            # settings). Untrusted until re-read.
            self._mrearm = False
            if self.marker_expect:
                self._arm_marker_check(self._last_tpdo_t, reset=True)
            self._ev_prev_flag = None
        if self.mode != "tpdo":
            self.log(f"MLS TPDO1 frames on 0x{self.cob_id:03X}: track reading by TPDO")
            self.mode = "tpdo"
            self._cycle = _SdoCycle()
        self._event_watch(r, self._last_tpdo_t)
        self._emit(r, SOURCE_TPDO, self.clock())

    def _hole(self, stamp: float | None) -> bool:
        """WP-E8: True when this frame ends a hole that counts. `stamp` is the frame's receive
        time (python-can's, the kernel's on socketcan); 0/None falls back to the clock."""
        t = (True, stamp) if stamp else (False, self._last_tpdo_t)
        prev, self._prev_frame_t = self._prev_frame_t, t
        if prev is None or prev[0] != t[0] or t[1] < prev[1]:
            return False  # the first frame, or the stamp's source changed
        t, prev = t[1], prev[1]
        period = self.tpdo_period_ms or self.DEFAULT_PERIOD_MS
        dt_ms = (t - prev) * 1000.0
        if dt_ms <= self.GAP_FACTOR * period:
            return False
        if not self.GAPS_WHILE_STATIONARY and self.moving is not None and not self.moving():
            self.gaps_stationary += 1
            return False
        self.tpdo_gaps += 1
        self.max_gap_ms = max(self.max_gap_ms, dt_ms)
        return True

    def _frozen(self, data: bytes, now: float) -> None:
        """Phase 1 frozen-sensor watch (H-P1-8): the longest run of byte-identical TPDO1 frames.
        Diagnostic only - a standing vehicle on a timer sends identical frames too."""
        if data != self._prev_data:
            self._prev_data, self._ident_since = data, now
            return
        self.max_identical_s = max(self.max_identical_s, now - self._ident_since)

    def _on_boot(self, m) -> None:
        """0x700+node: only the boot-up frame counts (WP-P9). The sensor lost nothing we wrote
        (we write nothing but the optional event reset) but may hold other settings: a new
        start, the identity chain again one read per poll, markers untrusted until re-checked."""
        if not m.data or m.data[0] != BOOT_UP:
            return
        now = self.clock()
        self.reboots += 1
        self.log(f"MLS node {self.node} boot-up frame: the sensor rebooted - markers untrusted, "
                 "re-reading 2006h:01 / 1800h")
        self._begin(now)
        self._rebooting = True
        self._chain = _Job("reboot", [read_mls.OBJ_VARIANT], self._got_variant, failed=self._reboot_unread)

    def _reboot_unread(self, key, now: float) -> None:
        self._rebooting = False
        self.log(f"MLS {key[0]:04X}h:{key[1]:02X} did not answer after the reboot: rediscovering later")
        self._rediscover_at = now + self.REDISCOVER_S

    def _nmt_start(self, now: float) -> None:
        """NMT Start addressed to the MLS only. TPDO1 flows in Operational and
        nothing else on this bus puts node 10 there: the sensor boots
        Operational but the drive link's Pre-operational at arm used to take
        it down (2026-09-21). The drives are not addressed. Rate-limited so a
        sensor that will not start is asked every 2 s, not every bus tick."""
        if now < self._next_nmt:
            return
        self._next_nmt = now + 2.0
        self.nmt_starts += 1
        self.link.nmt_nowait(0x01, self.node)  # no 50 ms pump on the bus thread (WP-B1 c)

    def stale_after(self) -> float:
        return self.stale_tpdo_s if self.mode == "tpdo" else 3.0 * self.sdo_period

    def age(self, now: float) -> float | None:
        return None if self.last is None else now - self.last.t_mono

    def _rediscover(self, now: float) -> bool:
        """Probe an absent/partly-read sensor; when it answers, the rest of start()'s chain.
        ONE short read per poll (WP-B1 b): the old blocking start() here held the bus thread
        for up to 7 x 0.4 s with the drives possibly moving. True while it owns this poll."""
        if self._chain is None:
            if self._rediscover_at is None or now < self._rediscover_at or self.want == "off":
                return False
            self._rediscover_at = now + self.REDISCOVER_S
            self._chain = _Job("rediscover", [read_mls.OBJ_VARIANT], self._probe_answered)
        if self.link.take_sensor("mls"):
            self._chain = _step(self._chain, self._short_read, now)
        return True

    def _short_read(self, key):
        return self.link.read_sensor(self.node, *key, timeout=self.PROBE_TIMEOUT_S)

    def poll(self, now: float) -> None:
        """Once per bus tick: stale bookkeeping, auto fallback, at most ONE SDO read."""
        if self._rediscover(now):
            return
        a = self.age(now)
        if (a is None or a > self.stale_after()) and not self._stale:
            self._stale = True
            self.stale_periods += 1
        want_tpdo = self.want in ("tpdo", "auto") and self.tpdo_enabled and self.mode != "off"
        no_stream = self._last_tpdo_t is None or now - self._last_tpdo_t > self.tpdo_wait_s
        if want_tpdo and no_stream and now - self._t_start >= self.tpdo_wait_s:
            # The stream never came, or died (the sensor was put back to
            # Pre-operational): ask node 10 to start, again and again, and in
            # auto mode poll by SDO meanwhile so the reading is not lost. The
            # first TPDO1 frame switches back (see _on_tpdo).
            self._nmt_start(now)
            self._mrearm = True
            if self.mode == "tpdo" and self.want == "auto":
                self.log(
                    f"MLS: no TPDO1 on 0x{self.cob_id:03X} for {self.tpdo_wait_s:.1f} s "
                    "(Pre-operational?): polling by SDO"
                )
                self.mode = "sdo"
        if self.mode == "tpdo":
            self._sdo_poll(now)
        if self.mode != "sdo":
            return
        c = self._cycle
        if c.index == 0 and now < self._next_cycle:
            return
        if not self.link.take_sensor("mls"):
            return  # this tick's one sensor SDO went to the IMU: next tick
        if c.index == 0:
            self._next_cycle = now + self.sdo_period
        index, sub = SDO_ITEMS[c.index]
        v = self.link.read_sensor(self.node, index, sub, timeout=0.05)
        if v is None:
            self._cycle = _SdoCycle()
            backoff = self._sdo.miss(now)
            if backoff is not None:
                self._next_cycle = backoff
            return
        self._sdo.hit()
        c.values.append(v)
        c.index += 1
        if c.index == len(SDO_ITEMS):
            self._cycle = _SdoCycle()
            vals = c.values
            self._emit(read_mls.decode_sdo_values(vals, self.combi), SOURCE_SDO, self.clock())

    # -- SDO jobs: one queue, one operation per poll (E4) --

    def _pending(self, purpose: str) -> bool:
        return any(j.purpose == purpose for j in self._jobs)

    def _schedule(self, now: float) -> None:
        recheck = self._mnext is not None and now >= self._mnext
        if self.marker_expect and recheck and not self._pending("marker"):
            self._arm_marker_check(now, reset=False)  # periodic: keep the verdict meanwhile
        if self._temp_next is not None and now >= self._temp_next and not self._pending("temp"):
            self._temp_next = now + self.TEMP_PERIOD_S
            self._jobs.append(_Job("temp", list(read_mls.TEMP_READS), self._temp_done,
                                   failed=self._temp_failed))

    def _sdo_poll(self, now: float) -> None:
        """At most ONE short SDO operation: the next read (or write) of the first job."""
        self._schedule(now)
        if not self._jobs or not self.link.take_sensor("mls"):
            return
        job = self._jobs[0]
        if job.keys:
            key = job.keys[0]
            v = self._short_read(key)
            if v is None:
                self._jobs.pop(0)
                if job.failed:
                    job.failed(key, now)
                return
            job.vals[key] = v
            job.keys.pop(0)
            if not job.keys:
                job.done(job.vals, now)
                if job.write is None:
                    self._jobs.pop(0)
            return
        self._jobs.pop(0)
        index, sub, value, size = job.write
        try:
            ok, detail = self.link.write_sensor(self.node, index, sub, value, size,
                                                timeout=self.PROBE_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - ForbiddenWrite, or a link with no sensor write
            ok, detail = False, repr(e)
        job.wrote(ok, detail, now)

    # -- marker configuration (read-only) --

    def _arm_marker_check(self, now: float, reset: bool) -> None:
        self._jobs = [j for j in self._jobs if j.purpose != "marker"]
        self._jobs.append(_Job("marker", list(self.marker_expect), self._marker_done,
                               failed=self._marker_failed))
        self._mnext = None
        if reset:
            self.marker_status = "checking"

    def _marker_failed(self, key, now: float) -> None:
        self._mnext = now + self.MARKER_RETRY_S
        new = f"unverified: {key[0]:04X}h:{key[1]:02X} did not answer"
        if new != self.marker_status:
            self.log(f"MLS markers {new}; retrying in {self.MARKER_RETRY_S:.0f} s")
        self.marker_status = new

    def _marker_done(self, vals: dict, now: float) -> None:
        self.marker_checks += 1
        self._mnext = now + self.MARKER_RECHECK_S
        diffs = [
            f"{i:04X}h:{sb:02X} = {vals.get((i, sb))} (want {w})"
            for (i, sb), w in self.marker_expect.items()
            if vals.get((i, sb)) != w
        ]
        new = "ok" if not diffs else "misconfigured: " + "; ".join(diffs)
        if new != self.marker_status:
            if diffs:
                self.log(f"MLS markers {new} - no marker events. Fix with the service stopped: "
                         "python3 -m agv_core.drivers.canbus.read_mls set-markers --go")
            else:
                self.log("MLS markers: sensor configured as the profile expects")
        self.marker_status = new

    # -- event detection (mls-diagnostics-plan M1/M2) --

    def _event_watch(self, r: dict, now: float) -> None:
        """Every TPDO1 frame: queue the cause reads on a new event (see the module doc)."""
        st = r["status"]
        flag, nlcp = bool(st["event_flag"]), int(r["nlcp"])
        if nlcp:
            lvl = int(st["track_level"])
            self.track_level_min = lvl if self.track_level_min is None else min(self.track_level_min, lvl)
        prev_nlcp = nlcp if self._ev_prev_nlcp is None else self._ev_prev_nlcp
        new = False
        if flag and not self._pending("event"):
            if not self._ev_prev_flag:
                new = True  # rising, or already up when the stream (re)started
            elif self._ev_retry_at is not None and now >= self._ev_retry_at:
                new = True  # the last cause read got no answer
            elif self._ev_cleared_at is not None and now - self._ev_cleared_at >= self.CLEAR_MIN_S:
                new = True  # up again after a reset
        if new:
            self._ev_retry_at = self._ev_cleared_at = None
            lcp2 = mls_markers.lcp2(r)
            ctx = {"t_mono": now, "track_before": prev_nlcp > 0, "nlcp": nlcp, "lcp2_mm": lcp2,
                   "track_level": int(st["track_level"])}
            write = None if self.event_clear is None else (*read_mls.EVENT_RESET, self.event_clear, 1)
            self._jobs.append(_Job(
                "event", list(read_mls.EVENT_READS),
                lambda vals, t, ctx=ctx: self._event_done(vals, t, ctx),
                write=write, wrote=self._clear_done, failed=self._event_failed,
            ))
        self._ev_prev_flag, self._ev_prev_nlcp = flag, nlcp

    def _event_failed(self, key, now: float) -> None:
        self.events_unread += 1
        self._ev_retry_at = now + self.EVENT_RETRY_S

    def _event_done(self, vals: dict, now: float, ctx: dict) -> None:
        ev = read_mls.decode_event(*(vals.get(k) for k in read_mls.EVENT_READS))
        if ev["temp"]:
            self.events_temp += 1
            self._temp_next = now  # read the temperature now, not in a minute
        if ev["field"]:
            if ctx["track_before"]:
                self.events_field += 1
                if self.on_event is not None:
                    self.on_event(dict(ev, **ctx))
            else:
                self.events_no_track += 1
        if not ev["field"] and not ev["temp"]:
            self.events_other += 1

    def _clear_done(self, ok: bool, detail: str, now: float) -> None:
        if ok:
            self.clears += 1
            self._ev_cleared_at = now
            return
        self.log(f"MLS event-flag reset 2080h:01 = {self.event_clear} failed ({detail}): "
                 "not clearing again this run, only the first event after this one is seen")
        self.event_clear = None
        self.clear_state = "failed"

    # -- temperature --

    def _temp_done(self, vals: dict, now: float) -> None:
        self.temp = read_mls.decode_temp(*(vals.get(k) for k in read_mls.TEMP_READS))

    def _temp_failed(self, key, now: float) -> None:
        self.temp_unread += 1

    @property
    def markers_ok(self) -> bool:
        return self.marker_status == "ok" and self.mode == "tpdo"

    def marker_status_text(self) -> str:
        """What /amr/line_marker's heartbeat says."""
        if not self.marker_expect:
            return "off"
        if self.mode == "sdo":
            return "no stream (sdo)"
        if self.mode == "off":
            return "no sensor"
        return self.marker_status

    # -- diagnostics (pure; drive_node wraps it in a DiagnosticStatus) --

    def _variant_text(self) -> str:
        if self.variant is None:
            return ""
        return f"{self.variant} {read_mls.VARIANT_NAMES.get(self.variant, '?')}"

    def _period_text(self) -> str:
        if self.tpdo_period_ms is None:
            return ""
        return "0 (on change)" if self.tpdo_period_ms == 0 else str(self.tpdo_period_ms)

    def diagnostic(self, now: float) -> tuple[str, str, list[tuple[str, str]]]:
        a = self.age(now)
        s = self.last
        kv = [
            ("mode", self.mode),
            ("source", s.source if s else ""),
            ("nlcp", f"{s.nlcp} {s.reading['nlcp_label']}" if s else ""),
        ]
        for i in range(3):
            kv.append((f"lcp{i + 1}_mm", str(s.lcp_mm[i]) if s and (i + 1) in s.reading["valid"] else ""))
        st = s.reading["status"] if s else {}
        kv += [
            ("line_good", str(st.get("line_good", ""))),
            ("track_level", str(st.get("track_level", ""))),
            ("polarity", st.get("polarity", "")),
            ("marker", str(s.reading["marker"]["code"]) if s else ""),
            ("age_ms", "" if a is None else f"{a * 1000.0:.0f}"),
            ("samples", str(self.samples)),
            ("tpdo_frames", str(self.tpdo_frames)),
            ("stale_periods", str(self.stale_periods)),
            ("nmt_starts", str(self.nmt_starts)),
            ("restarts", str(self.restarts)),
            ("sdo_misses", str(self.misses)),
            ("variant", self._variant_text()),
            ("variant_mismatches", str(self.variant_mismatches)),
            ("markers", self.marker_status_text()),
            ("marker_checks", str(self.marker_checks)),
            ("events_field", str(self.events_field)),
            ("events_no_track", str(self.events_no_track)),
            ("events_temp", str(self.events_temp)),
            ("events_unread", str(self.events_unread)),
            ("event_clear", self.clear_state if self.event_clear is None else f"on ({self.event_clear})"),
            ("event_clears", str(self.clears)),
            ("track_level_min", "" if self.track_level_min is None else str(self.track_level_min)),
            ("temp_c", "" if not self.temp or self.temp["temp_c"] is None else str(self.temp["temp_c"])),
            ("temp_range_c", "" if not self.temp else f"{self.temp['lo_c']}..{self.temp['hi_c']}"),
            # WP-E8 / WP-P9 (2026-11-16)
            ("tpdo_period_ms", self._period_text()),
            ("tpdo_gaps", str(self.tpdo_gaps)),
            ("max_gap_ms", f"{self.max_gap_ms:.0f}"),
            ("gaps_stationary", str(self.gaps_stationary)),
            ("max_identical_s", f"{self.max_identical_s:.1f}"),
            ("rejected_frames", str(self.rejected_frames)),
            ("reserved_nlcp", str(self.reserved_nlcp)),
            ("reboots", str(self.reboots)),
        ]
        if self.mode == "off":
            return ERROR, "off", kv
        if a is None or a > self.stale_after():
            return ERROR, "stale", kv
        if s.nlcp == 0:
            return WARN, "no track", kv
        return OK, s.reading["nlcp_label"], kv
