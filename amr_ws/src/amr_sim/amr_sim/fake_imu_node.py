"""fake_imu_node (spec §8): yaw rate from ground truth + measured MLS gyro noise.

Publishes /imu/data_raw as the real MLS IMU node (T10) will: RAW, biased.
Noise model is reconciliation D-3, measured on the vehicle 2026-09-03:
bias +0.0574 deg/s, sigma 0.0291 deg/s, plus a small bias random walk so the
bias node has something to track. Orientation is marked unavailable
(covariance[0] = -1): the EKF fuses yaw rate only.

Fault hooks (H-P3-2, WP-T2; amr_sim.fault_hooks): ~/mute, ~/freeze (std_srvs/SetBool) and the
script parameters start_delay_s, drop_after_s, freeze_after_s (also dropout_at_s, dropout_s).
"""

import math
import random
import time

from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from std_srvs.srv import SetBool

from amr_base.lean_node import LeanNode, run
from amr_base.qos import SENSOR_DATA
from amr_sim import fault_hooks as fh

DEG = math.pi / 180.0
G = 9.80665


class FakeImu(LeanNode):
    def __init__(self) -> None:
        super().__init__("fake_imu")
        self.declare_parameter("rate_hz", 100.0)
        self.declare_parameter("frame_id", "imu_frame")
        self.declare_parameter("bias_dps", 0.0574)  # D-3
        self.declare_parameter("noise_dps", 0.0291)  # D-3, 1 sigma
        self.declare_parameter("bias_walk_dps_per_sqrt_s", 0.002)
        self.declare_parameter("gravity_scale", 0.9894)  # D-3, 1.1 % scale error
        self.declare_parameter("seed", 0)
        for name in fh.SCRIPT_PARAMS:
            self.declare_parameter(name, 0.0)
        p = self.get_parameter
        self._hk = fh.Hooks(fh.script_from(lambda n: p(n).value))
        self._t0 = time.monotonic()
        self.dt = 1.0 / p("rate_hz").value
        self.frame_id = p("frame_id").value
        self.bias = p("bias_dps").value * DEG
        self.noise = p("noise_dps").value * DEG
        self.walk = p("bias_walk_dps_per_sqrt_s").value * DEG
        self.gravity = p("gravity_scale").value * G
        self._rng = random.Random(p("seed").value)
        self._wz_true = 0.0

        self._pub = self.create_publisher(Imu, "/imu/data_raw", SENSOR_DATA)
        self.create_subscription(Odometry, "/sim/ground_truth", self._on_truth, SENSOR_DATA)
        self.create_timer(self.dt, self._tick)
        self.create_service(SetBool, "~/mute", self._hook(fh.MUTE))
        self.create_service(SetBool, "~/freeze", self._hook(fh.FREEZE))
        self.get_logger().info(
            f"bias {p('bias_dps').value:+.4f} deg/s, sigma {p('noise_dps').value:.4f} deg/s, "
            f"{1 / self.dt:.0f} Hz"
        )

    def _hook(self, name: str):
        def srv(req, res):
            res.success, res.message = True, self._hk.set(name, req.data)
            self.get_logger().warn(f"sim fault: {res.message}")
            return res
        return srv

    def _on_truth(self, msg: Odometry) -> None:
        self._wz_true = msg.twist.twist.angular.z

    def _tick(self) -> None:
        self.bias += self._rng.gauss(0.0, self.walk * math.sqrt(self.dt))
        m = Imu()
        m.header.frame_id = self.frame_id
        m.orientation_covariance[0] = -1.0
        m.angular_velocity.z = self._wz_true + self.bias + self._rng.gauss(0.0, self.noise)
        m.angular_velocity_covariance = [1e6, 0.0, 0.0, 0.0, 1e6, 0.0, 0.0, 0.0, self.noise**2]
        m.linear_acceleration.z = self.gravity
        m.linear_acceleration_covariance = [1e6, 0.0, 0.0, 0.0, 1e6, 0.0, 0.0, 0.0, 1e6]
        m = self._hk.out(time.monotonic() - self._t0, m)
        if m is None:
            return
        m.header.stamp = self.get_clock().now().to_msg()
        self._pub.publish(m)


def main(args=None) -> None:
    run(FakeImu, args)


if __name__ == "__main__":
    main()
