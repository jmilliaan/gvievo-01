"""Occupancy grids as files: the nav2 map_server PGM + YAML convention.

Pure functions, numpy arrays. Used by the scan synthesiser (world in), the
survey save (map out) and the route editor (map in). Cell values follow
nav_msgs/OccupancyGrid: -1 unknown, 0 free, 100 occupied.

PGM rows run top-down; the grid's row 0 is the bottom (lowest y), so the
image is flipped on read and write. origin = world pose of the grid's
(0, 0) cell corner; only yaw-free origins are written here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import yaml


@dataclass(frozen=True)
class GridMeta:
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float = 0.0
    occupied_thresh: float = 0.65
    free_thresh: float = 0.196  # 205 (unknown) is 0.19608: not free, not occupied
    negate: int = 0


@dataclass
class Grid:
    data: np.ndarray  # int8 [rows, cols], row 0 = bottom
    meta: GridMeta

    @property
    def height(self) -> int:
        return int(self.data.shape[0])

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        c = int(np.floor((x - self.meta.origin_x) / self.meta.resolution))
        r = int(np.floor((y - self.meta.origin_y) / self.meta.resolution))
        return r, c

    def cell_to_world(self, r: int, c: int) -> tuple[float, float]:
        """Centre of cell (r, c)."""
        return (
            self.meta.origin_x + (c + 0.5) * self.meta.resolution,
            self.meta.origin_y + (r + 0.5) * self.meta.resolution,
        )


def to_pgm_bytes(grid: Grid) -> bytes:
    """Binary PGM (P5). unknown -> 205, free -> 254, occupied -> 0 (map_server trinary)."""
    img = np.full(grid.data.shape, 205, dtype=np.uint8)
    img[grid.data == 0] = 254
    img[grid.data >= 65] = 0
    img = np.flipud(img)
    header = f"P5\n{grid.width} {grid.height}\n255\n".encode()
    return header + img.tobytes()


def from_pgm_bytes(raw: bytes, meta: GridMeta) -> Grid:
    tokens, pos = [], 0
    while len(tokens) < 4:
        while raw[pos : pos + 1].isspace():
            pos += 1
        if raw[pos : pos + 1] == b"#":
            pos = raw.index(b"\n", pos) + 1
            continue
        end = pos
        while not raw[end : end + 1].isspace():
            end += 1
        tokens.append(raw[pos:end])
        pos = end
    pos += 1  # single whitespace after maxval
    if tokens[0] != b"P5":
        raise ValueError("only binary PGM (P5) is supported")
    w, h, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    img = np.frombuffer(raw[pos : pos + w * h], dtype=np.uint8).reshape(h, w)
    img = np.flipud(img)
    occ = (maxval - img.astype(np.float64)) / maxval if not meta.negate else img / maxval
    data = np.full(img.shape, -1, dtype=np.int8)
    data[occ >= meta.occupied_thresh] = 100
    data[occ <= meta.free_thresh] = 0
    return Grid(data, meta)


def write(grid: Grid, path_stem: str) -> tuple[str, str]:
    """Write <stem>.pgm and <stem>.yaml. Returns their paths."""
    pgm, yml = path_stem + ".pgm", path_stem + ".yaml"
    with open(pgm, "wb") as fh:
        fh.write(to_pgm_bytes(grid))
    doc = {
        "image": os.path.basename(pgm),
        "mode": "trinary",
        "resolution": float(grid.meta.resolution),
        "origin": [float(grid.meta.origin_x), float(grid.meta.origin_y), float(grid.meta.origin_yaw)],
        "negate": int(grid.meta.negate),
        "occupied_thresh": float(grid.meta.occupied_thresh),
        "free_thresh": float(grid.meta.free_thresh),
    }
    with open(yml, "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False)
    return pgm, yml


def read(yaml_path: str) -> Grid:
    with open(yaml_path) as fh:
        doc = yaml.safe_load(fh)
    meta = GridMeta(
        resolution=float(doc["resolution"]),
        origin_x=float(doc["origin"][0]),
        origin_y=float(doc["origin"][1]),
        origin_yaw=float(doc["origin"][2]) if len(doc["origin"]) > 2 else 0.0,
        occupied_thresh=float(doc.get("occupied_thresh", 0.65)),
        free_thresh=float(doc.get("free_thresh", 0.196)),
        negate=int(doc.get("negate", 0)),
    )
    image = doc["image"]
    if not os.path.isabs(image):
        image = os.path.join(os.path.dirname(yaml_path), image)
    with open(image, "rb") as fh:
        return from_pgm_bytes(fh.read(), meta)


def from_occupancy_grid_msg(msg) -> Grid:
    """nav_msgs/OccupancyGrid -> Grid (row 0 = bottom, as in the message)."""
    data = np.asarray(msg.data, dtype=np.int8).reshape(msg.info.height, msg.info.width)
    q = msg.info.origin.orientation
    yaw = float(np.arctan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z))
    meta = GridMeta(
        resolution=float(msg.info.resolution),
        origin_x=float(msg.info.origin.position.x),
        origin_y=float(msg.info.origin.position.y),
        origin_yaw=yaw,
    )
    return Grid(data.copy(), meta)


# ---------------------------------------------------------------------------
# Image (pixel) <-> world, for the route editor. The browser uses the SAME
# formulas (amr_web/static/editor.js); these are the reference, tested with
# non-zero origin, origin yaw, row inversion and non-default resolution.
# Pixel (u, v): u = column from the left, v = row from the TOP of the image,
# continuous (a pixel's centre is at +0.5). Origin yaw rotates the grid axes
# about the grid origin corner (map_server convention).
# ---------------------------------------------------------------------------


def world_to_pixel(meta: GridMeta, height: int, x: float, y: float) -> tuple[float, float]:
    dx, dy = x - meta.origin_x, y - meta.origin_y
    c, s = np.cos(meta.origin_yaw), np.sin(meta.origin_yaw)
    gx = c * dx + s * dy  # into grid axes
    gy = -s * dx + c * dy
    u = gx / meta.resolution
    v = height - gy / meta.resolution
    return float(u), float(v)


def pixel_to_world(meta: GridMeta, height: int, u: float, v: float) -> tuple[float, float]:
    gx = u * meta.resolution
    gy = (height - v) * meta.resolution
    c, s = np.cos(meta.origin_yaw), np.sin(meta.origin_yaw)
    return float(meta.origin_x + c * gx - s * gy), float(meta.origin_y + s * gx + c * gy)
