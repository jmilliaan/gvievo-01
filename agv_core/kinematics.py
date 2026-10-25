"""Differential-drive geometry: the conversion between body motion and wheels.

Pure geometry: it knows nothing about what decides where to go (the LINE follower,
Nav2), so every controller meets the motors through the same conversions. Keep
control logic and sensor knowledge out of here.

The dimensions themselves live in the profile (vehicle section) and reach
here through config, which also does the deriving - MPS_PER_RPM and friends are
computed from wheel diameter, gearing and track so the profile cannot hold a
conversion factor that disagrees with the geometry it came from.
"""
from agv_core import config


def to_int32(n):
    """An integer as the drive's signed 32-bit counter would hold it (two's complement wrap)."""
    n = int(n) & 0xFFFFFFFF
    return n - (1 << 32) if n >= 1 << 31 else n


def counts_delta(new, old):
    """6064h is INT32 and wraps; the shorter way round is the real travel."""
    return to_int32(int(new) - int(old))


def approach_decel_rpm_s(v_rpm, end_rpm, distance_m, mps_per_rpm):
    """The constant r/min/s that takes v_rpm to end_rpm over distance_m. Uncapped: the
    caller compares it with 6084h (or caps it). mps_per_rpm is passed, not read, so the
    mission loader can check a profile that is not the loaded one."""
    return (v_rpm ** 2 - end_rpm ** 2) * mps_per_rpm / (2.0 * distance_m)


def max_yaw_accel(driver_accel_rpm_s):
    """rad/s^2 available for steering, given the 6083h/6084h setting.

    Yaw acceleration is capped by how fast the drivers will slew the wheel
    difference, which is two wheels each ramping at 6083h. This is not a spare
    fact: it is the binding constraint on steering authority, and it is a
    property of THESE DRIVES rather than of whatever is steering.

    *** Derive the limit from here; never hardcode one. *** A controller that
    commands a yaw rate the drives cannot slew to diverges, and a later change
    to drivers.ramp.auto.accel would silently make a hardcoded limit wrong.
    """
    return 2.0 * driver_accel_rpm_s * config.RAD_S_PER_RPM_DIFF


def body_to_wheels(v_mps, omega_rad_s):
    """(forward speed, yaw rate) -> (left, right) motor r/min in DRIVER terms.

    No clamping. Saturation is a control decision - the caller has to scale both
    wheels together to keep the turn ratio, and only it knows the base speed.
    """
    diff_rpm = omega_rad_s / config.RAD_S_PER_RPM_DIFF
    base_rpm = v_mps * config.RPM_PER_MPS
    left = base_rpm - diff_rpm / 2.0
    right = base_rpm + diff_rpm / 2.0
    return (-left if config.INVERT_LEFT else left,
            -right if config.INVERT_RIGHT else right)


def wheels_to_body(left_rpm, right_rpm):
    """Exact inverse of body_to_wheels(). For odometry and diagnostics."""
    left = -left_rpm if config.INVERT_LEFT else left_rpm
    right = -right_rpm if config.INVERT_RIGHT else right_rpm
    return ((left + right) / 2.0 * config.MPS_PER_RPM,
            (right - left) * config.RAD_S_PER_RPM_DIFF)


def rpm_to_mps(rpm):
    return rpm * config.MPS_PER_RPM


def mps_to_rpm(mps):
    return mps * config.RPM_PER_MPS
