"""Footprint polygon, and the cells it sweeps along a line or through a turn.

Reads amr_description/config/footprint.yaml (the single source of truth the
costmap also gets). Sweeps are unions of the rasterised polygon at poses every
0.05 m along a straight, or at headings a fraction of a cell apart through the
signed angle of a rotation - the COMPLETE swept area, not the centreline (spec
§5.4). A rotation of unknown angle is the disc of the polygon's reach. The
margin is applied as a dilation of the result.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
import yaml
from amr_maps.grid import Grid, require_axis_aligned


@dataclass(frozen=True)
class Footprint:
    polygon: tuple[tuple[float, float], ...]  # base_footprint frame, metres
    margin_m: float

    @property
    def reach_m(self) -> float:
        """Farthest vertex from the pivot: the rotation sweep radius."""
        return max(math.hypot(x, y) for x, y in self.polygon)

    def as_costmap_string(self) -> str:
        """Nav2 `footprint` parameter format."""
        return "[" + ", ".join(f"[{x:.3f}, {y:.3f}]" for x, y in self.polygon) + "]"


def load(path: str) -> Footprint:
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    poly = tuple((float(p[0]), float(p[1])) for p in doc["polygon"])
    if len(poly) < 3:
        raise ValueError("footprint polygon needs at least 3 vertices")
    return Footprint(poly, float(doc.get("margin_m", 0.0)))


def default_path() -> str:
    from ament_index_python.packages import get_package_share_directory  # noqa: PLC0415

    return os.path.join(get_package_share_directory("amr_description"), "config", "footprint.yaml")


def _polygon_world(fp: Footprint, x: float, y: float, yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    pts = np.asarray(fp.polygon, dtype=np.float64)
    return np.column_stack((x + c * pts[:, 0] - s * pts[:, 1], y + s * pts[:, 0] + c * pts[:, 1]))


def rasterize_polygon(grid: Grid, poly: np.ndarray, mask: np.ndarray) -> None:
    """OR the cells whose centres lie inside `poly` (world coords) into `mask`."""
    res, ox, oy = grid.meta.resolution, grid.meta.origin_x, grid.meta.origin_y
    c0 = max(0, int(math.floor((poly[:, 0].min() - ox) / res)))
    c1 = min(grid.width - 1, int(math.floor((poly[:, 0].max() - ox) / res)))
    r0 = max(0, int(math.floor((poly[:, 1].min() - oy) / res)))
    r1 = min(grid.height - 1, int(math.floor((poly[:, 1].max() - oy) / res)))
    if c1 < c0 or r1 < r0:
        return
    cols = np.arange(c0, c1 + 1)
    rows = np.arange(r0, r1 + 1)
    px = ox + (cols + 0.5) * res
    py = oy + (rows + 0.5) * res
    X, Y = np.meshgrid(px, py)  # [rows, cols]
    inside = np.zeros(X.shape, dtype=bool)
    n = len(poly)
    for i in range(n):  # even-odd crossing test, vectorised over the bbox
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        crosses = (y1 > Y) != (y2 > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (X < xint)
    mask[r0 : r1 + 1, c0 : c1 + 1] |= inside


def dilate(mask: np.ndarray, cells: int) -> np.ndarray:
    """Disc dilation bounded by the grid: nothing wraps from one edge onto the opposite one."""
    if cells <= 0:
        return mask
    rows, cols = mask.shape
    padded = np.zeros((rows + 2 * cells, cols + 2 * cells), dtype=bool)
    for dr in range(-cells, cells + 1):
        for dc in range(-cells, cells + 1):
            if dr * dr + dc * dc <= cells * cells:
                padded[cells + dr : cells + dr + rows, cells + dc : cells + dc + cols] |= mask
    return padded[cells : cells + rows, cells : cells + cols]


def margin_cells(fp: Footprint, res: float) -> int:
    """Margin in whole cells, rounded UP: a margin smaller than a cell still dilates by one."""
    if fp.margin_m <= 0.0:
        return 0
    return max(1, int(math.ceil(fp.margin_m / res - 1e-9)))


def _map_extent(grid: Grid) -> tuple[float, float, float, float]:
    m = grid.meta
    return (
        m.origin_x,
        m.origin_y,
        m.origin_x + grid.width * m.resolution,
        m.origin_y + grid.height * m.resolution,
    )


def _pad(grid: Grid, fp: Footprint) -> float:
    return max(fp.margin_m, margin_cells(fp, grid.meta.resolution) * grid.meta.resolution)


def line_outside(
    grid: Grid, fp: Footprint, start: tuple[float, float, float], end: tuple[float, float, float]
) -> bool:
    """True if any part of the translated footprint plus margin leaves the map rectangle.
    The sweep lies in the convex hull of the polygon at both ends, so checking those vertices
    (grown by the margin) against the rectangle is exact for the hull and conservative."""
    x0, y0, x1, y1 = _map_extent(grid)
    pad = _pad(grid, fp) - 1e-9
    pts = np.vstack((_polygon_world(fp, *start), _polygon_world(fp, end[0], end[1], start[2])))
    return bool(
        (pts[:, 0].min() - pad < x0)
        or (pts[:, 0].max() + pad > x1)
        or (pts[:, 1].min() - pad < y0)
        or (pts[:, 1].max() + pad > y1)
    )


def turn_headings(fp: Footprint, res: float, yaw: float, signed_angle: float) -> list[float]:
    """Headings from `yaw` through `yaw + signed_angle`, close enough that the farthest
    vertex moves at most half a cell between neighbours (so the union has no gaps)."""
    step = res / (2.0 * max(fp.reach_m, res))
    n = max(1, int(math.ceil(abs(signed_angle) / step)))
    return [yaw + signed_angle * k / n for k in range(n + 1)]


def rotation_outside(
    grid: Grid,
    fp: Footprint,
    pivot: tuple[float, float],
    yaw: float | None = None,
    signed_angle: float | None = None,
) -> bool:
    """True if the rotation sweep plus margin leaves the map rectangle. With a heading and a
    signed angle this is the exact sweep; without, the disc of the reach (any turn)."""
    x0, y0, x1, y1 = _map_extent(grid)
    pad = _pad(grid, fp) - 1e-9
    if yaw is None or signed_angle is None:
        r = fp.reach_m + pad
        return bool(pivot[0] - r < x0 or pivot[0] + r > x1 or pivot[1] - r < y0 or pivot[1] + r > y1)
    pts = np.vstack(
        [
            _polygon_world(fp, pivot[0], pivot[1], h)
            for h in turn_headings(fp, grid.meta.resolution, yaw, signed_angle)
        ]
    )
    return bool(
        (pts[:, 0].min() - pad < x0)
        or (pts[:, 0].max() + pad > x1)
        or (pts[:, 1].min() - pad < y0)
        or (pts[:, 1].max() + pad > y1)
    )


def swept_poses(grid: Grid, fp: Footprint, poses) -> np.ndarray:
    """Cells covered by the footprint at each of `poses` (x, y, yaw), grown by the margin.
    Callers sample the poses no farther apart than a cell so the union has no gaps."""
    require_axis_aligned(grid.meta)
    mask = np.zeros(grid.data.shape, dtype=bool)
    for x, y, yaw in poses:
        rasterize_polygon(grid, _polygon_world(fp, x, y, yaw), mask)
    return dilate(mask, margin_cells(fp, grid.meta.resolution))


def swept_line(
    grid: Grid, fp: Footprint, start: tuple[float, float, float], end: tuple[float, float, float]
) -> np.ndarray:
    """Cells covered by the footprint translated from `start` to `end` (same heading)."""
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    n = max(1, int(math.ceil(length / grid.meta.resolution)))
    poses = [
        (start[0] + k / n * (end[0] - start[0]), start[1] + k / n * (end[1] - start[1]), start[2])
        for k in range(n + 1)
    ]
    return swept_poses(grid, fp, poses)


def arc_poses(
    centre: tuple[float, float],
    radius: float,
    yaw0: float,
    signed_angle: float,
    spacing: float,
    from_len: float = 0.0,
    to_len: float | None = None,
) -> list[tuple[float, float, float]]:
    """Poses along an arc (heading tangent) every `spacing` metres of arc length, between
    `from_len` and `to_len` (default: the whole arc). Same construction as compiler.arc_pose."""
    sign = 1.0 if signed_angle >= 0 else -1.0
    total = radius * abs(signed_angle)
    a0 = max(0.0, min(total, from_len))
    a1 = total if to_len is None else max(a0, min(total, to_len))
    n = max(1, int(math.ceil((a1 - a0) / spacing)))
    out = []
    for k in range(n + 1):
        phi = (a0 + (a1 - a0) * k / n) / radius
        yaw = yaw0 + sign * phi
        out.append(
            (centre[0] + sign * radius * math.sin(yaw), centre[1] - sign * radius * math.cos(yaw), yaw)
        )
    return out


def swept_arc(
    grid: Grid,
    fp: Footprint,
    centre: tuple[float, float],
    radius: float,
    yaw0: float,
    signed_angle: float,
    from_len: float = 0.0,
    to_len: float | None = None,
) -> np.ndarray:
    """Cells covered by the footprint driven along an arc (or the part of it between
    `from_len` and `to_len` metres of arc length)."""
    return swept_poses(
        grid, fp, arc_poses(centre, radius, yaw0, signed_angle, grid.meta.resolution, from_len, to_len)
    )


def arc_outside(
    grid: Grid, fp: Footprint, centre: tuple[float, float], radius: float, yaw0: float, signed_angle: float
) -> bool:
    """True if the footprint plus margin leaves the map anywhere along the arc (poses 5 deg apart:
    conservative through the padded vertices, like line_outside)."""
    x0, y0, x1, y1 = _map_extent(grid)
    pad = _pad(grid, fp) - 1e-9
    poses = arc_poses(centre, radius, yaw0, signed_angle, radius * math.radians(5.0))
    pts = np.vstack([_polygon_world(fp, *p) for p in poses])
    return bool(
        (pts[:, 0].min() - pad < x0)
        or (pts[:, 0].max() + pad > x1)
        or (pts[:, 1].min() - pad < y0)
        or (pts[:, 1].max() + pad > y1)
    )


def swept_rotation(
    grid: Grid,
    fp: Footprint,
    pivot: tuple[float, float],
    yaw: float | None = None,
    signed_angle: float | None = None,
) -> np.ndarray:
    """Cells the footprint covers turning about the pivot from `yaw` through `signed_angle`
    (+ccw): the polygon rasterised at every heading of turn_headings(). Without a heading
    and angle, the disc of the footprint's reach - the complete sweep of ANY turn."""
    require_axis_aligned(grid.meta)
    mask = np.zeros(grid.data.shape, dtype=bool)
    res = grid.meta.resolution
    if yaw is not None and signed_angle is not None:
        for h in turn_headings(fp, res, yaw, signed_angle):
            rasterize_polygon(grid, _polygon_world(fp, pivot[0], pivot[1], h), mask)
        return dilate(mask, margin_cells(fp, res))
    r = fp.reach_m
    c0 = max(0, int(math.floor((pivot[0] - r - grid.meta.origin_x) / res)))
    c1 = min(grid.width - 1, int(math.floor((pivot[0] + r - grid.meta.origin_x) / res)))
    r0 = max(0, int(math.floor((pivot[1] - r - grid.meta.origin_y) / res)))
    r1 = min(grid.height - 1, int(math.floor((pivot[1] + r - grid.meta.origin_y) / res)))
    if c1 >= c0 and r1 >= r0:
        cols = np.arange(c0, c1 + 1)
        rows = np.arange(r0, r1 + 1)
        X, Y = np.meshgrid(grid.meta.origin_x + (cols + 0.5) * res, grid.meta.origin_y + (rows + 0.5) * res)
        mask[r0 : r1 + 1, c0 : c1 + 1] = (X - pivot[0]) ** 2 + (Y - pivot[1]) ** 2 <= r * r
    return dilate(mask, margin_cells(fp, res))


@dataclass
class Clearance:
    occupied: int
    unknown: int
    keepout: int
    cells: int
    outside: bool = False  # part of the sweep leaves the map: never clear, whatever the mask holds

    @property
    def clear(self) -> bool:
        return not self.outside and self.occupied == 0 and self.unknown == 0 and self.keepout == 0


def check(grid: Grid, mask: np.ndarray, keepout: Grid | None = None, outside: bool = False) -> Clearance:
    """Unknown cells count as blocked: approval needs observed free space (spec §5.4).
    `outside` (from line_outside/rotation_outside) is kept apart from the in-map mask,
    which is clipped to the grid and so cannot express overhang."""
    occ = int(((grid.data >= 65) & mask).sum())
    unk = int(((grid.data == -1) & mask).sum())
    ko = int(((keepout.data >= 65) & mask).sum()) if keepout is not None else 0
    return Clearance(occ, unk, ko, int(mask.sum()), outside)
