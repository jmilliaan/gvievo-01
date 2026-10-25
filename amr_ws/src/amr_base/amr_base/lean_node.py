"""LeanNode: an rclpy Node without the default QoS event handlers (CPU, 2026-10-24).

rclpy attaches an incompatible-QoS event handler to every publisher and
subscription unless told otherwise. Each one is a waitable that the executor
re-adds to its wait set on every wakeup, so the cost scales with entities x
wakeups. Measured on the N97 (Humble, CycloneDDS, 100 Hz input): a node with
14 subscriptions + 6 publishers paid 1.81 ms per callback with them, 1.24 ms
without; across the stack that was roughly half a core.

All the default handlers do is log "New publisher discovered ... offering
incompatible QoS" once. A mismatch they would have reported still shows as the
data never arriving, which every consumer already treats as stale (zero
command, not ready). AMR_QOS_EVENTS=1 restores them for a debugging session.
A call that passes its own event_callbacks keeps them as given.
"""

from __future__ import annotations

import os

from rclpy.node import Node
from rclpy.qos_event import PublisherEventCallbacks, SubscriptionEventCallbacks

# The _ui display copies (/wheel_states_ui, /amr/line_track_ui, /amr/panel_state_ui):
# what the web subscribes to instead of the 50-100 Hz topics.
UI_PERIOD_S = 0.2  # wheels, line track
UI_PERIOD_FAST_S = 0.1  # the panel (a button press should show at once)


class UiThrottle:
    """At most one display copy per `period` s. Pure and clock-fed: due(now) says whether
    to publish this one, and starts the next period when it does."""

    def __init__(self, period: float = UI_PERIOD_S) -> None:
        self.period, self._t = float(period), None

    def due(self, now: float) -> bool:
        if self._t is not None and now - self._t < self.period:
            return False
        self._t = now
        return True


def _default_events() -> bool:
    return os.environ.get("AMR_QOS_EVENTS", "") == "1"


class LeanNode(Node):
    def create_publisher(self, *args, event_callbacks: PublisherEventCallbacks | None = None, **kwargs):
        if event_callbacks is None and not _default_events():
            event_callbacks = PublisherEventCallbacks(use_default_callbacks=False)
        return super().create_publisher(*args, event_callbacks=event_callbacks, **kwargs)

    def create_subscription(
        self, *args, event_callbacks: SubscriptionEventCallbacks | None = None, **kwargs
    ):
        if event_callbacks is None and not _default_events():
            event_callbacks = SubscriptionEventCallbacks(use_default_callbacks=False)
        return super().create_subscription(*args, event_callbacks=event_callbacks, **kwargs)

    def build_event(self, source: str, level: int, code: str, text: str):
        """An operator Event stamped now, with this node's next sequence number. The
        caller publishes it (each node keeps its own publish-safety rule)."""
        from amr_interfaces.msg import Event  # noqa: PLC0415

        m = Event()
        m.header.stamp = self.get_clock().now().to_msg()
        m.source, m.level, m.code, m.text = source, int(level), code, text
        self._event_seq = getattr(self, "_event_seq", 0) + 1
        m.seq = self._event_seq
        return m


def run(node_factory, args=None, before_destroy=None, catch_runtime=True, executor=None) -> None:
    """A node's whole life: init, spin until SIGINT or shutdown, then tear down in order.

    before_destroy(node) runs first in the teardown (drive_node disarms on its bus
    thread there, before the context goes away); the node is destroyed and rclpy shut
    down even if it raises. catch_runtime swallows the RuntimeError a callback raises
    from the C layer while launch tears the context down ("Unable to convert call
    argument"), but only once rclpy is no longer ok. executor: a factory such as
    lambda: MultiThreadedExecutor(num_threads=4); None spins single-threaded.
    """
    import rclpy  # noqa: PLC0415
    from rclpy.executors import ExternalShutdownException  # noqa: PLC0415

    rclpy.init(args=args)
    node = node_factory()
    try:
        if executor is None:
            rclpy.spin(node)
        else:
            ex = executor()
            ex.add_node(node)
            ex.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        if not catch_runtime or rclpy.ok():
            raise
    finally:
        try:
            if before_destroy is not None:
                before_destroy(node)
        finally:
            # launch sends SIGINT; the context may already be down by now, and
            # destroy_node() then raises from the C layer.
            try:
                node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
            rclpy.try_shutdown()
