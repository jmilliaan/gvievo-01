"""Logical route position and speed zones. Owned exclusively by the CAN thread.

RFID values are not location IDs: the expected stage identifies a station.
No clocks, I/O or configuration imports; inputs are validated profile records
and distinct tag encounters supplied by the caller.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Station:
    id: str
    tag: str
    direction: str
    high_speed_to_next: bool


class Route:
    def __init__(self, stations: Sequence[Mapping], speed_rules: Sequence[Mapping]):
        self.stations = tuple(Station(**row) for row in stations)
        self.speed_rules = tuple(dict(row) for row in speed_rules)
        self.index = 0
        self.parked = True
        self.direction = self.stations[0].direction
        self.high = False
        self.laps = 0

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
        if self.parked:
            self.direction = self.next.direction
            self.parked = False
        self.clear_speed()

    def encounter(self, tag: str) -> Station | None:
        """Process one new encounter, returning a station only on arrival."""
        if self.parked:
            return None
        if tag == self.next.tag and self.direction == self.next.direction:
            self.index = (self.index + 1) % len(self.stations)
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
        elif any(r['entry_tag'] == tag for r in rules):
            self.high = True
        return None

    def snapshot(self) -> dict:
        return {'station': self.current.id, 'next_station': self.next.id,
                'travel_direction': self.direction, 'parked': self.parked,
                'high_speed': self.high, 'laps': self.laps}
