"""amr_base.tfpose: a TF lookup as a pose, None on any failure (lean plan D71)."""

import math
from types import SimpleNamespace as NS

from agv_core import se2

from amr_base import tfpose


class Buffer:
    def __init__(self, transforms):
        self.transforms, self.asked = transforms, []

    def lookup_transform(self, target, source, time):
        self.asked.append((target, source, time))
        t = self.transforms.get((target, source))
        if t is None:
            raise LookupError(f"{source} -> {target}")
        return t


def _tf(x, y, q, sec=12, nanosec=500_000_000):
    stamp = NS(sec=sec, nanosec=nanosec)
    return NS(transform=NS(translation=NS(x=x, y=y), rotation=q), header=NS(stamp=stamp))


def test_a_missing_transform_is_none_not_an_error():
    buf = Buffer({})
    assert tfpose.lookup_pose(buf, "map", "odom", time=0) is None
    assert tfpose.lookup(buf, "map", "odom", time=0) is None


def test_planar_and_rolled_yaw_and_the_stamp():
    z, w = se2.quat_zw(0.4)
    cr, sr = math.cos(0.2), math.sin(0.2)  # a 0.4 rad roll composed with the yaw
    buf = Buffer({("map", "odom"): _tf(1.0, 2.0, NS(x=0.0, y=0.0, z=z, w=w)),
                  ("odom", "base_footprint"): _tf(3.0, 4.0, NS(w=w * cr, x=w * sr, y=z * sr, z=z * cr))})
    x, y, yaw = tfpose.lookup_pose(buf, "map", "odom", time=0)
    assert (x, y) == (1.0, 2.0) and math.isclose(yaw, 0.4)
    assert math.isclose(tfpose.lookup_pose(buf, "odom", "base_footprint", time=0)[2], 0.4, abs_tol=1e-9)
    assert buf.asked[0] == ("map", "odom", 0)
    assert tfpose.lookup_stamp(buf, "map", "odom") == 12.5  # latest: rclpy Time()
