"""WP-C5: drive_node's gyro chain (agv_core.gyro.GyroFilter) keeps everything imu_bias_node did:
nothing until calibrated, the plausibility check with its withholding OFF by default, NaN/inf
dropped, /imu/recalibrate. Pure: runs on the dev box."""

import math
import pathlib

import pytest
from agv_core import gyro

BIAS = math.radians(0.06)


def _still(f, t0, seconds, gz=BIAS, dt=0.02):
    t = t0
    out = None
    while t < t0 + seconds:
        f.wheels(t, True, 0.0)
        out = f.sample(t, gz)
        t += dt
    return t, out


def test_nothing_until_calibrated_then_the_bias_is_removed():
    f = gyro.GyroFilter()
    t, out = _still(f, 0.0, 2.2)
    assert out is None and not f.est.calibrated  # settle 0.3 + window 2.0 not done yet
    t, out = _still(f, t, 0.3)
    assert f.est.calibrated and out == pytest.approx(0.0, abs=1e-9)
    f.wheels(t, False, 0.0)
    assert f.sample(t, BIAS + 0.2) == pytest.approx(0.2)
    assert any("bias" in text for _, text in f.drain())


def test_no_wheel_feedback_is_not_stillness():
    f = gyro.GyroFilter(wheel_timeout_s=0.2)
    f.wheels(0.0, True, 0.0)
    for k in range(200):
        assert f.sample(0.3 + 0.02 * k, BIAS) is None  # wheels 0.3 s old: never calibrates


def test_nonfinite_samples_are_dropped_and_counted():
    f = gyro.GyroFilter()
    t, _ = _still(f, 0.0, 2.6)
    assert f.sample(t, math.nan) is None and f.est.nonfinite == 1
    assert f.est.calibrated and f.est.bias == pytest.approx(BIAS)
    assert any("non-finite" in text for _, text in f.drain())


def test_the_check_logs_but_does_not_withhold_by_default():
    f = gyro.GyroFilter()
    t, _ = _still(f, 0.0, 2.6)
    f.drain()
    for _ in range(60):  # a 0.3 rad/s wheel turn, the gyro reads nothing
        f.wheels(t, False, 0.3)
        out = f.sample(t, BIAS)
        t += 0.02
    assert f.suspect and out is not None and f.withheld == 0
    assert any(lvl == "error" and "gyro_check off" in text for lvl, text in f.drain())


def test_with_gyro_check_on_a_suspect_gyro_is_withheld_until_a_turn_agrees():
    f = gyro.GyroFilter(withhold=True)
    t, _ = _still(f, 0.0, 2.6)
    for _ in range(60):
        f.wheels(t, False, 0.3)
        out = f.sample(t, BIAS)
        t += 0.02
    assert f.suspect and out is None and f.withheld > 0
    for _ in range(60):
        f.wheels(t, False, 0.3)
        out = f.sample(t, BIAS + 0.3)
        t += 0.02
    assert not f.suspect and out == pytest.approx(0.3)


def test_recalibrate_discards_the_bias():
    f = gyro.GyroFilter()
    t, _ = _still(f, 0.0, 2.6)
    assert "still" in f.recalibrate()
    f.wheels(t, True, 0.0)
    assert f.sample(t, BIAS) is None and not f.est.calibrated


def test_the_old_import_paths_still_work():
    from amr_localization.gyro_bias import BiasEstimator
    from amr_localization.gyro_check import GyroCheck, curve_yaw_rate

    assert BiasEstimator is gyro.BiasEstimator and GyroCheck is gyro.GyroCheck
    assert curve_yaw_rate is gyro.curve_yaw_rate


def test_drive_node_publishes_imu_data_and_raw_only_with_subscribers():
    """Contract (the node needs rclpy, so read its source)."""
    src = (pathlib.Path(__file__).parents[1] / "amr_base" / "drive_node.py").read_text(encoding="utf-8")
    assert '"/imu/data"' in src and '"/imu/recalibrate"' in src
    body = src.split("def _publish_imu(", 1)[1].split("\n    def ", 1)[0]
    assert 'if self._subs.get("raw"):' in body and "self._gyro.sample(" in body
    assert "from amr_localization" not in src  # no package cycle (C#11)
