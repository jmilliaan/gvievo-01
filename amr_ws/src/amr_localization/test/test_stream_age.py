"""WP-C1 contract (cpu-load plan §4a a = C#10, 2026-11-16): localization_monitor drains its
age-only streams at the tick, and their ages come from the DDS source_timestamp.

Pure part: stream_age. Node part: checked in the source, since the node needs rclpy
(a vehicle-side colcon test exercises it for real)."""

from __future__ import annotations

import ast
import pathlib

from amr_localization import readiness as rd
from amr_localization import stream_age

NODE = pathlib.Path(__file__).resolve().parents[1] / "amr_localization" / "localization_monitor_node.py"
WALL = 1_731_740_000_000_000_000  # ns


def queue(*items):
    q = list(items)
    return lambda: q.pop(0) if q else None


def info(age_s: float) -> dict:
    return {"source_timestamp": WALL - int(age_s * 1e9), "received_timestamp": 0}


def test_the_age_is_the_source_timestamps_not_the_drain_time():
    now = 500.0  # the node clock (sim time works the same: only the wall-clock age carries over)
    got = stream_age.drain(queue(("a", info(0.30)), ("b", info(0.02))), now, WALL, prev_drain=499.9)
    assert [m for m, _ in got] == ["a", "b"], "oldest first, every queued sample"
    assert abs(got[0][1] - (now - 0.30)) < 1e-6 and abs(got[1][1] - (now - 0.02)) < 1e-6
    assert stream_age.newest(got) == got[1][1]


def test_a_late_drain_ages_a_sample_and_the_limits_still_judge_it():
    """A scan written 0.3 s ago is stale against the 0.15 s limit even though it is taken now."""
    now = 500.0
    t = stream_age.newest(stream_age.drain(queue(("scan", info(0.30))), now, WALL, None))
    r = rd.Readiness()
    r.on_initialpose(now - 10.0)
    r.evaluate(now, {"scan": now - t, "wheels": 0.0, "imu": 0.0, "tf": 0.0})
    assert r.reason == "stale: scan"
    t = stream_age.newest(stream_age.drain(queue(("scan", info(0.10))), now, WALL, None))
    r.evaluate(now, {"scan": now - t, "wheels": 0.0, "imu": 0.0, "tf": 0.0})
    assert r.reason != "stale: scan"


def test_no_source_timestamp_credits_the_previous_drain_never_now():
    got = stream_age.drain(queue(("a", {"source_timestamp": 0}), ("b", None)), 10.0, WALL, prev_drain=9.9)
    assert [t for _, t in got] == [9.9, 9.9], "it arrived after the last drain: never fresher than that"
    assert stream_age.drain(queue(("a", {})), 10.0, WALL, prev_drain=None) == [], "no evidence at all"


def test_a_future_source_time_is_age_zero():
    got = stream_age.drain(queue(("a", {"source_timestamp": WALL + 5_000_000_000})), 10.0, WALL, None)
    assert got == [("a", 10.0)]


def test_the_drain_is_bounded_and_keep_filters():
    many = queue(*[(i, info(0.001 * (100 - i))) for i in range(100)])
    got = stream_age.drain(many, 1.0, WALL, None, limit=stream_age.MAX_TAKE)
    assert len(got) == stream_age.MAX_TAKE
    assert stream_age.newest(got, lambda m: m < 10) == got[9][1]
    assert stream_age.newest(got, lambda m: False) is None


def test_the_limits_are_unchanged():
    assert rd.Limits().age_limits == {"scan": 0.15, "wheels": 0.10, "imu": 0.20, "tf": 0.20}
    assert (rd.Limits().wheels_grace_s, rd.Limits().imu_grace_s) == (0.4, 0.6)


def _calls(tree, name: str):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", None)) == name]


def test_the_node_polls_the_four_age_only_streams():
    src = NODE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert "take_message" in src and "stream_age.drain" in src
    polled = {c.args[1].value for c in _calls(tree, "poll")
              if len(c.args) > 1 and isinstance(c.args[1], ast.Constant)}
    assert polled == {"/scan", "/imu/data", "/wheel_states", "/drives/status"}
    for c in _calls(tree, "create_subscription"):
        topic = c.args[1].value if len(c.args) > 1 and isinstance(c.args[1], ast.Constant) else None
        assert topic not in polled, f"{topic} still has a per-message callback"
    assert "class PolledGroup(CallbackGroup)" in src and "return False" in src
    # the drain runs before evaluate() in the tick
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_tick")
    first = tick.body[0]
    assert isinstance(first, ast.Expr) and first.value.func.attr == "_drain"
    # the ages a drained sample gets are the stream_age ones: no arrival-time touch is left
    assert "_touch(" not in src


def test_scan_gated_is_raw_and_decoded_once_per_match():
    src = NODE.read_text(encoding="utf-8")
    assert '"/scan_gated", self._on_scan_gated, SENSOR_DATA, raw=True' in src
    assert src.count("deserialize_message(") == 1, "one decode site, cached per raw buffer"
    assert 'start_parameter_services=False' in src and "tf_thread.start(" in src
    assert "TransformListener(" not in src, "TF on its own lean node (§4a e)"
