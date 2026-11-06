"""trolley_node: /rear/scan, /rear/output_paths -> /amr/rear/trolley (station call plan 11.3).

Motion authority: none. It reports a state, and FollowJob reads it as an interlock. The decisions are
in amr_base.trolley_detect. Launched only with rear.source "scanner". Respawning, not required.

Frozen scans: the driver's scan counter is on raw_data only, a big message at the scan rate. A
real scanner never repeats 1000 float ranges bit for bit, so the bytes of `ranges` serve as the
counter. A repeat reads UNKNOWN, which is the safe side. Confirm at P8 that an open floor does not
repeat (every beam at no return would).
"""

from __future__ import annotations

import time

from agv_core import alarms
from agv_core import config as vehicle_config
from sensor_msgs.msg import LaserScan

from amr_base import trolley_detect as td
from amr_base.lean_node import LeanNode, run
from amr_base.qos import RELIABLE_1, SENSOR_DATA
from amr_interfaces.msg import Event, TrolleyState

try:
    from sick_safetyscanners2_interfaces.msg import OutputPaths
except ImportError:  # pragma: no cover - present on the vehicle
    OutputPaths = None


class TrolleyNode(LeanNode):
    def __init__(self) -> None:
        super().__init__("trolley_node")
        self.detect = td.TrolleyDetect(td.Params.from_profile(vehicle_config))
        self.field = td.RearField(
            vehicle_config.FRESH_FIELD_S,
            vehicle_config.REAR_FIELD_OUTPUT_INDEX,
            vehicle_config.REAR_NO_TROLLEY_CASE,
            vehicle_config.REAR_CASE_PROVEN,
        )
        self.create_subscription(LaserScan, "/rear/scan", self._on_scan, SENSOR_DATA)
        if OutputPaths is not None:
            self.create_subscription(OutputPaths, "/rear/output_paths", self._on_paths, SENSOR_DATA)
        else:
            self.get_logger().error(
                "sick_safetyscanners2_interfaces is not installed: the rear field stays UNKNOWN"
            )
        self._pub = self.create_publisher(TrolleyState, "/amr/rear/trolley", RELIABLE_1)
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._silent = False
        self._last = None
        self.create_timer(0.1, self._tick)

    def _on_scan(self, m: LaserScan) -> None:
        r = m.ranges
        self.detect.scan(
            time.monotonic(),
            r,
            m.angle_min,
            m.angle_increment,
            m.range_min,
            m.range_max,
            counter=hash(r.tobytes()) if hasattr(r, "tobytes") else hash(tuple(r)),
        )

    def _on_paths(self, m) -> None:
        self.field.update(
            time.monotonic(), getattr(m, "status", None), getattr(m, "active_monitoring_case", None)
        )

    def _tick(self) -> None:
        now = time.monotonic()
        state = self.detect.tick(now)
        rear_field, rear_case = self.field.read(now)
        m = TrolleyState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.state, m.rear_field, m.rear_case = state, rear_field, rear_case
        m.roi_points = min(int(self.detect.points), 65535)
        m.detail = self.detect.detail
        self._pub.publish(m)
        silent = state == td.UNKNOWN and bool(self.detect.detail)
        if silent != self._silent:
            self._silent = silent
            if silent:
                code = "REAR_SCANNER_SILENT"
                self._pub_event.publish(
                    self.build_event("trolley_node", alarms.level(code), code, self.detect.detail)
                )
        if (state, rear_field) != self._last:
            self._last = (state, rear_field)
            self.get_logger().info(f"trolley {state} rear field {rear_field} case {rear_case}: {m.detail}")


def main() -> None:
    run(TrolleyNode)


if __name__ == "__main__":
    main()
