"""Command mux + permission gating + slew limit + inverse kinematics (spec §3.5, §3.7).

Sources: /cmd_vel_teleop (panel MANUAL), /cmd_vel (controller_server, permit
FOLLOW), /cmd_vel_rotate (behavior_server, permit ROTATE) -> /cmd_wheel_vel at
50 Hz. Authority is decided by amr_base.gating from the panel image and the
executor's MotionPermit lease; a command must also be fresh (0.2 s). Loss of
authority or a fault zeroes the output at once, not through the ramp.

Acceleration limits default to the drives' own 6083h ramp from the profile
(reconciliation D-1): a controller allowed to demand more than the drives can
slew diverges. A parameter may lower them, never raise them above hardware.
"""

import math

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy

from amr_base import gating
from amr_base.agv_repo import config, kinematics
from amr_base.diff_drive import Geometry, clamp_wheels, inverse, slew
from amr_interfaces.msg import MotionPermit, PanelState, WheelVelocities

RELIABLE_1 = QoSProfile(
    depth=1,
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.VOLATILE,
)

WHEEL_RAD_S_PER_MOTOR_RPM = 2.0 * math.pi / 60.0 / config.GEAR_RATIO


class CmdMuxKinematics(Node):
    def __init__(self) -> None:
        super().__init__("cmd_mux_kinematics")
        hw_a_max = config.ACCEL_RPM_S * config.MPS_PER_RPM
        hw_alpha_max = kinematics.max_yaw_accel(config.ACCEL_RPM_S)

        self.declare_parameter("wheel_radius_m", config.WHEEL_DIA_M / 2.0)
        self.declare_parameter("track_width_m", config.TRACK_M)
        self.declare_parameter("wheel_vel_max_rad_s", config.MOTOR_MAX_RPM * WHEEL_RAD_S_PER_MOTOR_RPM)
        self.declare_parameter("a_max", min(0.5, hw_a_max))
        self.declare_parameter("alpha_max", min(1.0, hw_alpha_max))
        self.declare_parameter("teleop_timeout_s", 0.5)
        self.declare_parameter("cmd_timeout_s", 0.2)
        self.declare_parameter("permit_timeout_s", 0.3)
        self.declare_parameter("panel_timeout_s", 0.2)
        self.declare_parameter("rate_hz", 50.0)

        p = self.get_parameter
        self.geom = Geometry(p("wheel_radius_m").value, p("track_width_m").value)
        self.w_max = p("wheel_vel_max_rad_s").value
        self.a_max = min(p("a_max").value, hw_a_max)
        self.alpha_max = min(p("alpha_max").value, hw_alpha_max)
        if self.a_max < p("a_max").value or self.alpha_max < p("alpha_max").value:
            self.get_logger().warn(
                f"accel limits clamped to hardware: a_max={self.a_max:.3f} "
                f"alpha_max={self.alpha_max:.3f} (6083h = {config.ACCEL_RPM_S} r/min/s)"
            )
        self.gp = gating.Params(
            cmd_timeout_s=p("cmd_timeout_s").value,
            teleop_window_s=p("teleop_timeout_s").value,
            permit_timeout_s=p("permit_timeout_s").value,
            panel_timeout_s=p("panel_timeout_s").value,
        )
        self.dt = 1.0 / p("rate_hz").value

        self._teleop: gating.Stamped | None = None
        self._follow: gating.Stamped | None = None
        self._rotate: gating.Stamped | None = None
        self._permit: gating.Permit | None = None
        self._panel: gating.Panel | None = None
        self._v = 0.0
        self._wz = 0.0
        self._source = "none"
        self._reason = ""

        self.create_subscription(Twist, "/cmd_vel_teleop", self._on_teleop, RELIABLE_1)
        self.create_subscription(Twist, "/cmd_vel", self._on_follow, RELIABLE_1)
        self.create_subscription(Twist, "/cmd_vel_rotate", self._on_rotate, RELIABLE_1)
        self.create_subscription(MotionPermit, "/amr/motion_permit", self._on_permit, RELIABLE_1)
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10)
        self._pub = self.create_publisher(WheelVelocities, "/cmd_wheel_vel", RELIABLE_1)
        self.create_timer(self.dt, self._tick)
        self.get_logger().info(
            f"r={self.geom.wheel_radius_m} track={self.geom.track_width_m} "
            f"w_max={self.w_max:.2f} rad/s a_max={self.a_max:.3f} alpha_max={self.alpha_max:.3f}"
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_teleop(self, msg: Twist) -> None:
        self._teleop = gating.Stamped(self._now(), msg.linear.x, msg.angular.z)

    def _on_follow(self, msg: Twist) -> None:
        self._follow = gating.Stamped(self._now(), msg.linear.x, msg.angular.z)

    def _on_rotate(self, msg: Twist) -> None:
        self._rotate = gating.Stamped(self._now(), msg.linear.x, msg.angular.z)

    def _on_permit(self, msg: MotionPermit) -> None:
        self._permit = gating.Permit(self._now(), int(msg.source), bool(msg.enabled))

    def _on_panel(self, msg: PanelState) -> None:
        self._panel = gating.Panel(self._now(), bool(msg.valid), bool(msg.mode_auto))

    def _tick(self) -> None:
        sel = gating.select(
            self._now(), self._teleop, self._follow, self._rotate, self._permit, self._panel, self.gp
        )
        name = gating.NAMES[sel.source]
        if name != self._source or (sel.source == gating.NONE and sel.reason != self._reason):
            self.get_logger().info(f"command source: {self._source} -> {name} ({sel.reason})")
            self._source, self._reason = name, sel.reason

        if sel.source == gating.NONE:
            self._v = 0.0  # loss of authority: zero at once, never a ramp
            self._wz = 0.0
        else:
            self._v = slew(self._v, sel.v, self.a_max, self.dt)
            self._wz = slew(self._wz, sel.w, self.alpha_max, self.dt)

        wl, wr = clamp_wheels(*inverse(self.geom, self._v, self._wz), self.w_max)
        out = WheelVelocities()
        out.header.stamp = self.get_clock().now().to_msg()
        out.left_rad_s = wl
        out.right_rad_s = wr
        self._pub.publish(out)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdMuxKinematics()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        # A callback running while launch tears the context down raises from
        # the C layer ("Unable to convert call argument"); only real if still ok.
        if rclpy.ok():
            raise
    finally:
        # launch sends SIGINT; the context may already be down by the time we
        # get here, and destroy_node() then raises from the C layer.
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
