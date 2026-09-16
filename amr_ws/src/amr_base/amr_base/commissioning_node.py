"""commissioning_node (unified plan §7.2): the /blind replacement.

    /amr/commissioning/plan   PlanCommissioning   validate + hold a plan (moves nothing)
    /amr/commissioning/clear  Trigger             drop the plan / abort a running job
    /amr/commissioning_state  CommissioningState  latched, on change + 2 Hz
    /amr/commissioning_wheels WheelVelocities     per-wheel setpoints while a job runs,
                                                  to the mux's COMMISSIONING source

A job executes only on a fresh physical Start edge under a valid MANUAL panel
while the supervisor's lease carries the COMMISSIONING class (the supervisor
grants that - and withholds MANUAL - while this node reports PREPARED/RUNNING).
Every tick re-checks that authority; the mux and drive owner gate the output
again on their own. Evidence goes to <state_dir>/commissioning/<plan>-<ts>.json.
"""

from __future__ import annotations

import json
import os
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu
from std_srvs.srv import Trigger

from amr_base import commissioning as cj
from amr_interfaces.msg import CommissioningState, ControlLease, PanelState, WheelStates, WheelVelocities
from amr_interfaces.srv import PlanCommissioning

RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
SENSOR = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)


class CommissioningNode(Node):
    def __init__(self) -> None:
        super().__init__("commissioning_node")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("state_dir", os.path.expanduser("~/.amr"))
        self.declare_parameter("counts_fresh_s", 0.1)
        self.declare_parameter("still_wheel_rad_s", 0.02)
        p = self.get_parameter
        self.dt = 1.0 / float(p("rate_hz").value)
        self.evidence_dir = os.path.join(os.path.expanduser(str(p("state_dir").value)), "commissioning")
        self.counts_fresh = float(p("counts_fresh_s").value)
        self.still_thr = float(p("still_wheel_rad_s").value)
        self.job = cj.Job()
        self._wheels = None
        self._wheels_t = None
        self._panel = None
        self._panel_t = None
        self._start_edge = False
        self._lease = None
        self._lease_t = None
        self._gyro = None
        self._generation = 0
        self._last_phase = None
        self._seq = 0
        self.create_subscription(WheelStates, "/wheel_states", self._on_wheels, SENSOR)
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10)
        self.create_subscription(ControlLease, "/amr/control_lease", self._on_lease, RELIABLE_1)
        self.create_subscription(Imu, "/imu/data", self._on_imu, SENSOR)
        self._pub_cmd = self.create_publisher(WheelVelocities, "/amr/commissioning_wheels", RELIABLE_1)
        self._pub_state = self.create_publisher(CommissioningState, "/amr/commissioning_state", LATCHED)
        self.create_service(PlanCommissioning, "/amr/commissioning/plan", self._srv_plan)
        self.create_service(Trigger, "/amr/commissioning/clear", self._srv_clear)
        self.create_timer(self.dt, self._tick)
        self.create_timer(0.5, self._publish_state)
        self._t_last = time.monotonic()
        self.get_logger().info(f"commissioning idle; evidence -> {self.evidence_dir}")

    # -- inputs --

    def _on_wheels(self, m: WheelStates) -> None:
        self._wheels, self._wheels_t = m, time.monotonic()

    def _on_panel(self, m: PanelState) -> None:
        self._panel, self._panel_t = m, time.monotonic()
        if m.start_edge:
            self._start_edge = True  # consumed by exactly one tick

    def _on_lease(self, m: ControlLease) -> None:
        self._lease, self._lease_t = m, time.monotonic()
        self._generation = int(m.generation)

    def _on_imu(self, m: Imu) -> None:
        self._gyro = float(m.angular_velocity.z)

    # -- services (never move anything) --

    def _srv_plan(self, req, res):
        w = self._wheels
        cpr = float(w.counts_per_wheel_rev) if w is not None else 0.0
        try:
            res.planned_json = self.job.plan(req.plan_json, cpr)
        except ValueError as e:
            res.ok, res.message = False, str(e)
            return res
        res.ok, res.message = True, f"plan {self.job.plan_id} held: press physical Start under MANUAL to run"
        self.get_logger().info(res.message)
        self._publish_state()
        return res

    def _srv_clear(self, req, res):
        was_active = self.job.phase in (cj.RUNNING, cj.SETTLING)
        self.job.clear()
        if was_active:
            self._publish_wheels(0.0, 0.0)
        res.success, res.message = True, "cleared"
        self._publish_state()
        return res

    # -- the tick --

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._t_last = now - self._t_last, now
        w = self._wheels
        fresh = w is not None and self._wheels_t is not None and now - self._wheels_t <= self.counts_fresh
        counts = (int(w.left_counts), int(w.right_counts)) if fresh and w.counts_valid else None
        stopped = None
        if fresh:
            stopped = abs(w.left_vel_rad_s) <= self.still_thr and abs(w.right_vel_rad_s) <= self.still_thr
        panel_ok = self._panel is not None and self._panel_t is not None and now - self._panel_t <= 0.2
        lease_ok = self._lease is not None and self._lease_t is not None and now - self._lease_t <= 0.3
        start_edge, self._start_edge = self._start_edge, False
        inputs = cj.Inputs(
            now=now,
            dt=min(dt, 5 * self.dt),
            counts=counts,
            counts_per_rev=float(w.counts_per_wheel_rev) if w is not None else 0.0,
            stopped=stopped,
            panel_valid=bool(panel_ok and self._panel.valid),
            panel_manual=bool(panel_ok and not self._panel.mode_auto),
            start_edge=start_edge,
            lease_allowed=int(self._lease.allowed) if lease_ok else 0,
            gyro_yaw_rad_s=self._gyro,
        )
        before = self.job.phase
        wl, wr = self.job.tick(inputs)
        if self.job.phase in (cj.RUNNING, cj.SETTLING):
            self._publish_wheels(wl, wr)
        elif before in (cj.RUNNING, cj.SETTLING):
            # Do not leave the previous nonzero sample live until the mux's
            # freshness timeout when a job completes or loses authority.
            self._publish_wheels(0.0, 0.0)
        if self.job.phase != before:
            a, b = cj.PHASE_NAMES[before], cj.PHASE_NAMES[self.job.phase]
            self.get_logger().info(f"commissioning {a} -> {b} {self.job.reason}")
            if self.job.phase in (cj.DONE, cj.ABORTED):
                self._write_evidence()
            self._publish_state()

    def _publish_wheels(self, left: float, right: float) -> None:
        m = WheelVelocities()
        m.header.stamp = self.get_clock().now().to_msg()
        m.generation = self._generation
        m.left_rad_s, m.right_rad_s = float(left), float(right)
        self._pub_cmd.publish(m)

    def _write_evidence(self) -> None:
        try:
            os.makedirs(self.evidence_dir, exist_ok=True)
            path = os.path.join(
                self.evidence_dir, f"{self.job.plan_id}-{time.strftime('%Y%m%d-%H%M%S')}.json"
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.job.evidence({"generation": self._generation}), f, indent=1)
            self._results_path = path
        except OSError as e:
            self.get_logger().error(f"evidence not written: {e}")

    _results_path = ""

    def _publish_state(self) -> None:
        s = self.job.snapshot()
        m = CommissioningState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.phase = self.job.phase
        m.generation = self._generation
        m.plan_id = s.get("plan_id", "")
        m.segment = int(s.get("segment", 0))
        m.segments = int(s.get("segments", 0))
        m.kind = str(s.get("kind", ""))
        prog = s.get("progress_m", [0.0, 0.0])
        m.progress_left_m, m.progress_right_m = float(prog[0]), float(prog[1])
        m.speed_mps = float(s.get("speed_mps", 0.0))
        pose = s.get("pose", {})
        m.pose_x_m, m.pose_y_m, m.heading_deg = (
            float(pose.get("x_m", 0.0)),
            float(pose.get("y_m", 0.0)),
            float(pose.get("heading_deg", 0.0)),
        )
        m.gyro_heading_deg = float(s.get("gyro_heading_deg", 0.0))
        m.completed = int(s.get("completed", 0))
        m.reason = str(s.get("reason", "") or "")
        m.results_path = self._results_path if self.job.phase in (cj.DONE, cj.ABORTED) else ""
        self._pub_state.publish(m)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CommissioningNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
