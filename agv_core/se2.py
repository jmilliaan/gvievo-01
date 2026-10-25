"""Planar pose math shared by the ROS nodes, the web adapter and the tests.

Poses are (x, y, yaw) tuples in metres and radians. Pure standard library.
"""
import math


def wrap(a):
    """An angle into (-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))


def compose(frame, pose):
    """`pose`, expressed in `frame`'s child, returned in `frame`'s parent (yaw wrapped)."""
    fx, fy, fyaw = frame
    px, py, pyaw = pose
    c, s = math.cos(fyaw), math.sin(fyaw)
    return fx + c * px - s * py, fy + s * px + c * py, wrap(fyaw + pyaw)


def yaw_of(q):
    """Yaw of a quaternion with .x .y .z .w (the full formula: exact for a planar one too)."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def quat_zw(yaw):
    """(z, w) of the planar quaternion for `yaw`."""
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def correction_at(before, after, at):
    """How far a parent->child transform change moved a pose `at` (in the child frame),
    measured at that pose: (metres, |radians|). The map->odom correction AT the vehicle."""
    a, b = compose(before, at), compose(after, at)
    return math.hypot(b[0] - a[0], b[1] - a[1]), abs(wrap(b[2] - a[2]))
