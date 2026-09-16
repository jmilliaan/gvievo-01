"""drive_node (T9 + T10): the ONE owner of can0 - both BLV-R drives and the MLS gyro.

    /cmd_wheel_vel  (WheelVelocities, mux, 50 Hz)  ->  RPDO1 to both drives
    TPDO1/TPDO2 from both drives                   ->  /wheel_states  (WheelStates)
    MLS 2034h:3 (TPDO or SDO poll)                 ->  /imu/data_raw  (sensor_msgs/Imu)
    CiA-402 state, alarms, liveness                ->  /drives/status (DriveStatus, 10 Hz)

Services (std_srvs/Trigger): /drives/arm, /drives/disarm, /drives/ack_fault.

One bus thread does everything on the wire, in this order every tick:
service requests, arm policy, setpoint, PC heartbeat, IMU poll, feedback
publish, then pumps the bus for the rest of the period (TPDOs, EMCY and
heartbeats are decoded inside that pump). rclpy spins on the main thread.

Independent command watchdog: a /cmd_wheel_vel older than cmd_timeout_s is a
zero setpoint. Independent PC-loss response on the drive side: see
amr_base.canopen (1016h). Never runs beside agv_controller - both would own
can0 - and refuses to start if the bus cannot be opened.
"""

from __future__ import annotations

import queue
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu
from std_srvs.srv import Trigger

from amr_base import canopen
from amr_base.agv_repo import config
from amr_base.mls_imu import ImuSample, MlsImu
from amr_interfaces.msg import DriveStatus, WheelStates, WheelVelocities

from verify_drivers import open_bus  # noqa: E402  (repo module via agv_repo)

SENSOR_DATA = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)
RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)
BIG = 1e6


