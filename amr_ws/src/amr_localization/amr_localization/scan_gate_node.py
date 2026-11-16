"""/scan -> /scan_gated: the same scans, released only once odom->laser exists for
their stamp, and no faster than `min_period_s` (see scan_gate.py for why).

slam_toolbox, AMCL, the local costmap, the localization monitor and the route
executor read /scan_gated; only the web live view stays on raw /scan. Expired
scans are counted and logged, never published: a scan whose transform never
came is not the consumer's problem.

CPU (2026-11-16, cpu-load plan §4a d, e): /scan is taken and published as its raw
bytes, unchanged (scan_gate.cdr_header reads the stamp and frame); the TF listener runs
on its own lean node and thread (tf_thread); no parameter services.
"""

from rclpy.duration import Duration
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer

from amr_base.lean_node import LeanNode, run
from amr_base.qos import SENSOR_DATA
from amr_localization import tf_thread
from amr_localization.scan_gate import ScanGate, cdr_header


class ScanGateNode(LeanNode):
    def __init__(self) -> None:
        super().__init__("scan_gate", start_parameter_services=False)
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("min_period_s", 0.1)
        self.declare_parameter("settle_s", 0.02)
        self.declare_parameter("hold_max_s", 0.5)
        # 50 Hz (CPU, 2026-10-02; was 100): settle_s is already 20 ms, so a release is
        # at most one more poll period later. The timer runs only while a scan is pending
        # (CPU, 2026-10-24): an empty poll still cost a whole executor wakeup, 50 a second.
        self.declare_parameter("poll_period_s", 0.02)
        p = self.get_parameter
        self.odom_frame = p("odom_frame").value
        self.gate = ScanGate(
            min_period_s=p("min_period_s").value,
            settle_s=p("settle_s").value,
            hold_max_s=p("hold_max_s").value,
        )
        self.tf_buffer = Buffer(cache_time=Duration(seconds=5.0))
        self._tf_node, _ = tf_thread.start(self.tf_buffer, "scan_gate_tf")
        self._pub = self.create_publisher(LaserScan, "/scan_gated", SENSOR_DATA)
        self.create_subscription(LaserScan, "/scan", self._on_scan, SENSOR_DATA, raw=True)
        self._bad = 0  # raw scans whose header could not be read
        self._poll_timer = self.create_timer(p("poll_period_s").value, self._poll)
        self._poll_timer.cancel()  # armed by the first queued scan
        self.create_timer(30.0, self._report)
        self._reported_expired = 0

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_scan(self, raw: bytes) -> None:
        try:
            stamp, frame = cdr_header(raw)
        except ValueError as e:
            self._bad += 1
            if self._bad == 1:
                self.get_logger().error(f"unreadable /scan header, scan dropped: {e}")
            return
        self.gate.push(stamp, raw, self._now(), frame)  # the same bytes go out
        if self.gate.pending and self._poll_timer.is_canceled():
            self._poll_timer.reset()  # first poll one period from now, then every period

    def _poll(self) -> None:
        if not self.gate.pending:
            self._poll_timer.cancel()
            return

        def transformable(t: float) -> bool:
            # the frame of the scan being judged (the oldest), re-read per call: frames may change
            frame = self.gate.frame_of_oldest()
            return frame is not None and self.tf_buffer.can_transform(self.odom_frame, frame, Time(seconds=t))

        for raw in self.gate.poll(self._now(), transformable):
            self._pub.publish(raw)  # rclpy publishes bytes as an already-serialized message
        if not self.gate.pending:
            self._poll_timer.cancel()  # released or expired; the next scan re-arms it

    def _report(self) -> None:
        s = self.gate.stats
        new_expired = s.expired - self._reported_expired
        self._reported_expired = s.expired
        if new_expired:
            self.get_logger().warn(
                f"{new_expired} scans expired without an {self.odom_frame} transform in the last 30 s "
                f"(released {s.released}, thinned {s.thinned}, received {s.received})"
            )


def main() -> None:
    run(ScanGateNode, None, catch_runtime=False)


if __name__ == "__main__":
    main()
