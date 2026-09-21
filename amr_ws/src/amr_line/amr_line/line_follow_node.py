"""line_follow_node (dual-product plan, Increment 1): magnetic-tape following.

    /amr/line/arm        Trigger            arm the layer (moves nothing)
    /amr/line/clear      Trigger            disarm / abort a running follow
    /amr/line_state      LineState          latched, on change + 1 Hz
    /amr/line_cmd        Twist              body command while following,
                                            to the mux's LINE source
    /amr/line_track      LineTrack  (in)    the MLS reading from drive_node

The vehicle follows only on a fresh physical Start edge, under a valid AUTO
panel, while the supervisor's lease carries LEASE_LINE - which it grants
EXCLUSIVELY in LINE mode, so no browser jog and no pendant can fight the tape.
Every tick re-checks that authority; the mux and the drive owner gate the
output again on their own.

*** The control law is not in this file. *** `amr_line.autopilot` is a
byte-for-byte port of the engine that ran this vehicle as a tape AGV, and
`amr_line.job` holds the authority state machine, ROS-free and unit-tested.
This node marshals messages, stamps freshness and owns the clock. Keep it that
way: the decisions worth testing must stay where a test can reach them without
a ROS graph.

*** Command shape: a body Twist, not per-wheel. *** The follower computes
(v, omega) internally and only converts to wheels at the end, so publishing
the body pair costs one exact round trip - kinematics.wheels_to_body and
body_to_wheels both apply the invert_left/invert_right rule, so it cancels -
and it puts LINE on the same accel path the mux already gives FOLLOW.
"""

from __future__ import annotations

import time

import rclpy
from agv_core import kinematics
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from std_srvs.srv import Trigger

from amr_interfaces.msg import (
    ControlLease,
    DriveStatus,
    LineState,
    LineTrack,
    ModeState,
    PanelState,
)
from amr_line import autopilot, runtime
from amr_line import job as lj
from amr_line import track as tk

try:
    # The protective field's real state comes from the SICK driver, the same
    # source and the same index the executor uses. Optional exactly as it is
    # there: the package is absent on a dev box, and a layer that cannot be
    # imported without the scanner driver cannot be unit-tested at all.
    from sick_safetyscanners2_interfaces.msg import OutputPaths
except ImportError:  # pragma: no cover - present on the vehicle
    OutputPaths = None

RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
SENSOR = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)

# The state machine's constants are LineState's constants. If a renumbering
# ever slips through, fail here at construction rather than let readiness.py's
# `line_state in (1, 2, 3)` quietly stop guarding a moving vehicle.
_WIRE = (
    (lj.IDLE, LineState.IDLE), (lj.ARMED, LineState.ARMED),
    (lj.RUNNING, LineState.RUNNING), (lj.HOLD, LineState.HOLD),
    (lj.DONE, LineState.DONE), (lj.FAULT, LineState.FAULT),
)


