"""A TF listener on its own lean node and thread (CPU, 2026-11-16, cpu-load plan §4a e).

/tf arrives at ~42 Hz (the EKF). A TransformListener on the node that does the real work
put every one of those messages through that node's executor, whose wakeup cost grows
with its entity count. Here the listener gets a node of its own: no parameter services,
no QoS event handlers, two subscriptions, spun by a SingleThreadedExecutor on a daemon
thread. The caller keeps the Buffer and reads it from its own thread; tf2's buffer core
locks internally, which is how TransformListener(spin_thread=True) uses it too.

use_global_arguments=False: launch's `__node:=` remap applies to every node in the
process, so without it this node would carry the main node's name. It needs no
parameters (the listener only fills the buffer) and no remaps.
"""

from __future__ import annotations

import threading


def start(buffer, name: str):
    """Fill `buffer` from /tf and /tf_static on node `name`, spun on a daemon thread.
    Returns (node, thread). rclpy's shutdown ends the spin; the thread never blocks exit."""
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor  # noqa: PLC0415
    from tf2_ros import TransformListener  # noqa: PLC0415

    from amr_base.lean_node import LeanNode  # noqa: PLC0415

    node = LeanNode(name, start_parameter_services=False, use_global_arguments=False)
    node._tf_listener = TransformListener(buffer, node)  # kept alive with the node
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin() -> None:
        try:
            executor.spin()
        except (ExternalShutdownException, RuntimeError):
            pass  # the context went down under us: the process is ending

    thread = threading.Thread(target=spin, name=f"{name}_spin", daemon=True)
    thread.start()
    return node, thread
