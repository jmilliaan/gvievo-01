"""Differential-drive geometry: the conversion between body motion and wheels.

Deliberately separate from the control law (draft_pid_design.md section 6): a
SLAM pose controller producing (linear velocity, angular velocity) can replace
autopilot.py without touching this file or the motor interface under it. Nothing
here knows what a line sensor is.

The dimensions themselves live in agv-profile.json (vehicle section) and reach
here through config, which also does the deriving - MPS_PER_RPM and friends are
computed from wheel diameter, gearing and track so the profile cannot hold a
conversion factor that disagrees with the geometry it came from.
"""
import config


def max_yaw_accel(driver_accel_rpm_s):
    """rad/s^2 available for steering, given the 6083h/6084h setting.

    Yaw acceleration is capped by how fast the drivers will slew the wheel
    difference, which is two wheels each ramping at 6083h. This is not a spare
    fact: it is the binding constraint on steering gain (see config.K_RATIO).
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
