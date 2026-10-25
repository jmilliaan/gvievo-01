"""A TF lookup as a planar pose: the one shape every node reads TF in.

No rclpy import: the buffer is the caller's tf2_ros.Buffer, and `time` defaults to
"latest" (an rclpy Time() of zero, which is what Buffer.lookup_transform takes).
Any lookup failure is None - early in a survey, before localisation, or for a
stamp the buffer does not cover, "no pose" is a normal state, not an error.
"""

from __future__ import annotations

from agv_core import se2

yaw_of = se2.yaw_of


def _latest():
    from rclpy.time import Time  # noqa: PLC0415 - only a node that has a buffer needs rclpy

    return Time()


def lookup(buf, target: str, source: str, time=None):
    """The TransformStamped from `source` into `target`, or None."""
    try:
        return buf.lookup_transform(target, source, _latest() if time is None else time)
    except Exception:  # noqa: BLE001 - every TF failure means "not available"
        return None


def lookup_pose(buf, target: str, source: str, time=None) -> tuple[float, float, float] | None:
    """`source`'s origin in `target` as (x, y, yaw), or None."""
    t = lookup(buf, target, source, time)
    if t is None:
        return None
    tr = t.transform
    return tr.translation.x, tr.translation.y, se2.yaw_of(tr.rotation)


def lookup_stamp(buf, target: str, source: str) -> float | None:
    """The stamp (s) of the latest `source` -> `target` transform, or None."""
    t = lookup(buf, target, source)
    if t is None:
        return None
    return t.header.stamp.sec + t.header.stamp.nanosec * 1e-9
