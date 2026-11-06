"""Trolley detection and the rear field's reading (station call plan 11.3, 3.3). Pure, clock-fed.

    TrolleyDetect  beams inside a zone -> UNKNOWN / ABSENT / PRESENT, debounced, failing to UNKNOWN
    RearField      /rear/output_paths -> clear / violated / unknown, under the rear case gate

TROLLEY DETECTION IS NOT PERSONNEL PROTECTION. A person in the zone reads as a trolley, and this
cannot tell them apart. It is an interlock on the operator's procedure. The rear safety field does the
protecting, in the scanner OSSD -> FX3 -> STO chain, and nothing in this file is in that chain.

THE CASE GATE. Reading one field index does not prove which monitoring case is active: a towing case
with a reduced field left selected after unhitching would read clear with a person at the hitch. So
clear counts only with the no-trolley case proven active, reported by the driver or (when it reports
nothing) proven in hardware by the safety engineer (rear.case_proven). Case selection never comes
from here: nothing in this file or in trolley_node sets a case or writes to the scanner.

All values are placeholders until the calibration at P8.
"""

from __future__ import annotations

import dataclasses
import math

UNKNOWN, ABSENT, PRESENT = 0, 1, 2  # TrolleyState.state (test_wire_contract pins them through wire)
FIELD_UNKNOWN, FIELD_CLEAR, FIELD_VIOLATED = 0, 1, 2  # TrolleyState.rear_field
CASE_UNKNOWN, CASE_NO_TROLLEY, CASE_OTHER = 0, 1, 2  # TrolleyState.rear_case


@dataclasses.dataclass(frozen=True)
class Params:
    roi_x_min_m: float
    roi_x_max_m: float
    roi_half_width_m: float
    present_points: int
    absent_points: int
    present_s: float
    absent_s: float
    stale_s: float
    max_invalid_ratio: float

    @classmethod
    def from_profile(cls, c) -> Params:
        return cls(
            c.REAR_ROI_X_MIN_M,
            c.REAR_ROI_X_MAX_M,
            c.REAR_ROI_HALF_WIDTH_M,
            c.REAR_PRESENT_POINTS,
            c.REAR_ABSENT_POINTS,
            c.REAR_PRESENT_S,
            c.REAR_ABSENT_S,
            c.REAR_STALE_S,
            c.REAR_MAX_INVALID_RATIO,
        )


