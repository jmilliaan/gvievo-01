"""WP-C16 (2026-11-16): the 5 Hz display topics amr_web's live view reads instead of /scan + /tf.

The packing is checked by reading it back with the consumer's own decoder,
amr_web.live.cloud_xy (imported read-only), against the consumer's own projection,
live.scan_points: what the node sends is what the page would have drawn."""

from __future__ import annotations

import math

import numpy as np
import pytest

from amr_maps import live_display as ld

live = pytest.importorskip("amr_web.live")


def test_the_topic_contract_is_the_consumers():
    assert (ld.POSE_TOPIC, ld.SCAN_TOPIC) == (live.DISPLAY_POSE_TOPIC, live.DISPLAY_SCAN_TOPIC)
    assert ld.MAX_POINTS == live.MAX_POINTS
    assert ld.PERIOD_S * 5 <= live.DISPLAY_FRESH_S, "five periods inside the consumer's freshness"
    assert ld.FIELDS == (("x", 0, 7), ("y", 4, 7), ("z", 8, 7)) and ld.POINT_STEP == 12


@pytest.mark.parametrize("beams", [1, 381, 400, 401, 1152, 1652])
def test_the_cloud_round_trips_through_cloud_xy(beams):
    rng = np.random.default_rng(beams)
    ranges = rng.uniform(0.0, 35.0, beams)
    ranges[rng.random(beams) < 0.1] = np.inf
    ranges[rng.random(beams) < 0.05] = np.nan
    a0, inc = -1.658, (3.316 / max(1, beams - 1))
    pose = (3.2, -1.7, 2.1)
    n, data = ld.scan_cloud(ranges, a0, inc, 0.05, 30.0, *pose)
    assert len(data) == n * ld.POINT_STEP and n <= ld.MAX_POINTS
    got = live.cloud_xy(ld.FIELDS, ld.POINT_STEP, data, False)
    want = live.scan_points(list(ranges), a0, inc, 0.05, 30.0, *pose)
    assert len(got) == len(want) == n
    for (gx, gy), (wx, wy) in zip(got, want, strict=True):
        assert abs(gx - wx) <= 1.5e-3 and abs(gy - wy) <= 1.5e-3, "float32 + mm rounding only"
    z = np.frombuffer(data, dtype="<f4").reshape(-1, 3)[:, 2] if n else np.zeros(0)
    assert not z.any(), "z is 0"


def test_an_empty_or_all_invalid_scan_is_an_empty_cloud():
    assert ld.scan_cloud([], 0.0, 0.01, 0.05, 30.0, 0, 0, 0) == (0, b"")
    n, data = ld.scan_cloud([math.inf, math.nan, 0.01, 99.0], 0.0, 0.01, 0.05, 30.0, 0, 0, 0)
    assert (n, data) == (0, b"") and live.cloud_xy(ld.FIELDS, 12, data) == []


def test_world_frame_is_map_only_while_map_odom_is_fresh():
    assert ld.world_frame(0.1, True) == "map"
    assert ld.world_frame(-0.3, True) == "map", "AMCL stamps map->odom ahead"
    assert ld.world_frame(ld.MAP_FRESH_S, True) == "map"
    assert ld.world_frame(ld.MAP_FRESH_S + 0.01, True) == "odom", "a frozen stamp is a dead layer"
    assert ld.world_frame(None, True) == "odom"
    assert ld.world_frame(0.1, False) == "odom", "no map->base_footprint: odom"


def test_yaw_of_matches_the_shared_helper():
    se2 = pytest.importorskip("agv_core.se2")

    class Q:
        def __init__(self, yaw):
            self.x = self.y = 0.0
            self.z, self.w = math.sin(yaw / 2), math.cos(yaw / 2)

    for yaw in (-3.0, -1.0, 0.0, 0.5, 3.1):
        assert ld.yaw_of(Q(yaw)) == pytest.approx(se2.yaw_of(Q(yaw)), abs=1e-12)
