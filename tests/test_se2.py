"""agv_core.se2: the planar pose math the nodes share (lean plan D20)."""
import math
from types import SimpleNamespace

from helpers import check

from agv_core import se2


def test_se2():
    print("\nse2: wrap, compose, yaw of a quaternion, correction at the vehicle")
    check("wrap keeps (-pi, pi] and folds the rest",
          se2.wrap(math.pi) == math.pi and abs(se2.wrap(3 * math.pi) - math.pi) < 1e-12
          and abs(se2.wrap(-math.pi / 2 - 2 * math.pi) + math.pi / 2) < 1e-12)
    x, y, yaw = se2.compose((1.0, 2.0, math.pi / 2), (1.0, 0.0, math.pi))
    check("compose rotates the child pose into the parent and wraps the yaw",
          abs(x - 1.0) < 1e-12 and abs(y - 3.0) < 1e-12 and abs(yaw + math.pi / 2) < 1e-12,
          f"{x:.3f} {y:.3f} {yaw:.3f}")
    z, w = se2.quat_zw(0.7)
    planar = SimpleNamespace(x=0.0, y=0.0, z=z, w=w)
    # A 30 deg roll about x composed with 0.7 rad of yaw keeps the yaw.
    cr, sr = math.cos(math.radians(15)), math.sin(math.radians(15))
    rolled = SimpleNamespace(w=w * cr, x=w * sr, y=z * sr, z=z * cr)
    check("yaw_of reads a planar quaternion and a rolled one alike",
          abs(se2.yaw_of(planar) - 0.7) < 1e-12 and abs(se2.yaw_of(rolled) - 0.7) < 1e-9,
          f"{se2.yaw_of(rolled):.6f}")
    m, rad = se2.correction_at((0.0, 0.0, 0.0), (0.0, 0.0, math.radians(0.5)), (20.0, 0.0, 0.0))
    check("a 0.5 deg map->odom turn moves a vehicle 20 m out by ~0.17 m",
          abs(m - 20.0 * math.radians(0.5)) < 1e-4 and abs(rad - math.radians(0.5)) < 1e-12, f"{m:.4f}")


TESTS = [test_se2]
