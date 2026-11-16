"""H-P3-2 sim fault hooks (WP-T2): the pure switch and script behind every fake's ~/mute, ~/freeze."""

import ast
import os

from amr_sim import fault_hooks as fh

PKG = os.path.join(os.path.dirname(__file__), "..", "amr_sim")


class Msg:
    def __init__(self, v):
        self.v = v


def test_mute_publishes_nothing_and_freeze_repeats_the_first_frozen_content():
    h = fh.Hooks()
    assert h.out(0.0, Msg(1)).v == 1
    h.set(fh.MUTE, True)
    assert h.out(0.1, Msg(2)) is None
    h.set(fh.MUTE, False)
    h.set(fh.FREEZE, True)
    a = h.out(0.2, Msg(3))
    b = h.out(0.3, Msg(4))
    assert a.v == 3 and b is a  # content held; the node stamps it fresh each time
    h.set(fh.FREEZE, False)
    assert h.out(0.4, Msg(5)).v == 5
    h.set(fh.FREEZE, True)
    assert h.out(0.5, Msg(6)).v == 6  # a new freeze holds the content of its own moment


def test_the_script_timeline():
    s = fh.Script(start_delay_s=1.0, dropout_at_s=5.0, dropout_s=2.0, freeze_after_s=10.0, drop_after_s=20.0)
    assert [s.mode(t) for t in (0.5, 1.0, 4.9, 5.0, 6.9, 7.0, 10.0, 19.9, 20.0)] == [
        fh.MUTE, fh.OK, fh.OK, fh.MUTE, fh.MUTE, fh.OK, fh.FREEZE, fh.FREEZE, fh.MUTE,
    ]
    assert fh.Script().mode(1e6) == fh.OK  # every value 0 = off
    h = fh.Hooks(fh.Script(drop_after_s=1.0))
    h.set(fh.FREEZE, True)
    assert h.mode(2.0) == fh.FREEZE  # the services win over the script
    h.set(fh.MUTE, True)
    assert h.mode(0.0) == fh.MUTE  # the services win over the script


def test_script_from_reads_the_declared_parameter_names():
    vals = {"start_delay_s": 1.0, "drop_after_s": 2.0, "freeze_after_s": 3.0, "dropout_at_s": 4.0,
            "dropout_s": 5.0}
    s = fh.script_from(vals.__getitem__)
    assert (s.start_delay_s, s.drop_after_s, s.freeze_after_s, s.dropout_at_s, s.dropout_s) == (1, 2, 3, 4, 5)


def test_decimation_for_a_slow_mls():
    assert fh.decimation(100.0, 0.0) == 1 and fh.decimation(100.0, 200.0) == 1
    assert fh.decimation(100.0, 25.0) == 4 and fh.decimation(100.0, 30.0) == 3


def _services(name):
    tree = ast.parse(open(os.path.join(PKG, name), encoding="utf-8").read())
    return {c.args[1].value for c in ast.walk(tree)
            if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "create_service"
            and isinstance(c.args[1], ast.Constant)}


def test_every_hooked_fake_offers_mute_and_freeze():
    for name in ("fake_base_node.py", "fake_panel_node.py", "fake_imu_node.py", "tape_synth_node.py"):
        assert {"~/mute", "~/freeze"} <= _services(name), name
    assert {"~/fault", "~/wheels_invalid", "~/drive_silent"} <= _services("fake_base_node.py")
    assert "~/invalid" in _services("fake_panel_node.py")


def test_the_fake_base_watchdog_is_the_drive_nodes():
    """H-P3-2: cmd_timeout_s 0.25 -> 0.2, the vehicle's (drive_node treats > 0.2 s as zero)."""
    tree = ast.parse(open(os.path.join(PKG, "fake_base_node.py"), encoding="utf-8").read())
    got = [c.args[1].value for c in ast.walk(tree)
           if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "declare_parameter"
           and isinstance(c.args[0], ast.Constant) and c.args[0].value == "cmd_timeout_s"]
    assert got == [0.2]


def _node_name(name):
    tree = ast.parse(open(os.path.join(PKG, name), encoding="utf-8").read())
    return next(c.args[0].value for c in ast.walk(tree)
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "__init__"
                and c.args and isinstance(c.args[0], ast.Constant))


def test_every_hook_the_dropout_sim_calls_exists():
    """WP-T3: the opt-in cases (amr_bringup test_fault_injection_sim, which needs ROS) call fault hooks
    by service name. Checked here, without ROS, so a renamed hook fails on every run, not once per
    milestone on the vehicle. The node names are the fakes' own (the launch keeps them)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "amr_bringup", "test",
                        "test_fault_injection_sim.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    hooks = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "HOOKS")
    nodes = {_node_name(f): f for f in ("fake_base_node.py", "fake_panel_node.py", "fake_imu_node.py",
                                        "tape_synth_node.py")}
    assert hooks
    for topic in hooks.values():
        node, srv = topic.strip("/").split("/")
        assert node in nodes, topic
        assert f"~/{srv}" in _services(nodes[node]), topic
