import os

import numpy as np
import pytest
from amr_maps.grid import Grid, GridMeta

from amr_mission import map_bundle as mb


def small_grid() -> Grid:
    d = np.full((20, 30), -1, dtype=np.int8)
    d[5:15, 5:25] = 0
    d[5, 5:25] = 100
    return Grid(d, GridMeta(0.05, -1.0, -0.5))


def manifest(rev: int = 1) -> mb.Manifest:
    return mb.Manifest(
        map_id="line_section",
        revision=rev,
        created=mb.now_iso(),
        frame_id="map",
        resolution=0.05,
        origin=[-1.0, -0.5, 0.0],
        width=30,
        height=20,
        start={"x_m": 0.0, "y_m": 0.0, "yaw_rad": 0.0, "description": "floor mark A"},
        review={"dx_m": 0.02, "dy_m": -0.01, "dyaw_rad": 0.01, "note": "seams ok"},
    )


def fake_posegraph(tmp_path) -> str:
    stem = str(tmp_path / "pg")
    for ext in (".posegraph", ".data"):
        with open(stem + ext, "wb") as fh:
            fh.write(b"\x00\x01" * 100)
    return stem


def test_stage_verify_publish_load(tmp_path):
    maps = str(tmp_path / "maps")
    stage = mb.staging_dir(maps, "line_section", 1)
    m = mb.stage_bundle(stage, small_grid(), fake_posegraph(tmp_path), manifest())
    assert set(m.files) == {"map.pgm", "map.yaml", "posegraph.posegraph", "posegraph.data"}
    assert mb.list_revisions(maps, "line_section") == []  # still staging
    mb.verify(stage)
    dest = mb.publish(stage, maps, "line_section", 1)
    assert dest.endswith("rev1") and not os.path.exists(stage)
    assert mb.list_revisions(maps, "line_section") == [1]
    assert mb.next_revision(maps, "line_section") == 2
    m2, g = mb.load(maps, "line_section", 1)
    assert m2.sha256 == m.sha256
    assert np.array_equal(g.data, small_grid().data)
    assert (g.meta.origin_x, g.meta.origin_y) == (-1.0, -0.5)


def test_missing_posegraph_fails_before_publish(tmp_path):
    maps = str(tmp_path / "maps")
    stage = mb.staging_dir(maps, "m", 1)
    with pytest.raises(mb.BundleError, match="serialisation missing"):
        mb.stage_bundle(stage, small_grid(), str(tmp_path / "nope"), manifest())
    with pytest.raises(mb.BundleError, match="no pose graph"):
        mb.stage_bundle(stage, small_grid(), None, manifest())
    mb.discard(stage)
    assert mb.list_revisions(maps, "m") == []


def test_corruption_is_caught_by_verify(tmp_path):
    maps = str(tmp_path / "maps")
    stage = mb.staging_dir(maps, "m", 1)
    mb.stage_bundle(stage, small_grid(), fake_posegraph(tmp_path), manifest())
    os.remove(os.path.join(stage, "posegraph.data"))
    with pytest.raises(mb.BundleError, match="missing"):
        mb.verify(stage)
    stage = mb.staging_dir(maps, "m", 2)
    mb.stage_bundle(stage, small_grid(), fake_posegraph(tmp_path), manifest(2))
    with open(os.path.join(stage, "map.pgm"), "ab") as fh:
        fh.write(b"x")
    with pytest.raises(mb.BundleError, match="hash mismatch"):
        mb.verify(stage)


def test_revisions_are_immutable(tmp_path):
    maps = str(tmp_path / "maps")
    stage = mb.staging_dir(maps, "m", 1)
    mb.stage_bundle(stage, small_grid(), fake_posegraph(tmp_path), manifest())
    mb.publish(stage, maps, "m", 1)
    stage2 = mb.staging_dir(maps, "m", 1)
    mb.stage_bundle(stage2, small_grid(), fake_posegraph(tmp_path), manifest())
    with pytest.raises(mb.BundleError, match="already exists"):
        mb.publish(stage2, maps, "m", 1)


def test_empty_file_refused(tmp_path):
    maps = str(tmp_path / "maps")
    stage = mb.staging_dir(maps, "m", 1)
    stem = str(tmp_path / "pg")
    open(stem + ".posegraph", "wb").close()
    open(stem + ".data", "wb").close()
    with pytest.raises(mb.BundleError, match="empty"):
        mb.stage_bundle(stage, small_grid(), stem, manifest())


def test_partial_directory_without_manifest_is_not_a_revision(tmp_path):
    maps = str(tmp_path / "maps")
    os.makedirs(os.path.join(maps, "m", "rev3"))
    assert mb.list_revisions(maps, "m") == []
    assert mb.next_revision(maps, "m") == 1


def test_world_fixture_is_surfaces_only(tmp_path):
    import numpy as np
    from amr_maps.generate_sim_factory import build
    from amr_mission.fixtures import surfaces_only, write_world_as_bundle

    world = build()
    surf = surfaces_only(world)
    solid = world.data >= 65
    assert (surf.data >= 65).sum() < solid.sum() * 0.6  # interiors gone
    r, c = world.world_to_cell(10.0, 2.4)  # deep inside rack row C
    assert world.data[r, c] == 100 and surf.data[r, c] == -1
    r, c = world.world_to_cell(10.0, 1.82)  # its south face
    assert surf.data[r, c] == 100
    assert np.array_equal(surf.data == 0, world.data == 0)  # free space untouched

    dest = write_world_as_bundle(str(tmp_path), "w")
    assert dest.endswith("rev1")
    m, g = mb.load(str(tmp_path), "w", 1)
    assert "surfaces" in m.review["note"]
    assert np.array_equal(g.data, surf.data)