class TrolleyDetect:
    def __init__(self, params: Params) -> None:
        self.p = params
        self.state = UNKNOWN
        self.detail = "no scan yet"
        self.points = 0
        self._t: float | None = None  # the last usable scan
        self._raw: int | None = None  # the raw reading being debounced
        self._raw_since = 0.0
        self._counter = None  # the scan identity, for frozen content
        self._counter_since = 0.0
        self._geom_key = None
        self._zone: list[tuple[int, float, float]] = []

    def _fail(self, why: str) -> None:
        self.state, self.detail = UNKNOWN, why
        self._raw = None

    def _beams(self, angle_min: float, angle_inc: float, n: int):
        """The beams whose direction crosses the zone, with their (cos, sin). Cached: the angles of a
        scan do not change, and the beam loop runs at the scan rate on the N97."""
        key = (angle_min, angle_inc, n)
        if key != self._geom_key:
            p = self.p
            zone = []
            for k in range(n):
                a = angle_min + k * angle_inc
                c, s = math.cos(a), math.sin(a)
                if self._crosses(c, s, p):
                    zone.append((k, c, s))
            self._geom_key, self._zone = key, zone
        return self._zone

    @staticmethod
    def _crosses(c: float, s: float, p: Params) -> bool:
        """Slab test: does the ray from the scanner cross the rectangle?"""
        lo, hi = 0.0, math.inf
        for o_min, o_max, d in (
            (p.roi_x_min_m, p.roi_x_max_m, c),
            (-p.roi_half_width_m, p.roi_half_width_m, s),
        ):
            if abs(d) < 1e-9:
                if not o_min <= 0.0 <= o_max:
                    return False
                continue
            a, b = sorted((o_min / d, o_max / d))
            lo, hi = max(lo, a), min(hi, b)
        return lo <= hi

    def scan(self, now, ranges, angle_min, angle_inc, range_min, range_max, counter=None) -> None:
        """One /rear/scan. `counter` is anything that changes with each real scan (see trolley_node):
        the same value beyond stale_s is a scanner or driver publishing frozen content."""
        if not ranges or not angle_inc or angle_inc <= 0 or not math.isfinite(angle_min):
            self._fail("malformed scan")
            return
        if counter is not None:
            if counter != self._counter:
                self._counter, self._counter_since = counter, now
            elif now - self._counter_since > self.p.stale_s:
                self._fail("the scan content is frozen")
                return
        self._t = now
        zone = self._beams(angle_min, angle_inc, len(ranges))
        if not zone:
            self._fail("no beam of this scan crosses the trolley zone")
            return
        p = self.p
        count = invalid = 0
        for k, c, s in zone:
            r = ranges[k]
            # NaN or below the minimum: the scanner could not measure. Beyond the maximum or inf is a
            # valid "nothing there", so an open floor does not read as a blind scanner.
            if math.isnan(r) or r < range_min:
                invalid += 1
            elif (
                r <= range_max
                and p.roi_x_min_m <= r * c <= p.roi_x_max_m
                and abs(r * s) <= p.roi_half_width_m
            ):
                count += 1
        self.points = count
        if invalid > p.max_invalid_ratio * len(zone):
            self._fail(f"{invalid} of {len(zone)} beams in the zone invalid")
            return
        raw = PRESENT if count >= p.present_points else ABSENT if count <= p.absent_points else None
        if raw is None or raw != self._raw:
            self._raw, self._raw_since = raw, now  # between: the state stays, the timer starts over
        if raw is None or raw == self.state:
            if self.state != UNKNOWN:
                self.detail = ""
            return
        if now - self._raw_since >= (p.present_s if raw == PRESENT else p.absent_s):
            self.state, self.detail = raw, ""

    def tick(self, now) -> int:
        """The state now: a scan that stopped arriving is UNKNOWN, and leaving it needs a full debounce."""
        if self._t is None or now - self._t > self.p.stale_s:
            self._fail("no scan" if self._t is None else "the rear scan is stale")
        return self.state


def case_of(active_case, no_trolley_case: int) -> int:
    """The driver's OutputPaths.active_monitoring_case against the profile's no-trolley case. 0 is the
    driver's value for no case data; -1 in the profile means it is not set."""
    if active_case is None or not active_case or no_trolley_case < 0:
        return CASE_UNKNOWN
    return CASE_NO_TROLLEY if int(active_case) == no_trolley_case else CASE_OTHER


def gated(clear: bool | None, case: int, proven: bool) -> bool | None:
    """The rear case gate (plan 3.3): clear stays clear only for the no-trolley case, or for an unknown
    case the safety engineer has proven in hardware. CASE_OTHER is never clear, whatever `proven`
    says. Violated stays violated: a stop is never gated away."""
    if clear is not True:
        return clear
    if case == CASE_NO_TROLLEY or (case == CASE_UNKNOWN and proven):
        return True
    return None


class RearField:
    """The latest /rear/output_paths. A malformed array is no evidence: the old reading ages out."""

    def __init__(self, fresh_s: float, index: int, no_trolley_case: int, proven: bool) -> None:
        self.fresh_s, self.index = float(fresh_s), int(index)
        self.no_trolley_case, self.proven = int(no_trolley_case), bool(proven)
        self._clear: bool | None = None
        self._active = None
        self._t: float | None = None

    def update(self, now, status, active_case=None) -> None:
        if status is None or len(status) <= self.index:
            return
        self._clear, self._active, self._t = bool(status[self.index]), active_case, now

    def read(self, now) -> tuple[int, int]:
        """(rear_field, rear_case) as TrolleyState wants them."""
        if self._t is None or now - self._t > self.fresh_s:
            return FIELD_UNKNOWN, CASE_UNKNOWN
        case = case_of(self._active, self.no_trolley_case)
        clear = gated(self._clear, case, self.proven)
        return ({True: FIELD_CLEAR, False: FIELD_VIOLATED}.get(clear, FIELD_UNKNOWN), case)
