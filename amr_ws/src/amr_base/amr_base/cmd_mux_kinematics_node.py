"""Command mux + permission gating + slew limit + inverse kinematics (spec §3.5, §3.7).

Sources: /amr/manual_command (browser jog, panel MANUAL), /cmd_vel_teleop
(engineering keyboard, panel MANUAL, `teleop_enabled`), the navigation layer's
generation-private /amr/layers/<gen>/cmd_vel (controller_server, permit FOLLOW)
and .../cmd_vel_rotate (behavior_server, permit ROTATE) -> /cmd_wheel_vel at
50 Hz, stamped with the applied supervisor generation.

Authority is decided by amr_base.gating from the supervisor's ControlLease
(`require_supervisor`), the panel image, the drive owner's status and the
executor's MotionPermit; a command must also be fresh (0.2 s). Loss of
authority or a fault zeroes the output at once, not through the ramp. A lease
generation change clears every cached command, permit and slew state and
re-subscribes the navigation inputs: nothing from the old layer can be replayed
into the new one. /amr/mux_state (10 Hz) is the transition barrier's
acknowledgement that a new (inhibited) generation has been applied.

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
from amr_interfaces.msg import (
    ControlLease,
    DriveStatus,
    ManualCommand,
    MotionPermit,
    MuxState,
    PanelState,
    WheelVelocities,
)

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
        self.declare_parameter("require_supervisor", False)  # production: True (unified plan §4.2)
        self.declare_parameter("teleop_enabled", True)  # /cmd_vel_teleop, engineering only
        self.declare_parameter("lease_timeout_s", 0.3)
        self.declare_parameter("drives_timeout_s", 0.3)

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
            lease_timeout_s=p("lease_timeout_s").value,
            drives_timeout_s=p("drives_timeout_s").value,
            require_supervisor=bool(p("require_supervisor").value),
            teleop_enabled=bool(p("teleop_enabled").value),
        )
        self.dt = 1.0 / p("rate_hz").value

        self._teleop: gating.Stamped | None = None
        self._follow: gating.Stamped | None = None
        self._rotate: gating.Stamped | None = None
        self._permit: gating.Permit | None = None
        self._panel: gating.Panel | None = None
        self._lease: gating.Lease | None = None
        self._manual: gating.Manual | None = None
        self._drives: gating.Drives | None = None
        self._applied_gen = 0  # the lease generation the subscriptions/caches belong to
        self._applied_instance = ""
        self._v = 0.0
        self._wz = 0.0
        self._source = "none"
        self._reason = ""
        self._last = gating.Selection(gating.NONE, 0.0, 0.0, "", 0, False)

        self.create_subscription(Twist, "/cmd_vel_teleop", self._on_teleop, RELIABLE_1)
        self._nav_subs: list = []
        self._subscribe_nav(0)
        self.create_subscription(MotionPermit, "/amr/motion_permit", self._on_permit, RELIABLE_1)
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10)
        self.create_subscription(ControlLease, "/amr/control_lease", self._on_lease, RELIABLE_1)
        self.create_subscription(ManualCommand, "/amr/manual_command", self._on_manual, RELIABLE_1)
        self.create_subscription(DriveStatus, "/drives/status", self._on_drives, RELIABLE_1)
        self._pub = self.create_publisher(WheelVelocities, "/cmd_wheel_vel", RELIABLE_1)
        self._pub_state = self.create_publisher(MuxState, "/amr/mux_state", RELIABLE_1)
        self.create_timer(self.dt, self._tick)
        self.create_timer(0.1, self._publish_state)
        if not self.gp.require_supervisor:
            self.get_logger().warn(
                "require_supervisor=false: unsupervised bench mode, no ControlLease needed"
            )
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
        cur = self._permit
        same_stream = cur is not None and cur.instance == msg.instance and cur.generation == msg.generation
        if same_stream and int(msg.seq) <= cur.seq and int(msg.seq) != 0:
            return  # an older sample cannot renew permission
        self._permit = gating.Permit(
            self._now(), int(msg.source), bool(msg.enabled), msg.instance, int(msg.generation), int(msg.seq)
        )

    def _on_panel(self, msg: PanelState) -> None:
        self._panel = gating.Panel(self._now(), bool(msg.valid), bool(msg.mode_auto))

    def _on_drives(self, msg: DriveStatus) -> None:
        self._drives = gating.Drives(self._now(), bool(msg.operational))

    def _on_manual(self, msg: ManualCommand) -> None:
        cur = self._manual
        if cur is not None and cur.session == msg.session and int(msg.seq) <= cur.seq:
            return  # reordered / duplicate refresh
        v, w = float(msg.v), float(msg.w)
        if not (math.isfinite(v) and math.isfinite(w) and math.isfinite(msg.valid_for_s)):
            return
        self._manual = gating.Manual(
            self._now(),
            v,
            w,
            msg.instance,
            int(msg.generation),
            msg.session,
            int(msg.seq),
            float(msg.valid_for_s),
        )

    def _on_lease(self, msg: ControlLease) -> None:
        cur = self._lease
        if cur is not None and cur.instance == msg.instance and cur.generation == msg.generation:
            if int(msg.seq) <= cur.seq:
                return  # stale sample cannot extend a lease
        self._lease = gating.Lease(
            self._now(), msg.instance, int(msg.generation), int(msg.seq), int(msg.allowed)
        )
        if (msg.instance, int(msg.generation)) != (self._applied_instance, self._applied_gen):
            self._apply_generation(msg.instance, int(msg.generation))

    def _apply_generation(self, instance: str, gen: int) -> None:
        """A new layer: forget every command, permit and ramp of the old one."""
        self.get_logger().info(
            f"supervisor generation {self._applied_gen} -> {gen} ({instance[:8]}): caches cleared"
        )
        self._applied_instance, self._applied_gen = instance, gen
        self._teleop = self._follow = self._rotate = None
        self._permit = None
        self._manual = None
        self._v = self._wz = 0.0
        self._subscribe_nav(gen)

    def _subscribe_nav(self, gen: int) -> None:
        for sub in self._nav_subs:
            self.destroy_subscription(sub)
        self._nav_subs = [
            self.create_subscription(Twist, gating.nav_topic("/cmd_vel", gen), self._on_follow, RELIABLE_1),
            self.create_subscription(
                Twist, gating.nav_topic("/cmd_vel_rotate", gen), self._on_rotate, RELIABLE_1
            ),
        ]

    def _tick(self) -> None:
        sel = gating.select(
            self._now(),
            self._teleop,
            self._follow,
            self._rotate,
            self._permit,
            self._panel,
            self.gp,
            lease=self._lease,
            manual=self._manual,
            drives=self._drives,
        )
        name = gating.NAMES[sel.source]
        if name != self._source or (sel.source == gating.NONE and sel.reason != self._reason):
            self.get_logger().info(f"command source: {self._source} -> {name} ({sel.reason})")
            self._source, self._reason = name, sel.reason

        if sel.source == gating.NONE or (sel.v == 0.0 and sel.w == 0.0 and sel.reason.endswith("timed out")):
            self._v = 0.0  # loss of authority or an expired command: zero at once, never a ramp
            self._wz = 0.0
        else:
            self._v = slew(self._v, sel.v, self.a_max, self.dt)
            self._wz = slew(self._wz, sel.w, self.alpha_max, self.dt)

        wl, wr = clamp_wheels(*inverse(self.geom, self._v, self._wz), self.w_max)
        self._last = sel
        self._out = (wl, wr)
        out = WheelVelocities()
        out.header.stamp = self.get_clock().now().to_msg()
        out.generation = self._applied_gen
        out.left_rad_s = wl
        out.right_rad_s = wr
        self._pub.publish(out)

    _out = (0.0, 0.0)

    def _publish_state(self) -> None:
        m = MuxState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.instance = self._applied_instance
        m.generation = self._applied_gen
        m.source = self._last.source
        m.inhibited = bool(self._last.inhibited)
        m.left_rad_s, m.right_rad_s = self._out
        m.reason = self._last.reason
        self._pub_state.publish(m)


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
