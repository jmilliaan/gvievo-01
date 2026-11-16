"""What a DriveStatus / WheelStates / OutputPaths message says, read the same way
everywhere. Pure: no rclpy, no message import (the callers pass the fields).

The state strings are cia402.decode_state()'s, as drive_node publishes them.
"""

from __future__ import annotations

OPERATION_ENABLED = "Operation enabled"
SWITCH_ON_DISABLED = "Switch on disabled"  # STO held by the safety chain (FX3), or not yet reset
# drive_node's standby (2026-10-08): linked, power stage off on purpose. Not an emergency.
STANDBY_STATES = ("Ready to switch on", "Switched on")
# DriveStatus.left/right_state for a node whose TPDO1 stopped: its cached statusword is not
# evidence of anything (WP-A4).
STALE = "stale"
LINK_STANDBY = "standby"  # = amr_base.canopen.STANDBY (test_drive_state pins it)
LINK_FAULT = "fault"  # = amr_base.canopen.FAULT


def torque_off(operational: bool, left_state: str, right_state: str) -> bool:
    """Not operational AND neither statusword says Operation enabled: the drives' torque is
    gone (the safety chain or a stop). A feedback-only loss with a drive still enabled is
    never torque off."""
    return not operational and OPERATION_ENABLED not in (left_state, right_state)


def has_fault(*states: str) -> bool:
    """Any drive in Fault or Fault reaction active, however the state is spelt."""
    return any("fault" in s.lower() for s in states)


def still(left_rad_s: float, right_rad_s: float, eps: float, inclusive: bool = True,
          valid: bool = True) -> bool:
    """Both wheels within eps rad/s of zero (and their samples valid). inclusive: |w| <= eps;
    else |w| < eps - each caller keeps the comparison its threshold was tuned with."""
    if not valid:
        return False
    if inclusive:
        return abs(left_rad_s) <= eps and abs(right_rad_s) <= eps
    return abs(left_rad_s) < eps and abs(right_rad_s) < eps


def field_clear(status, index: int, active: bool = False) -> bool | None:
    """/output_paths status[index] read as clear (True) or occupied (False), or None for a
    malformed array, which is no evidence at all: the caller lets the previous reading age out.

    `active` is the path's status while the field is OCCUPIED: scanner_fields.yaml
    `protective.active` (WP-E3, 2026-11-16). False on agv-01, so True reads clear."""
    if status is None or len(status) <= index:
        return None
    return bool(status[index]) != bool(active)


def field_valid(valid, index: int) -> bool:
    """/output_paths is_valid[index]: the path bit may be trusted (WP-E2, 2026-11-16). An
    invalid path is UNKNOWN - neither clear nor violated - so it never resumes AUTO and never
    explains a stop as the field's. None = no array to check (pure callers and tests); the
    nodes pass () for a message without is_valid, and a short array is invalid."""
    if valid is None:
        return True
    return len(valid) > index and bool(valid[index])
