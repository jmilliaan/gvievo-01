"""What a DriveStatus / WheelStates / OutputPaths message says, read the same way
everywhere. Pure: no rclpy, no message import (the callers pass the fields).

The state strings are cia402.decode_state()'s, as drive_node publishes them.
"""

from __future__ import annotations

OPERATION_ENABLED = "Operation enabled"
SWITCH_ON_DISABLED = "Switch on disabled"  # STO held by the safety chain (FX3), or not yet reset
# drive_node's standby (2026-10-08): linked, power stage off on purpose. Not an emergency.
STANDBY_STATES = ("Ready to switch on", "Switched on")
LINK_STANDBY = "standby"  # = amr_base.canopen.STANDBY (test_drive_state pins it)


def torque_off(operational: bool, left_state: str, right_state: str) -> bool:
    """Not operational AND neither statusword says Operation enabled: the drives' torque is
    gone (the safety chain or a stop). A feedback-only loss with a drive still enabled is
    never torque off."""
    return not operational and OPERATION_ENABLED not in (left_state, right_state)


def still(left_rad_s: float, right_rad_s: float, eps: float, inclusive: bool = True,
          valid: bool = True) -> bool:
    """Both wheels within eps rad/s of zero (and their samples valid). inclusive: |w| <= eps;
    else |w| < eps - each caller keeps the comparison its threshold was tuned with."""
    if not valid:
        return False
    if inclusive:
        return abs(left_rad_s) <= eps and abs(right_rad_s) <= eps
    return abs(left_rad_s) < eps and abs(right_rad_s) < eps


def field_clear(status, index: int) -> bool | None:
    """/output_paths status[index] (True = the field is clear), or None for a malformed
    array, which is no evidence at all: the caller lets the previous reading age out."""
    if status is None or len(status) <= index:
        return None
    return bool(status[index])