class LineFollowNode(Node):
    def __init__(self) -> None:
        super().__init__("line_follow_node")
        for mine, wire in _WIRE:
            if mine != wire:
                raise RuntimeError(
                    f"amr_line.job state {mine} does not match LineState {wire}: "
                    "readiness._line_active_locked depends on ARMED/RUNNING/HOLD "
                    "being 1..3. Fix the message or the module, not this check."
                )

        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("generation", 0)
        self.declare_parameter("v_max_mps", 0.30)
        self.declare_parameter("prereq_grace_s", 0.5)
        self.declare_parameter("auto_resume_clear_s", 2.0)
        self.declare_parameter("auto_resume_estop", False)
        self.declare_parameter("accept_sdo_track", False)
        self.declare_parameter("panel_fresh_s", 0.2)
        self.declare_parameter("lease_fresh_s", 0.3)
        self.declare_parameter("drives_fresh_s", 0.5)
        self.declare_parameter("field_output_index", 0)  # /output_paths status[i]

        self.dt = 1.0 / float(self.get_parameter("rate_hz").value)
        self._generation = int(self.get_parameter("generation").value)
        self.panel_fresh = float(self.get_parameter("panel_fresh_s").value)
        self.lease_fresh = float(self.get_parameter("lease_fresh_s").value)
        self.drives_fresh_s = float(self.get_parameter("drives_fresh_s").value)
        self.field_index = int(self.get_parameter("field_output_index").value)

        # The engine is handed its constants; it never reads a profile itself.
        runtime.load_from_profile()
        self.job = lj.FollowJob(
            autopilot.LineFollower(),
            prereq_grace_s=float(self.get_parameter("prereq_grace_s").value),
            auto_resume_clear_s=float(self.get_parameter("auto_resume_clear_s").value),
            auto_resume_estop=bool(self.get_parameter("auto_resume_estop").value),
            v_max_mps=float(self.get_parameter("v_max_mps").value),
        )
        self.reader = tk.TrackReader(
            timeout_s=runtime.SENSOR_TIMEOUT_S,
            min_hz=getattr(runtime, "LINE_MIN_TRACK_HZ", 40.0),
            accept_sdo=bool(self.get_parameter("accept_sdo_track").value),
        )

        self._panel = None
        self._panel_t = None
        self._start_edge_t = None
        self._reset_edge = False
        self._lease = None
        self._lease_t = None
        self._drives_t = None
        self._torque_off_msg = False
        self._field_clear = True
        self._t_last = time.monotonic()
        self._published_zero = True

        self.create_subscription(LineTrack, "/amr/line_track", self._on_track, SENSOR)
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10)
        self.create_subscription(ControlLease, "/amr/control_lease", self._on_lease, RELIABLE_1)
        self.create_subscription(ModeState, "/amr/mode_state", self._on_mode, LATCHED)
        self.create_subscription(DriveStatus, "/drives/status", self._on_drives, RELIABLE_1)
        if OutputPaths is not None:
            self.create_subscription(OutputPaths, "/output_paths", self._on_output_paths, SENSOR)
        else:
            self.get_logger().warning(
                "sick_safetyscanners2_interfaces is not installed: the protective "
                "field is assumed clear and only the drives' torque report can "
                "stop this layer. Do not run the vehicle like this."
            )

        self._pub_cmd = self.create_publisher(Twist, "/amr/line_cmd", RELIABLE_1)
        self._pub_state = self.create_publisher(LineState, "/amr/line_state", LATCHED)

        self.create_service(Trigger, "/amr/line/arm", self._srv_arm)
        self.create_service(Trigger, "/amr/line/clear", self._srv_clear)

        self.create_timer(self.dt, self._tick)
        self.create_timer(1.0, self._publish_state)
        self._publish_state()
        self.get_logger().info(
            f"line layer up, generation {self._generation}: "
            f"k_ratio={runtime.K_RATIO} kd={runtime.KD} "
            f"cap={self.job.v_max_mps} m/s rate floor={self.reader.min_hz} Hz"
        )

    # -- intake ------------------------------------------------------------
    def _on_track(self, m: LineTrack) -> None:
        self.reader.update(m, time.monotonic())

    def _on_panel(self, m: PanelState) -> None:
        self._panel, self._panel_t = m, time.monotonic()
        if m.start_edge:
            self._start_edge_t = time.monotonic()  # consumed by exactly one tick
        if m.reset_edge:
            self._reset_edge = True

    def _on_lease(self, m: ControlLease) -> None:
        cur = self._lease
        if cur is not None and cur.instance == m.instance:
            # Replayed or reordered leases never move authority backwards.
            if int(m.generation) < int(cur.generation):
                return
            if int(m.generation) == int(cur.generation) and int(m.seq) <= int(cur.seq):
                return
        self._lease, self._lease_t = m, time.monotonic()

    def _on_mode(self, m: ModeState) -> None:
        self._mode = m

    def _on_drives(self, m: DriveStatus) -> None:
        # torque off = not operational AND neither statusword says Operation enabled
        self._torque_off_msg = (
            not m.operational and "Operation enabled" not in (m.left_state, m.right_state)
        )
        self._drives_t = time.monotonic()

    def _on_output_paths(self, m) -> None:
        if len(m.status) <= self.field_index:
            return
        self._field_clear = bool(m.status[self.field_index])

    # -- authority ---------------------------------------------------------
    def _authority(self, now: float):
        if self._lease is None or self._lease_t is None or now - self._lease_t > self.lease_fresh:
            return None, 0
        return (str(self._lease.instance), int(self._lease.generation)), int(self._lease.allowed)

    def _inputs(self, now: float, dt: float) -> lj.Inputs:
        authority, allowed = self._authority(now)
        panel_ok = (
            self._panel is not None
            and self._panel_t is not None
            and now - self._panel_t <= self.panel_fresh
        )
        start_edge_t, self._start_edge_t = self._start_edge_t, None
        reset_edge, self._reset_edge = self._reset_edge, False
        track_ok, track_cause = self.reader.usable(now)
        return lj.Inputs(
            now=now,
            dt=dt,
            sensor=self.reader.sensor(),
            sensor_age_s=self.reader.age_s(now) or 0.0,
            track_ok=track_ok,
            track_cause=track_cause,
            panel_valid=bool(panel_ok and self._panel.valid),
            panel_auto=bool(panel_ok and self._panel.mode_auto),
            start_edge=start_edge_t is not None,
            start_edge_t=start_edge_t,
            reset_edge=reset_edge,
            lease_allowed=allowed,
            lease_line=ControlLease.LINE,
            authority=authority,
            torque_off=bool(
                self._torque_off_msg
                and self._drives_t is not None
                and now - self._drives_t <= self.drives_fresh_s
            ),
            field_clear=self._field_clear,
            drives_fresh=bool(
                self._drives_t is not None and now - self._drives_t <= self.drives_fresh_s
            ),
        )

    # -- services ----------------------------------------------------------
    def _srv_arm(self, req, res):
        now = time.monotonic()
        ok, msg = self.job.arm(self._inputs(now, self.dt))
        res.success, res.message = ok, msg
        self.get_logger().info(f"arm: {msg}")
        self._publish_state()
        return res

    def _srv_clear(self, req, res):
        if self.job.clear():
            # Do not leave the last nonzero command live until the mux's
            # freshness timeout: zero it now.
            self._publish_cmd(0.0, 0.0)
        res.success, res.message = True, "cleared"
        self.get_logger().info("clear: the layer is disarmed")
        self._publish_state()
        return res

    # -- the tick ----------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._t_last = now - self._t_last, now
        before = self.job.state

        left, right = self.job.tick(self._inputs(now, min(dt, 5 * self.dt)))

        if self.job.state == lj.RUNNING:
            v, omega = kinematics.wheels_to_body(left, right)
            self._publish_cmd(v, omega)
        elif before == lj.RUNNING:
            # Explicit zero on the falling edge, for the same reason as above.
            self._publish_cmd(0.0, 0.0)

        if self.job.state != before:
            self.get_logger().info(
                f"line {lj.STATE_NAMES[before]} -> {lj.STATE_NAMES[self.job.state]}"
                f" {self.job.reason}"
            )
            self._publish_state()

    # -- output ------------------------------------------------------------
    def _publish_cmd(self, v: float, omega: float) -> None:
        if v == 0.0 and omega == 0.0 and self._published_zero:
            return
        m = Twist()
        m.linear.x = float(v)
        m.angular.z = float(omega)
        self._pub_cmd.publish(m)
        self._published_zero = v == 0.0 and omega == 0.0

    def _publish_state(self) -> None:
        d = getattr(self.job, "diag", {}) or {}
        m = LineState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.generation = self._generation
        m.state = self.job.state
        m.hold_cause = self.job.hold_cause
        m.auto_resume = self.job.auto_resume()
        m.engine_state = str(d.get("state", "idle"))
        m.has_track = bool(d.get("has_track", False))
        m.error_mm = float(d.get("e_mm") or 0.0)
        v, omega = (0.0, 0.0)
        if self.job.state == lj.RUNNING and d:
            v, omega = kinematics.wheels_to_body(d.get("n_l", 0.0), d.get("n_r", 0.0))
        m.v_mps, m.omega_rad_s = float(v), float(omega)
        m.followed_m = float(self.job.followed_m)
        m.track_hz = float(self.reader.hz() or 0.0)
        m.sample_age_s = float(self.reader.age_s(time.monotonic()) or 0.0)
        m.track_source = "" if self.reader.last is None else str(self.reader.last.source)
        m.message = self.job.reason
        self._pub_state.publish(m)


def main() -> None:
    rclpy.init()
    node = LineFollowNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.job.clear()
            node._publish_cmd(0.0, 0.0)
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    main()
