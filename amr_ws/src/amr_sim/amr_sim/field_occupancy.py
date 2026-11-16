"""/output_paths from the scan and the field rectangles (S-fake-output-paths-from-field-geometry).

SIM ONLY. This emulates the scanner's own safety decision so the sim can exercise the real mux
and the real follower/executor: protective stop, the warning-2 deceleration stop, the warning-1
x0.5 and resume after a clear field. It is NOT a field monitor and must never be reused as one
on a vehicle: there the nanoScan3's certified evaluation is the only source (fake_output_paths_node
refuses ROS_DOMAIN_ID 10, test_launch_layers holds it out of every real:=true launch).

The rectangles, paths and polarity come from amr_bringup/config/scanner_fields.yaml (the doc
scanner_fields.load() validated at launch). Pure: no rclpy (test_field_occupancy.py).
"""

from __future__ import annotations

import math

ROLES = ("protective", "warning_1", "warning_2")
N_PATHS = 20  # the driver's /output_paths arrays
# Scripted overrides (H-P3-2): the stream the node publishes instead of the computed one.
AUTO, CLEAR, DROP, INVALID = "auto", "clear", "drop", "invalid"
VIOLATE = "violate"  # + a role: that field occupied (and the fields around it, they nest)


def points(ranges, angle_min: float, angle_increment: float, range_min: float, range_max: float) -> list:
    """LaserScan -> (x, y) in the scanner frame (x forward, y left); invalid returns dropped."""
    out = []
    for i, r in enumerate(ranges):
        if not (math.isfinite(r) and range_min <= r <= range_max):
            continue
        a = angle_min + i * angle_increment
        out.append((r * math.cos(a), r * math.sin(a)))
    return out


def inside(p, rect: dict) -> bool:
    return rect["x_min"] <= p[0] <= rect["x_max"] and rect["y_min"] <= p[1] <= rect["y_max"]


def occupied_now(pts: list, doc: dict, min_points: int = 2) -> dict:
    """role -> occupied in this scan: at least `min_points` returns inside its rectangle (one stray
    beam of 0.01 m range noise on a rectangle edge is not an obstacle)."""
    f = doc["fields"]
    return {role: sum(1 for p in pts if inside(p, f[role]["rect"])) >= min_points for role in ROLES}


class Debounce:
    """A field changes state only after `samples` scans in a row agree (N-sample debounce)."""

    def __init__(self, samples: int = 2) -> None:
        self.samples = max(1, int(samples))
        self.state = {r: False for r in ROLES}
        self._run = {r: 0 for r in ROLES}

    def update(self, now_occ: dict) -> dict:
        for r in ROLES:
            if now_occ[r] == self.state[r]:
                self._run[r] = 0
                continue
            self._run[r] += 1
            if self._run[r] >= self.samples:
                self.state[r], self._run[r] = now_occ[r], 0
        return dict(self.state)


def override_occupancy(override: str) -> dict | None:
    """The occupancy a scripted override forces; None = AUTO (the computed one)."""
    if override == CLEAR:
        return {r: False for r in ROLES}
    if override.startswith(VIOLATE + ":"):
        role = override.split(":", 1)[1]
        if role not in ROLES:
            raise ValueError(f"violate:{role}: expected one of {ROLES}")
        # protective inside warning_2 inside warning_1: an object in an inner field is in the outer ones
        nest = {"protective": ROLES, "warning_2": ("warning_2", "warning_1"), "warning_1": ("warning_1",)}
        return {r: r in nest[role] for r in ROLES}
    return None


def output_paths(occ: dict, doc: dict, valid: bool = True) -> tuple[list, list]:
    """(status, is_valid), N_PATHS each. A field's path reads its yaml `active` level while
    occupied and the other level while clear; unused paths read clear."""
    f = doc["fields"]
    active = bool(f["protective"]["active"])  # one polarity for all paths (scanner_fields.validate)
    status = [not active] * N_PATHS
    for role in ROLES:
        status[int(f[role]["path"])] = active if occ[role] else not active
    return status, [bool(valid)] * N_PATHS


def check_override(override: str) -> str:
    """The /sim/output_paths/set argument, validated. Returns it, or raises ValueError."""
    if override in (AUTO, CLEAR, DROP, INVALID):
        return override
    override_occupancy(override)  # raises on a bad violate:<role>
    if not override.startswith(VIOLATE + ":"):
        raise ValueError(f"{override!r}: expected auto|clear|drop|invalid|violate:<role>")
    return override
