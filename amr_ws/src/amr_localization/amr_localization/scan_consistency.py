"""Scan-versus-map consistency for the localisation monitor (pure numpy, no ROS).

match: fraction of returned beams whose endpoint lies within `tol` of a mapped
obstacle. Informational: clutter lowers it, a speckled map raises it.

long: fraction of beams (among those the map expects to hit a wall within
range) that measure farther than that wall by more than `tol` AND end in
mapped free space. This is the loss trigger. A beam that passes a mapped wall
and lands on another mapped obstacle is the map being seen THROUGH - wire mesh,
railings, glass (the survey cage is mesh, 2026-09-17) - not a pose error; a
wrong pose puts endpoints in free space wholesale. A beam that ends in unknown
or off the map, or has no return, proves nothing either way.
"""

from __future__ import annotations

import numpy as np
from amr_maps.grid import Grid
from amr_maps.raycast import ScanGeometry, cast

OCCUPIED = 65


def occupied_near(grid: Grid, tol_m: float) -> np.ndarray:
    """Occupied cells dilated by tol_m (square, wrap-free)."""
    occ = grid.data >= OCCUPIED
    cells = max(1, int(round(tol_m / grid.meta.resolution)))
    p = np.pad(occ, cells)
    near = np.zeros_like(occ)
    h, w = occ.shape
    for dr in range(-cells, cells + 1):
        for dc in range(-cells, cells + 1):
            near |= p[cells + dr : cells + dr + h, cells + dc : cells + dc + w]
    return near


def compare(
    grid: Grid,
    occ_near: np.ndarray,
    lx: float,
    ly: float,
    yaw: float,
    ranges: np.ndarray,
    geom: ScanGeometry,
    tol_m: float,
) -> tuple[float, float]:
    """(match_frac, long_frac) for a scan taken at laser pose (lx, ly, yaw) in the map frame."""
    ranges = np.asarray(ranges, dtype=np.float64)
    n = len(ranges)
    expected = cast(grid, lx, ly, yaw, geom)  # inf where the map has nothing within range
    measured = np.where(np.isfinite(ranges), ranges, np.inf)

    valid = np.isfinite(ranges) & (ranges >= geom.range_min) & (ranges < geom.range_max)
    a = geom.angles + yaw
    finite = np.where(valid, ranges, 0.0)  # inf * cos would raise; invalid beams are masked anyway
    ex, ey = lx + finite * np.cos(a), ly + finite * np.sin(a)
    m = grid.meta
    cols = np.floor((ex - m.origin_x) / m.resolution)
    rows = np.floor((ey - m.origin_y) / m.resolution)
    inside = valid & (cols >= 0) & (cols < grid.width) & (rows >= 0) & (rows < grid.height)
    ci, ri = cols[inside].astype(int), rows[inside].astype(int)
    near_obstacle = np.zeros(n, dtype=bool)
    near_obstacle[inside] = occ_near[ri, ci]
    in_free = np.zeros(n, dtype=bool)
    in_free[inside] = (grid.data[ri, ci] >= 0) & ~near_obstacle[inside]

    wall_expected = np.isfinite(expected)
    long = wall_expected & (measured > expected + tol_m) & in_free
    long_frac = float(long.sum()) / max(1, int(wall_expected.sum()))
    match_frac = float(near_obstacle[valid].mean()) if valid.sum() >= 20 else 0.0
    return match_frac, long_frac
