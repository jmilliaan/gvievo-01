"""Raycasting a 2-D laser against an occupancy grid. Pure numpy.

All beams are marched together: sample points at `step` spacing along every
ray, look up the grid, take the first occupied sample per beam. Accuracy is
±step/2 in range, which is why step defaults to half a cell. Cost is
beams x (max_range / step) lookups per scan; at 550 beams, 20 m and 0.025 m
that is 440 k lookups, a few ms in numpy.

CPU (2026-11-16, cpu-load plan §4a c): the march goes in chunks of CHUNK samples and a
beam leaves it once it has hit; the per-beam cos/sin of one (geometry, yaw) are cached
(beam_trig) and shared with scan_consistency's own lookups. Every sample point is the
same float expression as in the whole-array march, so the ranges are bit-identical to
it (test_raycast's brute-force oracle).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from amr_maps.grid import OCCUPIED, Grid


@dataclass(frozen=True)
class ScanGeometry:
    angle_min: float  # rad, in the laser frame
    angle_max: float
    beams: int
    range_min: float
    range_max: float

    @property
    def angle_increment(self) -> float:
        return (self.angle_max - self.angle_min) / (self.beams - 1)

    @property
    def angles(self) -> np.ndarray:
        return np.linspace(self.angle_min, self.angle_max, self.beams)


# nanoScan3: 275 deg, from -47.5 deg (behind-right) to +227.5 deg, i.e. the
# 85 deg dead sector faces backwards. Expressed symmetric about the forward
# axis: -137.5 .. +137.5 deg. The wire count is 1652 at 1/6 deg; the sim
# default is coarser and configurable (spec §8: "configurable scan geometry").
# On this vehicle a wall behind the mount limits the usable window to about
# +/-95 deg (operator, 2026-09-16): that is what the sim and the driver use.
NANOSCAN3_FOV = math.radians(275.0)
MOUNTED_FOV = math.radians(190.0)


def nanoscan3(beams: int = 551, range_max: float = 30.0) -> ScanGeometry:
    """The device's full geometry."""
    return ScanGeometry(-NANOSCAN3_FOV / 2, NANOSCAN3_FOV / 2, beams, 0.05, range_max)


def mounted(beams: int = 381, range_max: float = 30.0) -> ScanGeometry:
    """The usable window on this vehicle: 190 deg at 0.5 deg."""
    return ScanGeometry(-MOUNTED_FOV / 2, MOUNTED_FOV / 2, beams, 0.05, range_max)


CHUNK = 32  # samples per march step (0.8 m at the default 0.025 m step)


@lru_cache(maxsize=8)
def beam_trig(geom: ScanGeometry, yaw: float) -> tuple[np.ndarray, np.ndarray]:
    """(cos, sin) of every beam for a laser at `yaw`: np.cos/np.sin of `yaw + geom.angles`,
    once per (geometry, yaw). Read-only, because callers share them."""
    angles = yaw + geom.angles  # [B]
    c, s = np.cos(angles), np.sin(angles)
    c.setflags(write=False)
    s.setflags(write=False)
    return c, s


def cast(
    grid: Grid, x: float, y: float, yaw: float, geom: ScanGeometry, step: float | None = None
) -> np.ndarray:
    """Ranges (m) for a laser at world pose (x, y, yaw). inf where nothing is hit."""
    step = step or grid.meta.resolution / 2.0
    n_samples = int(math.ceil(geom.range_max / step)) + 1
    dists = np.arange(n_samples) * step  # [S]
    cos_a, sin_a = beam_trig(geom, float(yaw))
    res, ox, oy = grid.meta.resolution, grid.meta.origin_x, grid.meta.origin_y
    first = np.full(geom.beams, -1, dtype=np.int64)  # first occupied sample per beam; -1 none yet
    active = np.arange(geom.beams)
    for s0 in range(0, n_samples, CHUNK):
        if active.size == 0:
            break  # every beam has hit
        d = dists[s0:s0 + CHUNK]
        px = x + np.outer(cos_a[active], d)  # [b, chunk]
        py = y + np.outer(sin_a[active], d)
        cols = np.floor((px - ox) / res).astype(np.int64)
        rows = np.floor((py - oy) / res).astype(np.int64)
        inside = (cols >= 0) & (cols < grid.width) & (rows >= 0) & (rows < grid.height)
        occ = np.zeros(px.shape, dtype=bool)
        # Leaving the grid counts as a hit at the boundary? No: outside is unknown,
        # the beam just reports no return (inf), like a real scanner into open air.
        occ[inside] = grid.data[rows[inside], cols[inside]] >= OCCUPIED
        hit = occ.any(axis=1)
        first[active[hit]] = s0 + occ[hit].argmax(axis=1)
        active = active[~hit]  # a beam that hit leaves the march
    hit = first >= 0
    ranges = dists[np.where(hit, first, n_samples - 1)].astype(np.float64)
    ranges[~hit] = np.inf
    ranges[ranges < geom.range_min] = geom.range_min
    return ranges
