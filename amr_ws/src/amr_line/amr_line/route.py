"""Logical route position. Owned exclusively by the line job.

RFID values are not location IDs: the expected stage identifies a station.
No clocks, I/O or configuration imports; inputs are validated profile records
and distinct tag encounters supplied by the caller.

Speed zones were removed 2026-10-02: tracked AUTO has one cruise speed (the
profile's auto_rpm) plus the branch_latch slow zones, which branch.py owns.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class RouteError(RuntimeError):
    """Position confidence lost; a new run must not guess the route stage."""


@dataclass(frozen=True)
class Station:
    id: str
    tag: str
    direction: str


class Route:
    def __init__(self, stations: Sequence[Mapping], guard: Mapping | None = None):
        self.stations = tuple(Station(**row) for row in stations)
        self.index = 0
        # No stations: a mission without a route. Plain line-following.
        self.enabled = bool(self.stations)
        self.parked = self.enabled
        self.direction = self.stations[0].direction if self.enabled else None
        self.laps = 0
        self.guard = guard or {'enabled': False}
        self.distance_m = 0.0
        self.guard_error = None
        self.notice = None
        self.initial_assumption = self.enabled

    @property
    def guarded(self) -> bool:
        return self.guard['enabled']

    def invalidate(self, reason: str) -> None:
        self.guard_error = self.guard_error or reason

    def advance(self, distance_m: float) -> str | None:
        """Integrate externally estimated travel, never claim localization."""
        if self.parked or self.guard_error:
            return None
        self.distance_m += max(0.0, distance_m)
        if not self.guarded:
            return None
        leg = next(r for r in self.guard['legs'] if r['from_station'] == self.current.id)
        if self.distance_m > leg['max_m']:
            reason = f"route distance exceeded; expected station {self.next.id}"
            self.invalidate(reason)
            raise RouteError(reason)
        return None

    @property
    def current(self) -> Station | None:
        return self.stations[self.index] if self.enabled else None

    @property
    def next(self) -> Station | None:
        if not self.enabled:
            return None
        return self.stations[(self.index + 1) % len(self.stations)]

    def depart(self) -> None:
        """Commit departure only when Start's delay has completed."""
        if self.guard_error:
            raise RouteError(self.guard_error + "; return to point 2 and restart controller")
        if self.parked:
            self.direction = self.next.direction
            self.parked = False
            self.distance_m = 0.0

    def encounter(self, tag: str) -> Station | None:
        """Process one new encounter, returning a station only on arrival."""
        self.notice = None
        if not self.enabled:
            return None
        if self.parked or self.guard_error:
            return None
        # Direction is route bookkeeping, not independent physical evidence.
        if tag == self.next.tag:
            if self.guarded:
                leg = next(r for r in self.guard['legs'] if r['from_station'] == self.current.id)
                if self.distance_m < leg['min_m']:
                    self.notice = f"early tag {tag} rejected; expected station {self.next.id} farther along leg"
                    return None
            self.index = (self.index + 1) % len(self.stations)
            self.initial_assumption = False
            self.laps += int(self.index == 0)
            self.parked = True
            return self.current
        return None

    def snapshot(self) -> dict:
        if not self.enabled:
            return {'enabled': False, 'station': None, 'next_station': None,
                    'travel_direction': None, 'parked': False,
                    'laps': 0,
                    'guard_enabled': False, 'guard_error': self.guard_error,
                    'initial_assumption': False,
                    'distance_estimate_m': self.distance_m}
        return {'enabled': True, 'station': self.current.id, 'next_station': self.next.id,
                'travel_direction': self.direction, 'parked': self.parked,
                'laps': self.laps,
                'guard_enabled': self.guarded, 'guard_error': self.guard_error,
                'initial_assumption': self.initial_assumption,
                'distance_estimate_m': self.distance_m}
