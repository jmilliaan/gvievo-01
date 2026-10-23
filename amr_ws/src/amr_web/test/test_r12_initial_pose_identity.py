"""Review R12: an initial pose drawn on one map must never seed localization on another."""

from amr_web.adapter import initial_pose_mismatch, localization_map

MODE = {
    "mode_name": "NAVIGATION",
    "active_map_id": "hall_a",
    "active_map_revision": 3,
    "active_map_sha256": "abc",
    "generation": 12,
}


def test_pose_on_the_active_map_under_the_same_generation_is_applied():
    assert initial_pose_mismatch(MODE, "hall_a", 3, 12, "abc") == ""
    assert initial_pose_mismatch(MODE, "hall_a", 3, 12) == ""  # no sha offered: id + rev + generation


def test_pose_drawn_on_another_map_with_the_same_frame_is_refused():
    assert "hall_b rev3" in initial_pose_mismatch(MODE, "hall_b", 3, 12)
    assert "rev2" in initial_pose_mismatch(MODE, "hall_a", 2, 12)
    assert "sha256" in initial_pose_mismatch(MODE, "hall_a", 3, 12, "different")


def test_active_map_switched_during_the_drag_is_refused():
    assert "changed mode" in initial_pose_mismatch(MODE, "hall_a", 3, 11)
    assert initial_pose_mismatch(dict(MODE, mode_name="TRANSITIONING"), "hall_a", 3, 12)
    assert initial_pose_mismatch(dict(MODE, mode_name="IDLE", active_map_id=""), "hall_a", 3, 12)
    assert initial_pose_mismatch(None, "hall_a", 3, 12)


# LINE with tape localization (2026-10-23): AMCL runs on the map the line layer started with.
LINE_MODE = {"mode_name": "LINE", "active_map_id": "", "active_map_revision": 0, "generation": 14}
LINE = {"loc_map_id": "rev-boiacca-map-01", "loc_map_revision": 1, "loc_map_sha256": "d792"}


def test_line_takes_a_pose_drawn_on_its_tape_localization_map():
    assert initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 1, 14, "d792", LINE, 0.5) == ""
    assert localization_map(LINE_MODE, LINE, 0.5)["layer"] == "line"


def test_line_refuses_another_map_off_or_a_stale_line_state():
    assert "rev2" in initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 2, 14, "", LINE, 0.5)
    assert "sha256" in initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 1, 14, "other", LINE, 0.5)
    assert "changed mode" in initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 1, 13, "", LINE, 0.5)
    off = dict(LINE, loc_map_id="", loc_map_revision=0)
    why = initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 1, 14, "", off, 0.5)
    assert "tape localization is off" in why
    # a LineState older than LINE_FRESH_S may be a replaced layer's
    assert initial_pose_mismatch(LINE_MODE, "rev-boiacca-map-01", 1, 14, "", LINE, 10.0)
    # NAVIGATION never takes the line layer's map
    assert localization_map(MODE, LINE, 0.5)["layer"] == "navigation"
