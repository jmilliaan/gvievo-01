"""WP-P6 black box (S-rosbag2-snapshot-mcap): the recorder argv, the trigger policy, the prune plan.

Pure (amr_bringup.blackbox); the node and the launch entry need ROS (test_launch_layers walks the
launch). On the vehicle: one snapshot writes a file that `ros2 bag reindex` opens.
"""

import os

import pytest

from amr_bringup import blackbox as bb


def test_the_recorder_is_snapshot_mode_mcap_under_its_own_node_name():
    argv = bb.record_argv("/s/blackbox/bb-1", 16)
    assert argv[:3] == ["ros2", "bag", "record"] and "--snapshot-mode" in argv
    assert argv[argv.index("--max-cache-size") + 1] == str(16 * 1024 * 1024)
    assert argv[argv.index("-s") + 1] == "mcap"
    assert argv[argv.index("--node-name") + 1] == "amr_blackbox" == bb.NODE_NAME
    assert bb.SNAPSHOT_SERVICE == "/amr_blackbox/snapshot"
    assert argv[argv.index("-o") + 1] == "/s/blackbox/bb-1"
    with pytest.raises(ValueError):
        bb.record_argv("/x", 0)


def test_the_topics_are_the_low_rate_set_with_health_order_and_trolley():
    t = set(bb.TOPICS)
    assert {"/amr/events", "/amr/device_health", "/amr/line/order_state", "/amr/rear/trolley"} <= t
    assert {"/wheel_states_ui", "/amr/line_track_ui", "/amr/panel_state_ui", "/amr/mode_state"} <= t
    assert not t & {"/scan", "/map", "/amr/line_track", "/wheel_states", "/cmd_wheel_vel", "/tf"}
    assert len(bb.TOPICS) == len(t)


def test_the_health_topic_is_the_one_health_pub_publishes():
    """Spelt out in blackbox (rclpy-free); health_pub.TOPIC is the owner (WP-H1)."""
    src = os.path.join(os.path.dirname(__file__), "..", "..", "amr_base", "amr_base", "health_pub.py")
    with open(src, encoding="utf-8") as fh:
        assert f'TOPIC = "{bb.DEVICE_HEALTH_TOPIC}"' in fh.read()


def test_every_respawn_records_into_a_new_directory():
    cmd = bb.recorder_cmd("/home/u/.amr", 8)
    assert cmd[:2] == ["sh", "-c"] and cmd[3] == "sh" and cmd[4] == os.path.join("/home/u/.amr", "blackbox")
    assert '-o "$1/bb-$(date +%Y%m%d-%H%M%S)"' in cmd[2]
    assert cmd[2].startswith('mkdir -p "$1" && exec ros2 bag')
    assert str(8 * 1024 * 1024) in cmd[2]
    assert bb.newest_bag_dir(["x", "bb-20261116-101010", "bb-20261116-090909"]) == "bb-20261116-101010"
    assert bb.newest_bag_dir(["x"]) == ""


def test_off_unless_asked():
    assert not bb.enabled(None) and not bb.enabled("") and not bb.enabled("false")
    assert bb.enabled("true") and bb.enabled("1")


def test_a_fault_edge_dumps_after_the_post_window_and_a_baseline_does_not():
    p = bb.TriggerPolicy(post_s=3.0, min_gap_s=60.0)
    p.observe_mode(0.0, bb.MODE_FAULT, "BASE_NOT_READY")  # first sample: a baseline (respawn in FAULT)
    assert p.due(100.0) == []
    p.observe_mode(101.0, 7)  # LINE
    p.observe_mode(102.0, bb.MODE_FAULT, "LAYER_EXITED")
    p.observe_mode(102.5, bb.MODE_FAULT, "LAYER_EXITED")  # no new edge
    assert p.due(104.9) == []  # the aftermath goes into the file too
    assert p.due(105.0) == ["mode FAULT LAYER_EXITED"]
    assert p.due(106.0) == []


def test_line_hold_fault_and_error_events_trigger_and_coalesce_within_the_gap():
    p = bb.TriggerPolicy(post_s=2.0, min_gap_s=30.0)
    p.observe_line(0.0, 2)  # RUNNING, baseline
    p.observe_line(1.0, bb.LINE_HOLD, "field")
    p.observe_event(1.5, 1, "PANEL_STALE")  # WARN: not a trigger
    assert p.due(3.0) == ["line HOLD field"]
    p.observe_line(5.0, 2)
    p.observe_line(6.0, bb.LINE_FAULT)
    p.observe_event(7.0, bb.EVENT_ERROR, "DRIVE_FAULT")
    p.observe_event(7.1, bb.EVENT_ERROR, "DRIVE_FAULT")  # once per dump
    assert p.due(10.0) == []  # inside the 30 s gap: kept, not lost
    assert p.due(33.0) == ["line FAULT", "event DRIVE_FAULT"]
    p.observe_line(40.0, bb.LINE_FAULT)  # no change: no edge
    assert p.due(100.0) == []


def test_prune_keeps_the_newest_and_never_touches_the_live_recorder():
    live = os.path.join("/bb", "bb-3")
    files = [(os.path.join("/bb", f"bb-1/f{i}.mcap"), float(i), 10) for i in range(5)]
    files += [(os.path.join(live, "a.mcap"), 1.0, 10), (os.path.join(live, "b.mcap"), 0.5, 10)]
    out = bb.prune_plan(files, keep=4, max_bytes=10_000, protect=live)
    # the two live files count; then f4, f3 fit; f2, f1, f0 go
    assert sorted(out) == sorted(os.path.join("/bb", f"bb-1/f{i}.mcap") for i in (0, 1, 2))
    assert bb.prune_plan(files, keep=100, max_bytes=35, protect=live) == [
        os.path.join("/bb", f"bb-1/f{i}.mcap") for i in (3, 2, 1, 0)
    ]
    assert bb.prune_plan([], keep=1) == []


def test_snapshot_files_lists_only_mcap(tmp_path):
    d = tmp_path / "blackbox" / "bb-1"
    d.mkdir(parents=True)
    (d / "bb-1_0.mcap").write_bytes(b"x" * 3)
    (d / "metadata.yaml").write_text("x")
    got = bb.snapshot_files(str(tmp_path))
    assert [(os.path.basename(p), size) for p, _t, size in got] == [("bb-1_0.mcap", 3)]
    assert bb.snapshot_files(str(tmp_path / "nothing")) == []
