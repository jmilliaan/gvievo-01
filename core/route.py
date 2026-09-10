"""Logical route position and speed zones. Owned exclusively by the CAN thread.

RFID values are not location IDs: the expected stage identifies a station.
No clocks, I/O or configuration imports; inputs are validated profile records
and distinct tag encounters supplied by the caller.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence


class RouteError(RuntimeError):
    """Position confidence lost; a new run must not guess the route stage."""


@dataclass(frozen=True)
class Station:
    id: str
    tag: str
    direction: str
    high_speed_to_next: bool


class Route:
    def __init__(self, stations: Sequence[Mapping], speed_rules: Sequence[Mapping],
                 guard: Mapping | None = None):
        self.stations = tuple(Station(**row) for row in stations)
        self.speed_rules = tuple(dict(row) for row in speed_rules)
        self.index = 0
        self.parked = True
        self.direction = self.stations[0].direction
        self.high = False
        self.laps = 0
        self.guard = guard or {'enabled': False}
        self.distance_m = 0.0
        self.zone_distance_m = 0.0
        self.zone_active = False
        self.zone_expired = False
        self.guard_error = None
        self.notice = None
        self.initial_assumption = True

    @property
    def guarded(self) -> bool:
        return self.guard['enabled']

    def invalidate(self, reason: str) -> None:
        self.clear_speed()
        self.guard_error = self.guard_error or reason

    def advance(self, distance_m: float) -> str | None:
        """Integrate externally estimated travel, never claim localization."""
        if self.parked or self.guard_error:
            return None
        self.distance_m += max(0.0, distance_m)
        if self.zone_active:
            self.zone_distance_m += max(0.0, distance_m)
        if not self.guarded:
            return None
        leg = next(r for r in self.guard['legs'] if r['from_station'] == self.current.id)
        if self.distance_m > leg['max_m']:
            reason = f"route distance exceeded; expected station {self.next.id}"
            self.invalidate(reason)
            raise RouteError(reason)
        if (self.zone_active and not self.zone_expired
                and self.zone_distance_m >= self.guard['high_speed_max_m'][self.direction]):
            self.zone_expired = True
            self.clear_speed()
            return f"high-speed distance exceeded ({self.direction}); normal speed until exit tag"
        return None

    @property
    def current(self) -> Station:
        return self.stations[self.index]

    @property
    def next(self) -> Station:
        return self.stations[(self.index + 1) % len(self.stations)]

    def clear_speed(self) -> None:
        self.high = False

    def depart(self) -> None:
        """Commit departure only when Start's delay has completed."""
        if self.guard_error:
            raise RouteError(self.guard_error + "; return to point 2 and restart controller")
        if self.parked:
            self.direction = self.next.direction
            self.parked = False
            self.distance_m = self.zone_distance_m = 0.0
            self.zone_active = self.zone_expired = False
        self.clear_speed()

    def encounter(self, tag: str) -> Station | None:
        """Process one new encounter, returning a station only on arrival."""
        self.notice = None
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
            self.clear_speed()
            return self.current
        if not self.current.high_speed_to_next:
            self.clear_speed()
            return None
        # Reset wins should more than one rule match; validation normally
        # rejects that ambiguity within a direction.
        rules = [r for r in self.speed_rules if r['direction'] == self.direction]
        if any(r['exit_tag'] == tag for r in rules):
            self.high = False
            self.zone_active = self.zone_expired = False
            self.zone_distance_m = 0.0
        elif any(r['entry_tag'] == tag for r in rules):
            if not self.zone_active:
                self.zone_active = True
                self.zone_distance_m = 0.0
            self.high = not self.zone_expired
        return None

    def snapshot(self) -> dict:
        return {'station': self.current.id, 'next_station': self.next.id,
                'travel_direction': self.direction, 'parked': self.parked,
                'high_speed': self.high, 'laps': self.laps,
                'guard_enabled': self.guarded, 'guard_error': self.guard_error,
                'initial_assumption': self.initial_assumption,
                'distance_estimate_m': self.distance_m,
                'high_distance_estimate_m': self.zone_distance_m}
