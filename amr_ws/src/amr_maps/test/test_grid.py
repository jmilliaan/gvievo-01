import numpy as np
import pytest
from amr_maps.generate_sim_factory import ORIGIN_X, ORIGIN_Y, build

from amr_maps import grid


def test_pgm_round_trip(tmp_path):
    g = build()
    stem = str(tmp_path / "w")
    grid.write(g, stem)
    back = grid.read(stem + ".yaml")
    assert back.data.shape == g.data.shape
    assert np.array_equal(back.data, g.data)
    assert back.meta.resolution == g.meta.resolution
    assert (back.meta.origin_x, back.meta.origin_y) == (ORIGIN_X, ORIGIN_Y)


def test_row_zero_is_bottom(tmp_path):
    g = grid.Grid(np.zeros((4, 3), dtype=np.int8), grid.GridMeta(0.1, 0.0, 0.0))
    g.data[0, 0] = 100  # bottom-left cell occupied
    raw = grid.to_pgm_bytes(g)
    pixels = raw[len(b"P5\n3 4\n255\n") :]
    assert pixels[-3] == 0  # last row of the image = bottom row of the grid
    assert pixels[0] == 254


def test_unknown_survives(tmp_path):
    g = grid.Grid(np.full((2, 2), -1, dtype=np.int8), grid.GridMeta(0.1, 0.0, 0.0))
    g.data[1, 1] = 0
    back = grid.from_pgm_bytes(grid.to_pgm_bytes(g), g.meta)
    assert back.data[0, 0] == -1 and back.data[1, 1] == 0


def test_world_to_cell_and_back():
    g = build()
    r, c = g.world_to_cell(0.0, 0.0)
    x, y = g.cell_to_world(r, c)
    assert abs(x) <= g.meta.resolution and abs(y) <= g.meta.resolution
    assert g.data[r, c] == 0, "the start mark must be free space"


def test_world_has_walls_and_racks():
    g = build()
    assert g.data[0, :].min() == 100 and g.data[-1, :].max() == 100
    r, c = g.world_to_cell(10.0, 2.4)
    assert g.data[r, c] == 100  # rack row C
    r, c = g.world_to_cell(10.0, 0.0)
    assert g.data[r, c] == 0  # aisle between B and C, the survey aisle
    with pytest.raises(ValueError):
        grid.from_pgm_bytes(b"P2\n1 1\n255\n0", g.meta)


@pytest.mark.parametrize("yaw", [0.0, 0.3, -1.2])
@pytest.mark.parametrize("origin", [(0.0, 0.0), (-3.0, -10.0), (12.5, 4.25)])
@pytest.mark.parametrize("res", [0.05, 0.1, 0.025])
def test_pixel_world_round_trip(yaw, origin, res):
    meta = grid.GridMeta(res, origin[0], origin[1], origin_yaw=yaw)
    h = 400
    for x, y in ((0.0, 0.0), (5.3, -2.1), (-7.7, 9.9)):
        u, v = grid.world_to_pixel(meta, h, x, y)
        bx, by = grid.pixel_to_world(meta, h, u, v)
        assert (bx, by) == pytest.approx((x, y), abs=1e-9)


def test_pixel_conventions():
    meta = grid.GridMeta(0.05, -3.0, -10.0)
    h = 400
    # the grid origin corner is the bottom-left pixel corner of the image
    assert grid.world_to_pixel(meta, h, -3.0, -10.0) == pytest.approx((0.0, 400.0))
    # one cell east, one cell north -> one pixel right, one pixel up (smaller v)
    assert grid.world_to_pixel(meta, h, -2.95, -9.95) == pytest.approx((1.0, 399.0))
    # the centre of cell (row 0, col 0) is at pixel (0.5, 399.5)
    g = build()
    cx, cy = g.cell_to_world(0, 0)
    assert grid.world_to_pixel(g.meta, g.height, cx, cy) == pytest.approx((0.5, 399.5))
