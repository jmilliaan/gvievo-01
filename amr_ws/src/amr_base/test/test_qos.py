"""amr_base.qos: each shared profile pinned (lean plan D07). A drifted copy fails silently
on the wire (no connection, and LeanNode hides the incompatible-QoS log), so here it fails loudly."""

import pytest

qos = pytest.importorskip("rclpy.qos")

from amr_base import qos as profiles  # noqa: E402

R, BE = qos.QoSReliabilityPolicy.RELIABLE, qos.QoSReliabilityPolicy.BEST_EFFORT
V, TL = qos.QoSDurabilityPolicy.VOLATILE, qos.QoSDurabilityPolicy.TRANSIENT_LOCAL


@pytest.mark.parametrize(
    "name, depth, reliability, durability",
    [("SENSOR_DATA", 5, BE, V), ("RELIABLE_1", 1, R, V), ("LATCHED", 1, R, TL), ("EVENT_STREAM", 50, R, V)],
)
def test_profile(name, depth, reliability, durability):
    p = getattr(profiles, name)
    assert (p.depth, p.reliability, p.durability) == (depth, reliability, durability)
    assert p.history == qos.QoSHistoryPolicy.KEEP_LAST


def test_the_mux_and_drive_node_use_the_shared_profiles():
    from amr_base import cmd_mux_kinematics_node as mux
    from amr_base import drive_node

    assert mux.LATCHED is profiles.LATCHED and mux.RELIABLE_1 is profiles.RELIABLE_1
    assert drive_node.MARKER_QOS is profiles.EVENT_STREAM and drive_node.SENSOR_DATA is profiles.SENSOR_DATA
