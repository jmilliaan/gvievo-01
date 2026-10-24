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
