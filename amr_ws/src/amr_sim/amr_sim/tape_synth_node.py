"""tape_synth_node: a straight strip of magnetic tape, for the LINE layer in sim. Manual-only
(`ros2 run amr_sim tape_synth_node`): no launch file starts it (lean plan D164).

Re-hosts the plant from the tape engine's test rig (`amr_line/test/harness.py`,
itself verbatim from gy-demo): the vehicle's lateral offset y and heading theta
integrate e_dot = v*sin(theta), theta_dot = omega from the wheel speeds the
fake base actually reaches - not from the commanded ones - so the drivers' slew
limit still shapes the loop exactly as it does in the offline step-response
tests. What the sensor reports is the NEGATIVE of the sensor's offset from the
tape, quantised to 1 mm at 100 Hz, which is the polarity measured on the
machine on 2026-08-31 and the one the engine's INVERT_ERROR is tuned against.

The tape is `tape_length_m` long and then stops. Past its end the sensor
reports no track, so a follower that runs off the end must finish DONE on its
own line-loss distance budget - that is the swap-out test, and it is the
reason this node exists: a LINE layer that can be entered, run, ended and left
without a vehicle.

    /wheel_states    WheelStates (in)   the fake base's wheel speeds
    /amr/line_track  LineTrack          100 Hz, tpdo-sourced, seq-numbered

Parameters: y0_mm (initial offset, default 30 = the rig's step), tape_length_m
(default 20), rate_hz (100). Nothing here reads the engine's gains.

Fault hooks (H-P3-2, WP-T2; amr_sim.fault_hooks): ~/mute, ~/freeze (std_srvs/SetBool), the
script parameters dropout_at_s + dropout_s (an MLS dropout window), freeze_at_s (frozen from
then on: seq moves, the reading does not), and rate_after_s + rate_hz_after (a slow MLS).
"""

from __future__ import annotations

import time

from agv_core import config
from agv_core.drivers.canbus.mls_markers import SOURCE_TPDO
from std_srvs.srv import SetBool

from amr_base.diff_drive import WheelScale
from amr_base.lean_node import LeanNode, run
from amr_base.qos import SENSOR_DATA
from amr_interfaces.msg import LineTrack, WheelStates
from amr_sim import fault_hooks as fh
from amr_sim.tape_plant import TapePlant

_SCALE = WheelScale(config.GEAR_RATIO, config.INVERT_LEFT, config.INVERT_RIGHT)


class TapeSynth(LeanNode):
    def __init__(self) -> None:
        super().__init__("tape_synth")
        self.declare_parameter("y0_mm", 30.0)
        self.declare_parameter("tape_length_m", 20.0)
        self.declare_parameter("rate_hz", 100.0)
        self.declare_parameter("dropout_at_s", 0.0)
        self.declare_parameter("dropout_s", 0.0)
        self.declare_parameter("freeze_at_s", 0.0)
        self.declare_parameter("rate_after_s", 0.0)
        self.declare_parameter("rate_hz_after", 0.0)
        g = self.get_parameter
        self._hk = fh.Hooks(fh.Script(freeze_after_s=g("freeze_at_s").value,
                                      dropout_at_s=g("dropout_at_s").value,
                                      dropout_s=g("dropout_s").value))
        self._rate_after_s = float(g("rate_after_s").value)
        self._every = fh.decimation(float(g("rate_hz").value), float(g("rate_hz_after").value))
        self._n = 0
        self._t0 = time.monotonic()
        self.plant = TapePlant(
            float(self.get_parameter("y0_mm").value) / 1000.0,
            float(self.get_parameter("tape_length_m").value),
            config.SENSOR_LOOKAHEAD_M,
        )
        self.dt = 1.0 / float(self.get_parameter("rate_hz").value)
        self._left = self._right = 0.0
        self._seq = 0
        self._t_last = time.monotonic()
        self._pub = self.create_publisher(LineTrack, "/amr/line_track", SENSOR_DATA)
        self.create_subscription(WheelStates, "/wheel_states", self._on_wheels, SENSOR_DATA)
        self.create_timer(self.dt, self._tick)
        self.create_service(SetBool, "~/mute", self._hook(fh.MUTE))
        self.create_service(SetBool, "~/freeze", self._hook(fh.FREEZE))
        self.get_logger().info(
            f"tape: {self.plant.tape_length_m} m straight, sensor starts "
            f"{self.plant.y * 1000:.0f} mm off it"
        )

    def _hook(self, name: str):
        def srv(req, res):
            res.success, res.message = True, self._hk.set(name, req.data)
            self.get_logger().warn(f"sim fault: {res.message}")
            return res
        return srv

    def _on_wheels(self, m: WheelStates) -> None:
        # rad/s at the wheel -> motor r/min, the engine's unit
        self._left = _SCALE.motor_rpm(m.left_vel_rad_s, True)
        self._right = _SCALE.motor_rpm(m.right_vel_rad_s, False)

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._t_last = now - self._t_last, now
        self.plant.step(self._left, self._right, min(dt, 5 * self.dt))
        mm = self.plant.reading_mm()

        t = now - self._t0
        self._n += 1
        if self._rate_after_s > 0 and t >= self._rate_after_s and self._n % self._every:
            return  # the slow MLS: only every Nth tick goes out
        m = LineTrack()
        m.source = SOURCE_TPDO
        m.sample_age_s = 0.0
        m.lcp_mm = [0, 0, 0]
        m.valid = [False, False, False]
        if mm is None:
            m.nlcp, m.nlcp_label, m.line_good = 0, "none", False
        else:
            # One tape -> LCP2 is the track (MLS table 17).
            m.lcp_mm[1] = int(mm)
            m.valid[1] = True
            m.nlcp, m.nlcp_label, m.line_good = 2, "one track", True
        m.track_level = 7 if mm is not None else 0
        m.polarity = "north"
        m = self._hk.out(t, m)
        if m is None:
            return
        m.stamp = self.get_clock().now().to_msg()
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        m.seq = self._seq  # a frozen MLS still counts on
        self._pub.publish(m)


def main() -> None:
    run(TapeSynth, None, catch_runtime=False)


if __name__ == "__main__":
    main()
