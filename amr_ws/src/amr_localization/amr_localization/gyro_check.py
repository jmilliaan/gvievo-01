"""Moved to agv_core.gyro (unified plan WP-C5, 2026-11-16): drive_node runs the check itself
now, and amr_base may not import amr_localization. These names stay for imu_bias_node (sim only),
line_follow_node (curve_yaw_rate) and the tests."""

from agv_core.gyro import GyroCheck, curve_yaw_rate  # noqa: F401
