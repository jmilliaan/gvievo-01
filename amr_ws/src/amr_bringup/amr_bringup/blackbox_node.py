"""amr_blackbox_trigger: calls the black-box recorder's snapshot on a FAULT or stop edge (WP-P6).

    python3 -m amr_bringup.blackbox_node    (base.launch.py, blackbox:=true only)

Watches /amr/mode_state, /amr/line_state and /amr/events; blackbox.TriggerPolicy decides,
this node only calls /amr_blackbox/snapshot (rosbag2_interfaces/srv/Snapshot) and prunes old
files. Read-only and optional: it respawns, is never required(), and a missing recorder is a
log line, not a fault.
"""

from __future__ import annotations

import os
import time

from agv_core import paths

from amr_base.lean_node import LeanNode, run
from amr_base.qos import LATCHED
from amr_bringup import blackbox as bb
from amr_interfaces.msg import Event, LineState, ModeState


class BlackboxTrigger(LeanNode):
    def __init__(self) -> None:
        super().__init__("amr_blackbox_trigger", start_parameter_services=False)
        self.declare_parameter("state_dir", paths.state_dir())
        self.state_dir = os.path.expanduser(str(self.get_parameter("state_dir").value))
        self.policy = bb.TriggerPolicy()
        from rosbag2_interfaces.srv import Snapshot  # noqa: PLC0415 - rosbag2 only on the vehicle

        self._srv_type = Snapshot
        self._cli = self.create_client(Snapshot, bb.SNAPSHOT_SERVICE)
        self.create_subscription(ModeState, "/amr/mode_state", self._on_mode, LATCHED)
        self.create_subscription(LineState, "/amr/line_state", self._on_line, LATCHED)
        self.create_subscription(Event, "/amr/events", self._on_event, 50)
        self.create_steady_timer(0.5, self._tick)
        self._prune()

    def _on_mode(self, m) -> None:
        self.policy.observe_mode(time.monotonic(), int(m.mode), str(m.fault_code))

    def _on_line(self, m) -> None:
        self.policy.observe_line(time.monotonic(), int(m.state), str(m.hold_cause))

    def _on_event(self, m) -> None:
        self.policy.observe_event(time.monotonic(), int(m.level), str(m.code))

    def _tick(self) -> None:
        reasons = self.policy.due(time.monotonic())
        if not reasons:
            return
        if not self._cli.service_is_ready():
            self.get_logger().warn(f"black box not running; no snapshot for {', '.join(reasons)}")
            return
        self.get_logger().info(f"black box snapshot: {', '.join(reasons)}")
        fut = self._cli.call_async(self._srv_type.Request())
        fut.add_done_callback(self._done)

    def _done(self, fut) -> None:
        try:
            ok = bool(fut.result().success)
        except Exception as e:  # noqa: BLE001 - a failed snapshot is a log line
            self.get_logger().warn(f"black box snapshot failed: {e!r}")
            return
        if not ok:
            self.get_logger().warn("black box snapshot refused by the recorder")
        self._prune()

    def _prune(self) -> None:
        root = bb.root(self.state_dir)
        try:
            live = bb.newest_bag_dir(os.listdir(root))  # the running recorder's: never pruned
        except OSError:
            return  # nothing recorded yet
        protect = os.path.join(root, live) if live else ""
        for p in bb.prune_plan(bb.snapshot_files(self.state_dir), protect=protect):
            try:
                os.remove(p)
                d = os.path.dirname(p)
                if not any(n.endswith(".mcap") for n in os.listdir(d)):
                    for n in os.listdir(d):
                        os.remove(os.path.join(d, n))  # metadata.yaml of a pruned bag
                    os.rmdir(d)
            except OSError as e:
                self.get_logger().warn(f"black box prune {p}: {e!r}")


def main() -> None:
    run(BlackboxTrigger)


if __name__ == "__main__":
    main()
