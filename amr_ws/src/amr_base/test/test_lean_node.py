"""LeanNode (CPU, 2026-10-24): no default QoS event handlers, and every production node uses it.

The handlers only log an incompatible-QoS warning, but each is a waitable the
executor re-adds on every wakeup (1.81 -> 1.24 ms per callback for 14 subs +
6 pubs on the N97). Real rclpy on its own domain: nothing reaches the vehicle graph.
"""

from __future__ import annotations

import pathlib
import re

import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.node import Node  # noqa: E402
from rclpy.qos_event import PublisherEventCallbacks  # noqa: E402
from std_msgs.msg import Int32  # noqa: E402

from amr_base.lean_node import LeanNode  # noqa: E402

DOMAIN = 70
SRC = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def ctx():
    c = rclpy.Context()
    rclpy.init(context=c, domain_id=DOMAIN)
    yield c
    rclpy.try_shutdown(context=c)


def test_no_default_event_handlers(ctx, monkeypatch):
    monkeypatch.delenv("AMR_QOS_EVENTS", raising=False)
    plain = Node("plain_probe", context=ctx)
    lean = LeanNode("lean_probe", context=ctx)
    try:
        assert len(plain.create_publisher(Int32, "/p", 1).event_handlers) == 1, "rclpy default changed?"
        assert len(plain.create_subscription(Int32, "/p", lambda _m: None, 1).event_handlers) == 1
        assert lean.create_publisher(Int32, "/p", 1).event_handlers == []
        assert lean.create_subscription(Int32, "/p", lambda _m: None, 1).event_handlers == []
        assert lean.create_subscription(Int32, "/p", lambda _m: None, 1, raw=True).raw, "kwargs pass through"
    finally:
        plain.destroy_node()
        lean.destroy_node()


def test_explicit_callbacks_and_the_debug_switch_keep_them(ctx, monkeypatch):
    lean = LeanNode("lean_probe", context=ctx)
    try:
        own = PublisherEventCallbacks(incompatible_qos=lambda _e: None)
        assert len(lean.create_publisher(Int32, "/p", 1, event_callbacks=own).event_handlers) == 1
        monkeypatch.setenv("AMR_QOS_EVENTS", "1")
        assert len(lean.create_publisher(Int32, "/p", 1).event_handlers) == 1
        assert len(lean.create_subscription(Int32, "/p", lambda _m: None, 1).event_handlers) == 1
    finally:
        lean.destroy_node()


def test_every_production_node_is_lean():
    """A new node written as `class X(Node)` would quietly bring the handlers back."""
    plain = []
    for f in sorted(SRC.glob("amr_*/amr_*/*.py")):
        if f.parts[-3] == "amr_sim" or f.name == "lean_node.py":
            continue  # sim nodes model the vehicle's I/O, not its CPU
        found = re.findall(r"^class \w+\((?:\w+\.)*Node\):", f.read_text(), re.M)
        plain += [f"{f.relative_to(SRC)}: {m}" for m in found]
    assert not plain, "use amr_base.lean_node.LeanNode:\n" + "\n".join(plain)
    lean = [f for f in SRC.glob("amr_*/amr_*/*.py") if "(LeanNode):" in f.read_text()]
    assert len(lean) >= 15, f"expected the 15 production nodes, found {len(lean)}"


class _Node:
    def __init__(self, log):
        self.log = log

    def destroy_node(self):
        self.log.append("destroy")


def _fake_rclpy(monkeypatch, log, spin_raises=None, ok=False):
    import rclpy

    monkeypatch.setattr(rclpy, "init", lambda args=None: log.append("init"))
    monkeypatch.setattr(rclpy, "ok", lambda: ok)
    monkeypatch.setattr(rclpy, "try_shutdown", lambda: log.append("shutdown"))

    def spin(node):
        log.append("spin")
        if spin_raises is not None:
            raise spin_raises

    monkeypatch.setattr(rclpy, "spin", spin)


def test_run_tears_down_in_order_before_destroy_first(monkeypatch):
    """D10: drive_node disarms in before_destroy; it must come before destroy_node."""
    from amr_base.lean_node import run

    log = []
    _fake_rclpy(monkeypatch, log, spin_raises=KeyboardInterrupt())
    run(lambda: _Node(log), before_destroy=lambda n: log.append("before"))
    assert log == ["init", "spin", "before", "destroy", "shutdown"]


def test_run_destroys_even_when_before_destroy_raises(monkeypatch):
    import pytest

    from amr_base.lean_node import run

    log = []
    _fake_rclpy(monkeypatch, log, spin_raises=KeyboardInterrupt())

    def boom(n):
        raise ValueError("teardown")

    with pytest.raises(ValueError):
        run(lambda: _Node(log), before_destroy=boom)
    assert log[-2:] == ["destroy", "shutdown"]


def test_run_swallows_a_teardown_runtime_error_only_once_rclpy_is_down(monkeypatch):
    import pytest

    from amr_base.lean_node import run

    log = []
    _fake_rclpy(monkeypatch, log, spin_raises=RuntimeError("Unable to convert call argument"), ok=False)
    run(lambda: _Node(log))  # context already down: swallowed
    _fake_rclpy(monkeypatch, log, spin_raises=RuntimeError("real"), ok=True)
    with pytest.raises(RuntimeError):
        run(lambda: _Node(log))
    _fake_rclpy(monkeypatch, log, spin_raises=RuntimeError("real"), ok=False)
    with pytest.raises(RuntimeError):
        run(lambda: _Node(log), catch_runtime=False)


def test_ui_throttle_publishes_the_first_then_one_per_period():
    from amr_base.lean_node import UiThrottle

    t = UiThrottle(0.2)
    got = [t.due(x) for x in (100.0, 100.1, 100.19, 100.2, 100.25, 100.41)]
    assert got == [True, False, False, True, False, True]
