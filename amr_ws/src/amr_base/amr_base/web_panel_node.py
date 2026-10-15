"""web_panel_node (aop-demo-oct): the operator panel when the vehicle has no DIO island.

This branch drives the vehicle from the web app alone: no selector, no Start/Reset, no
pendant, no Manual Arm input. This node stands where panel_node stood and publishes the
same /amr/panel_state, so the mux, arm_policy, drive_node and the supervisor read it
unchanged:

    selector  MANUAL, always (mode_auto false): nothing autonomous can start
    edges     never: no Start, no Reset
    pendant   never held
    manual_arm the web app's Arm / Disarm (/amr/panel/arm, std_srvs/SetBool); default OFF

Under MANUAL, arm_policy powers the drives exactly while manual_arm is true, so Arm here
is what Manual Arm (DI08) was on the cabinet. Jogging still needs the supervisor's manual
lease and a fresh, held browser command (gating.py); arming alone moves nothing.

The arm DROPS on its own when the drives report a fault, when they do not reach Operation
enabled within engage_timeout_s of the Arm, or when they leave it for that long later, and
it is refused while the drive status is stale or faulted. drive_node retries a failed
engage every 2 s while power is wanted; with one drive held in Switch on disabled (STO) that
enabled and shut down the other one every retry - the clicking heard on 2026-10-15. Each
press of Arm is now ONE attempt: a person clears the cause and arms again, never software
re-powering by itself (no automatic restart). The FX3 -> STO chain is untouched.

If this node dies the panel image goes stale: the mux zeroes and arm_policy cuts power.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from std_srvs.srv import SetBool

from amr_interfaces.msg import DriveStatus, Event, PanelState

RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
# drive_node's link states (DriveStatus.link_state) from which power may be asked for
ARMABLE = ("standby", "armed")


@dataclass
class Drives:
    t_recv: float
    link_state: str
    operational: bool = False


class WebArm:
    """The arm latch. Pure and clock-fed so it can be tested without ROS."""

    def __init__(self, drives_timeout_s: float = 1.0, engage_timeout_s: float = 1.5) -> None:
        self.armed = False
        self.drives: Drives | None = None
        self.timeout = drives_timeout_s
        # Under drive_node's 2 s engage retry, so a failed engage is never retried.
        self.engage_timeout = engage_timeout_s
        self._ok_t = 0.0  # the Arm press, then the last drive status that was operational

    def _drives_why(self, now: float) -> str | None:
        d = self.drives
        if d is None or now - d.t_recv > self.timeout:
            return "no drive status"
        if d.link_state not in ARMABLE:
            return f"drives {d.link_state or 'unknown'}"
        return None

    def request(self, arm: bool, now: float) -> tuple[bool, str]:
        if not arm:
            was, self.armed = self.armed, False
            return True, "disarmed" if was else "already disarmed"
        why = self._drives_why(now)
        if why is not None:
            return False, f"cannot arm: {why}"
        if not self.armed:
            self._ok_t = now
        self.armed = True
        return True, "armed: drives powered at zero; hold a jog button to move"

    def on_drives(self, d: Drives) -> str | None:
        """Feed a drive status. Returns why the arm was dropped, if it was."""
        self.drives = d
        if not self.armed:
            return None
        if d.link_state == "fault":
            self.armed = False
            return "drive fault: disarmed, arm again after clearing it"
        if d.operational:
            self._ok_t = d.t_recv
        return self.tick(d.t_recv)

    def tick(self, now: float) -> str | None:
        """Drop an arm the drives have not honoured for engage_timeout_s (also covers a
        drive status that stopped arriving). Returns why, if it was dropped."""
        if self.armed and now - self._ok_t > self.engage_timeout:
            self.armed = False
            return (
                f"the drives did not power up within {self.engage_timeout:g} s: disarmed. "
                "See the Drives row for the drive that stayed off, then arm again"
            )
        return None


class WebPanel(Node):
    def __init__(self) -> None:
        super().__init__("web_panel")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("drives_timeout_s", 1.0)
        self.declare_parameter("engage_timeout_s", 1.5)
        self._lock = threading.Lock()
        self._arm = WebArm(
            float(self.get_parameter("drives_timeout_s").value),
            float(self.get_parameter("engage_timeout_s").value),
        )
        self._event_seq = 0
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self.seq = 0
        self._pub = self.create_publisher(PanelState, "/amr/panel_state", 10)
        # 10 Hz copy for displays, as panel_node publishes it.
        self._pub_ui = self.create_publisher(PanelState, "/amr/panel_state_ui", 10)
        self._ui_t = 0.0
        self.create_subscription(DriveStatus, "/drives/status", self._on_drives, RELIABLE_1)
        self.create_service(SetBool, "/amr/panel/arm", self._srv_arm)
        self.create_timer(1.0 / float(self.get_parameter("rate_hz").value), self._tick)
        self.get_logger().info("web panel: selector MANUAL, drives disarmed until the web app arms them")

    def _on_drives(self, m: DriveStatus) -> None:
        with self._lock:
            why = self._arm.on_drives(Drives(time.monotonic(), str(m.link_state), bool(m.operational)))
        if why:
            self._dropped(why)

    def _dropped(self, why: str) -> None:
        """An arm the drives did not honour: say so where the operator looks (the web log)."""
        self.get_logger().warn(why)
        e = Event()
        e.header.stamp = self.get_clock().now().to_msg()
        e.source, e.level, e.code, e.text = "web_panel", Event.WARN, "DRIVES_NOT_READY", why
        self._event_seq += 1
        e.seq = self._event_seq
        self._pub_event.publish(e)

    def _srv_arm(self, req, res):
        with self._lock:
            res.success, res.message = self._arm.request(bool(req.data), time.monotonic())
        self.get_logger().info(f"{'arm' if req.data else 'disarm'} from the web: {res.message}")
        return res

    def _tick(self) -> None:
        m = PanelState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.valid = True
        m.mode_auto = False
        self.seq += 1
        m.seq = self.seq
        with self._lock:
            why = self._arm.tick(time.monotonic())
            m.manual_arm = self._arm.armed
        if why:
            self._dropped(why)
        self._pub.publish(m)
        if time.monotonic() - self._ui_t >= 0.1:
            self._ui_t = time.monotonic()
            self._pub_ui.publish(m)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WebPanel()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        if rclpy.ok():
            raise
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