class DriveNode(Node):
    def __init__(self) -> None:
        super().__init__("drive_node")
        dp = self.declare_parameter
        dp("rate_hz", 1.0 / config.LOOP_PERIOD_S)
        dp("cmd_timeout_s", 0.2)
        dp("feedback_hz", 50.0)  # TPDO event timer; 100 Hz once the 125 kbps bus is proven to carry it
        dp("driver_timeout_s", config.DRIVER_TIMEOUT_S)
        dp("auto_arm", True)
        dp("arm_retry_s", 2.0)
        dp("pc_node_id", 100)
        dp("pc_heartbeat_ms", 100)
        dp("pc_loss_ms", 500)  # 1016h on the drives; 0 disables the drive-side response
        dp("ramp", "auto")  # profile drivers.ramp.<name>
        dp("imu_enabled", config.IMU_ENABLED)
        dp("imu_poll_hz", 50.0)
        dp("imu_stamp_every", 10)
        dp("gyro_sign", 1.0)  # VERIFY on the vehicle: CCW spin must read positive
        dp("gyro_var", 1e-6)  # (rad/s)^2; measured sigma 0.029 deg/s and LSB 0.061 deg/s
        dp("imu_frame", "imu_frame")
        p = self.get_parameter
        self.period = 1.0 / p("rate_hz").value
        self.cmd_timeout = p("cmd_timeout_s").value
        self.feedback_ms = max(1, int(round(1000.0 / p("feedback_hz").value)))
        self.driver_timeout = p("driver_timeout_s").value
        self.want_armed = bool(p("auto_arm").value)
        self.arm_retry = p("arm_retry_s").value
        self.pc_node = int(p("pc_node_id").value)
        self.pc_hb_s = p("pc_heartbeat_ms").value / 1000.0
        self.pc_loss_ms = int(p("pc_loss_ms").value)
        self.ramp = config.RAMP[p("ramp").value]
        self.imu_enabled = bool(p("imu_enabled").value)
        self.imu_frame = p("imu_frame").value
        self.gyro_var = p("gyro_var").value

        self.nodes = {config.LEFT: "left", config.RIGHT: "right"}
        self._lock = threading.Lock()
        self._cmd: tuple[float, float, float] | None = None  # (t_mono, wl, wr)
        self._requests: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._status_snapshot: dict = {"state": "starting", "reason": "", "mode": "off"}

        self._pub_wheels = self.create_publisher(WheelStates, "/wheel_states", SENSOR_DATA)
        self._pub_status = self.create_publisher(DriveStatus, "/drives/status", RELIABLE_1)
        self._pub_imu = self.create_publisher(Imu, "/imu/data_raw", SENSOR_DATA)
        self.create_subscription(WheelVelocities, "/cmd_wheel_vel", self._on_cmd, RELIABLE_1)
        self.create_service(Trigger, "/drives/arm", lambda q, r: self._request("arm", r))
        self.create_service(Trigger, "/drives/disarm", lambda q, r: self._request("disarm", r))
        self.create_service(Trigger, "/drives/ack_fault", lambda q, r: self._request("ack", r))

        self._thread = threading.Thread(target=self._run, name="can", daemon=True)
        self._thread.start()
        # A dead bus thread must take the process down, not leave a node that
        # answers services and publishes nothing.
        self.create_timer(0.5, self._check_bus_thread)

    def _check_bus_thread(self) -> None:
        if not self._thread.is_alive() and not self._stop.is_set():
            self.get_logger().fatal(f"bus thread ended: {self._status_snapshot}")
            raise SystemExit(1)

    # ---- rclpy thread ----

    def _on_cmd(self, msg: WheelVelocities) -> None:
        with self._lock:
            self._cmd = (time.monotonic(), float(msg.left_rad_s), float(msg.right_rad_s))

    def _request(self, what: str, res):
        done = threading.Event()
        box: dict = {}
        self._requests.put((what, done, box))
        if not done.wait(15.0):
            res.success, res.message = False, f"{what}: bus thread did not answer"
            return res
        res.success, res.message = box.get("ok", False), box.get("msg", "")
        return res

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=8.0)

    # ---- bus thread ----

    def _log(self, s: str) -> None:
        self.get_logger().info(s)

    def _run(self) -> None:
        try:
            raw, how = open_bus(config.CAN_BITRATE, config.CAN_CHANNEL, config.CAN_ADAPTER_SERIAL)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"CAN bus unavailable: {e} (is agv_controller stopped?)")
            self._status_snapshot = {"state": "no bus", "reason": str(e), "mode": "off"}
            return
        router = canopen.Router(raw)
        link = canopen.DriveLink(router, self.nodes, self.ramp, log=self._log)
        self._log(f"bus up on {how} at {config.CAN_BITRATE // 1000} kbps, profile {config.PROFILE_NAME}")
        link.enable_heartbeat(config.CAN_HEARTBEAT_MS)
        imu = None
        if self.imu_enabled:
            imu = MlsImu(
                link,
                config.SENSOR_NODE,
                self._publish_imu,
                sign=self.get_parameter("gyro_sign").value,
                poll_hz=self.get_parameter("imu_poll_hz").value,
                stamp_every=self.get_parameter("imu_stamp_every").value,
                log=self._log,
            )
            imu.start()
        if not self.pc_loss_ms:
            self.get_logger().warn("pc_loss_ms=0: the drives have NO independent response to losing this PC")

        try:
            self._loop(link, router, imu)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"bus thread error: {e!r}")
            self._status_snapshot = {"state": "bus error", "reason": repr(e), "mode": "off"}
        finally:
            try:
                link.disarm()
            except Exception:  # noqa: BLE001
                pass
            try:
                router.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._log("bus closed, drives de-energised")

    def _loop(self, link, router, imu) -> None:
        retry_at = 0.0
        t_tick = t_hb = t_status = 0.0
        last_pub = {n: (None, None) for n in self.nodes}
        while not self._stop.is_set() and rclpy.ok():
            t0 = time.perf_counter()
            now = time.monotonic()
            self._serve_requests(link)

            # Arm policy: the pure table decides, this thread acts.
            d = canopen.decide(
                link.state,
                self.want_armed,
                now,
                retry_at,
                link.silent_nodes(now, self.driver_timeout) if link.state == canopen.ARMED else [],
                link.dropped_out(),
                link.faulted_nodes(),
            )
            if d.action == "arm":
                retry_at = now + self.arm_retry
                try:
                    link.arm(
                        self.feedback_ms,
                        self.pc_node if self.pc_loss_ms else None,
                        self.pc_loss_ms,
                        config.GEAR_RATIO,
                        config.INVERT_LEFT,
                        config.INVERT_RIGHT,
                    )
                    self._log("armed (targets zero)")
                except Exception as e:  # noqa: BLE001 - a condition, retried
                    self.get_logger().warn(f"cannot arm: {e} - retrying in {self.arm_retry:.0f} s")
            elif d.action == "disarm":
                self.get_logger().warn(f"disarming: {d.reason}")
                link.disarm()
                retry_at = now + self.arm_retry
            elif d.action == "fault":
                self.get_logger().error(f"FAULT: {d.reason}")
                link.fault(d.reason)

            # Setpoint at rate_hz; the command watchdog is independent of the mux.
            if now - t_tick >= self.period and link.state == canopen.ARMED:
                t_tick = now
                link.send_target(*self._target(now, link.scale))

            if self.pc_loss_ms and now - t_hb >= self.pc_hb_s:
                t_hb = now
                link.send_pc_heartbeat(self.pc_node)

            if imu is not None:
                imu.poll(now)

            # Feedback: a WheelStates per complete new pair (TPDO1+TPDO2 from both).
            fresh = all(
                (link.telemetry[n].t_status, link.telemetry[n].t_position) != last_pub[n]
                and link.telemetry[n].t_status is not None
                and link.telemetry[n].t_position is not None
                for n in self.nodes
            )
            if fresh:
                for n in self.nodes:
                    last_pub[n] = (link.telemetry[n].t_status, link.telemetry[n].t_position)
                self._publish_wheels(link, now)

            if now - t_status >= 0.1:
                t_status = now
                self._publish_status(link, imu)

            spent = time.perf_counter() - t0
            router.pump(max(0.001, self.period - spent))

    def _serve_requests(self, link) -> None:
        while True:
            try:
                what, done, box = self._requests.get_nowait()
            except queue.Empty:
                return
            try:
                if what == "arm":
                    self.want_armed = True
                    box["ok"], box["msg"] = True, "arm requested"
                elif what == "disarm":
                    self.want_armed = False
                    link.disarm()
                    box["ok"], box["msg"] = True, "disarmed"
                elif what == "ack":
                    if link.state != canopen.FAULT:
                        box["ok"], box["msg"] = False, f"no fault latched (state {link.state})"
                    else:
                        reason = link.fault_reason
                        link.disarm()
                        box["ok"], box["msg"] = True, f"fault acknowledged ({reason}); re-arming if wanted"
            finally:
                done.set()

    def _target(self, now: float, scale: canopen.WheelScale) -> tuple[int, int]:
        with self._lock:
            cmd = self._cmd
        return canopen.target_rpm(cmd, now, self.cmd_timeout, scale, config.MOTOR_MAX_RPM)

    def _safe_publish(self, pub, msg) -> None:
        # SIGINT invalidates the context while this thread is mid-iteration;
        # a publish then raises RCLError. Stop quietly rather than log an error.
        if self._stop.is_set() or not rclpy.ok():
            return
        try:
            pub.publish(msg)
        except Exception:  # noqa: BLE001
            self._stop.set()

    def _publish_wheels(self, link, now: float) -> None:
        m = WheelStates()
        m.header.stamp = self.get_clock().now().to_msg()
        max_age = 2.5 * self.feedback_ms / 1000.0
        scale = link.scale
        for n, left in ((config.LEFT, True), (config.RIGHT, False)):
            t = link.telemetry[n]
            fresh = (
                t.t_status is not None
                and t.t_position is not None
                and now - min(t.t_status, t.t_position) < max_age
            )
            pos = scale.wheel_rad(t.position, left) if (scale and t.position is not None) else None
            vel = scale.wheel_rad_s(t.rpm, left) if (scale and t.rpm is not None) else 0.0
            valid = bool(fresh and pos is not None and not t.faulted and link.state == canopen.ARMED)
            if left:
                m.left_pos_rad, m.left_vel_rad_s, m.left_valid = (pos or 0.0), vel, valid
            else:
                m.right_pos_rad, m.right_vel_rad_s, m.right_valid = (pos or 0.0), vel, valid
        self._safe_publish(self._pub_wheels, m)

    def _publish_status(self, link, imu) -> None:
        m = DriveStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        tl, tr = link.telemetry[config.LEFT], link.telemetry[config.RIGHT]
        m.left_statusword, m.right_statusword = tl.statusword or 0, tr.statusword or 0
        m.left_error_code = (tl.alarm or {}).get("code", tl.error_register or 0) & 0xFFFF
        m.right_error_code = (tr.alarm or {}).get("code", tr.error_register or 0) & 0xFFFF
        m.left_state, m.right_state = tl.state, tr.state
        m.operational = bool(link.state == canopen.ARMED and tl.operation_enabled and tr.operation_enabled)
        self._safe_publish(self._pub_status, m)
        snap = {"state": link.state, "reason": link.fault_reason or "", "mode": imu.mode if imu else "off"}
        if snap != self._status_snapshot:
            self._status_snapshot = snap
            why = f" ({snap['reason']})" if snap["reason"] else ""
            self._log(f"drives {snap['state']}{why}, imu {snap['mode']}")

    def _publish_imu(self, s: ImuSample) -> None:
        m = Imu()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = self.imu_frame
        m.orientation_covariance[0] = -1.0
        m.angular_velocity.z = s.wz_rad_s
        m.angular_velocity_covariance = [BIG, 0.0, 0.0, 0.0, BIG, 0.0, 0.0, 0.0, self.gyro_var]
        m.linear_acceleration_covariance[0] = -1.0
        self._safe_publish(self._pub_imu, m)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DriveNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        if rclpy.ok():
            raise
    finally:
        node.stop()  # disarms on the bus thread before the context goes away
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
