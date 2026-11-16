"""event_recorder_node: /amr/events + /amr/device_health -> <state_dir>/logs/recorded_events.jsonl
(unified plan WP-H3, hardening plan H-P1-15). The decisions are amr_base.event_recorder's.

Motion authority: none. It subscribes, appends to a file, and publishes only its own
EVENTLOG_WRITE_FAILED edge on /amr/events and a 1 Hz /diagnostics status. Launched in base,
respawning, not required: losing the recorder loses forensics, never motion.

Every /amr/events publisher (drive_node, panel_node, cmd_mux, trolley_node, supervisor, line
follow, localization monitor, mapping session, route executor, station_bridge) offers
RELIABLE + VOLATILE, so one RELIABLE + VOLATILE subscription with a deep queue hears them all;
TRANSIENT_LOCAL here would refuse every one of them (test_event_recorder pins both).
"""

from __future__ import annotations

import time

from agv_core import health, paths
from agv_core.eventlog import EventLog
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy

from amr_base import event_recorder as er
from amr_base import health_pub, wire
from amr_base.lean_node import LeanNode, run
from amr_base.qos import EVENT_STREAM
from amr_interfaces.msg import Event

try:
    from amr_interfaces.msg import DeviceHealth
except ImportError:  # amr_interfaces not rebuilt yet: events only
    DeviceHealth = None

# Deeper than any publisher's 50: a burst from several nodes at once (a bus loss) must not
# drop the first lines, which are the ones that explain it.
RECORD_QOS = QoSProfile(
    depth=200, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)


class EventRecorder(LeanNode):
    def __init__(self) -> None:
        super().__init__("event_recorder", start_parameter_services=False)  # WP-C11: nobody sets params live
        self.declare_parameter("state_dir", paths.state_dir())
        self.rec = er.Recorder(EventLog(er.path_in(str(self.get_parameter("state_dir").value))))
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._pub_diag = self.create_publisher(DiagnosticArray, "/diagnostics", 5)
        self.create_subscription(Event, "/amr/events", self._on_event, RECORD_QOS)
        if DeviceHealth is not None:
            self.create_subscription(DeviceHealth, health_pub.TOPIC, self._on_health, EVENT_STREAM)
        else:
            self.get_logger().warn("no DeviceHealth (amr_interfaces not rebuilt): recording events only")
        self.create_timer(1.0, self._diag)
        self.get_logger().info(f"recording /amr/events to {self.rec.log.path}")

    def _on_event(self, m: Event) -> None:
        self._report(self.rec.record(er.event_row(time.time(), m.source, m.level, m.code, m.text, m.seq)))

    def _on_health(self, m) -> None:
        device = wire.HEALTH_DEVICE_NAMES.get(int(m.device), f"device {int(m.device)}")
        state = wire.HEALTH_STATE_NAMES.get(int(m.state), health.LOST)
        self._report(self.rec.health(time.time(), device, state, m.code, m.detail))

    def _report(self, edge) -> None:
        if edge is None:
            return
        level, code, text = edge
        (self.get_logger().warn if level else self.get_logger().info)(f"{code}: {text}")
        self._pub_event.publish(self.build_event(er.SOURCE, level, code, text))

    def _diag(self) -> None:
        arr = DiagnosticArray()
        arr.header.stamp = self.get_clock().now().to_msg()
        st = DiagnosticStatus(name="eventlog/recorder", hardware_id=self.rec.log.path)
        st.level = DiagnosticStatus.ERROR if self.rec.failing else DiagnosticStatus.OK
        st.message = "write failing" if self.rec.failing else "recording"
        st.values = [
            KeyValue(key="recorded", value=str(self.rec.recorded)),
            KeyValue(key="write_errors", value=str(self.rec.log.errors)),
            KeyValue(key="path", value=self.rec.log.path),
        ]
        arr.status.append(st)
        self._pub_diag.publish(arr)


def main() -> None:
    run(EventRecorder)


if __name__ == "__main__":
    main()
