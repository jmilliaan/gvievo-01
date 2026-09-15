"""Command mux + slew limit + inverse kinematics (spec §3.7).

/cmd_vel_teleop (priority) and /cmd_vel (nav) -> /cmd_wheel_vel at 50 Hz.
Teleop is active while its last message is younger than teleop_timeout_s.
No input within cmd_timeout_s -> zero output immediately (defence in depth
with the drive node watchdog), not a ramp.

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

from amr_base.agv_repo import config, kinematics
from amr_base.diff_drive import Geometry, clamp_wheels, inverse, slew
from amr_interfaces.msg import WheelVelocities

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
        self.teleop_timeout = p("teleop_timeout_s").value
        self.cmd_timeout = p("cmd_timeout_s").value
        self.dt = 1.0 / p("rate_hz").value

        self._teleop: tuple[float, Twist] | None = None
        self._nav: tuple[float, Twist] | None = None
        self._v = 0.0
        self._wz = 0.0
        self._source = "none"

        self.create_subscription(Twist, "/cmd_vel_teleop", self._on_teleop, RELIABLE_1)
        self.create_subscription(Twist, "/cmd_vel", self._on_nav, RELIABLE_1)
        self._pub = self.create_publisher(WheelVelocities, "/cmd_wheel_vel", RELIABLE_1)
        self.create_timer(self.dt, self._tick)
        self.get_logger().info(
            f"r={self.geom.wheel_radius_m} track={self.geom.track_width_m} "
            f"w_max={self.w_max:.2f} rad/s a_max={self.a_max:.3f} alpha_max={self.alpha_max:.3f}"
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_teleop(self, msg: Twist) -> None:
        self._teleop = (self._now(), msg)

    def _on_nav(self, msg: Twist) -> None:
        self._nav = (self._now(), msg)

    def _select(self) -> tuple[str, Twist | None]:
        now = self._now()
        if self._teleop and now - self._teleop[0] < self.teleop_timeout:
            return "teleop", self._teleop[1]
        if self._nav and now - self._nav[0] < self.cmd_timeout:
            return "nav", self._nav[1]
        return "none", None

    def _tick(self) -> None:
        source, cmd = self._select()
        if source != self._source:
            self.get_logger().info(f"command source: {self._source} -> {source}")
            self._source = source

        if cmd is None:
            self._v = 0.0
            self._wz = 0.0
        else:
            self._v = slew(self._v, cmd.linear.x, self.a_max, self.dt)
            self._wz = slew(self._wz, cmd.angular.z, self.alpha_max, self.dt)

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
