"""fake_panel_node: the operator panel in simulation (spec §8, T8).

Publishes /amr/panel_state at 20 Hz with the PanelScan semantics (debounced
image, rising edges on exactly one message). Services drive it from tests or a
terminal:
    /sim/panel/set_mode     std_srvs/SetBool   data=true -> AUTO, false -> MANUAL
    /sim/panel/press_start  std_srvs/Trigger
    /sim/panel/press_reset  std_srvs/Trigger
    /sim/panel/set_valid    std_srvs/SetBool   false = DIO link lost (stale/invalid image)
    /sim/panel/set_estop    std_srvs/SetBool   true = E-stop pressed (DI09 active), false = released
The emergency fields (estop_ok, emergency; emergency-suite plan Part B, kyb 243433c) run the real
amr_base/emergency.py: press, release, then press_reset clears it. The sim drives are not observed
(sto None), so a Reset with DI09 clear is taken at once. ~/invalid holds the state (a DIO
gap is not an E-stop, owner 2026-11-16).
Jog pendant levels are bool parameters read every tick, so a terminal can drive
without a browser:  ros2 param set /fake_panel pendant_fwd true  (also
pendant_rvs / pendant_left / pendant_right).
Fault hooks (H-P3-2, WP-T2; amr_sim.fault_hooks): ~/mute (publish nothing), ~/freeze (the last
image again, no new edges), ~/invalid (published with valid=false), plus the script parameters.
The real adapter (T12) wraps core/panel.PanelScan over drivers/dio.DioLink and
publishes the same message.
"""

import time

from agv_core import panel as panel_core  # repo module: core/panel.py
from std_srvs.srv import SetBool, Trigger

from amr_base import emergency
from amr_base.lean_node import UI_PERIOD_FAST_S, LeanNode, UiThrottle, run
from amr_interfaces.msg import PanelState
from amr_sim import fault_hooks as fh

PENDANT_PARAMS = ("pendant_fwd", "pendant_rvs", "pendant_left", "pendant_right")


class FakePanel(LeanNode):
    def __init__(self) -> None:
        super().__init__("fake_panel")
        self.declare_parameter("auto", False)
        self.declare_parameter("rate_hz", 20.0)
        for name in PENDANT_PARAMS:
            self.declare_parameter(name, False)
        for name in fh.SCRIPT_PARAMS:
            self.declare_parameter(name, 0.0)
        self._hk = fh.Hooks(fh.script_from(lambda n: self.get_parameter(n).value))
        self._flag_invalid = False
        self._t0 = time.monotonic()
        self.auto = bool(self.get_parameter("auto").value)
        self.valid = True
        self.estop = False  # E-stop pressed: DI09 active
        self.emergency = emergency.Emergency(3.0)
        self.seq = 0
        self._start_pending = False
        self._reset_pending = False
        self._pub = self.create_publisher(PanelState, "/amr/panel_state", 10)
        # 10 Hz copy for displays (CPU, 2026-10-02): the web shows the selector at 2 Hz.
        # Edges ride only the full topic - nothing that acts on Start/Reset reads this one.
        self._pub_ui = self.create_publisher(PanelState, "/amr/panel_state_ui", 10)
        self._ui = UiThrottle(UI_PERIOD_FAST_S)
        self.create_service(SetBool, "/sim/panel/set_mode", self._set_mode)
        self.create_service(SetBool, "/sim/panel/set_valid", self._set_valid)
        self.create_service(SetBool, "/sim/panel/set_estop", self._set_estop)
        self.create_service(Trigger, "/sim/panel/press_start", self._press_start)
        self.create_service(Trigger, "/sim/panel/press_reset", self._press_reset)
        self.create_service(SetBool, "~/mute", self._hook(fh.MUTE))
        self.create_service(SetBool, "~/freeze", self._hook(fh.FREEZE))
        self.create_service(SetBool, "~/invalid", self._set_invalid)
        self.create_timer(1.0 / self.get_parameter("rate_hz").value, self._tick)
        self.get_logger().info(f"panel: {'AUTO' if self.auto else 'MANUAL'}")

    def _set_mode(self, req, res):
        self.auto = bool(req.data)
        res.success, res.message = True, f"selector -> {'AUTO' if self.auto else 'MANUAL'}"
        self.get_logger().info(res.message)
        return res

    def _set_valid(self, req, res):
        self.valid = bool(req.data)
        res.success, res.message = True, f"panel image {'valid' if self.valid else 'INVALID'}"
        return res

    def _set_estop(self, req, res):
        self.estop = bool(req.data)
        res.success, res.message = True, f"E-stop {'PRESSED' if self.estop else 'released'}"
        self.get_logger().info(res.message)
        return res

    def _hook(self, name: str):
        def srv(req, res):
            res.success, res.message = True, self._hk.set(name, req.data)
            self.get_logger().warn(f"sim fault: {res.message}")
            return res
        return srv

    def _set_invalid(self, req, res):
        self._flag_invalid = bool(req.data)
        res.success, res.message = True, f"panel valid flag {not req.data}"
        self.get_logger().warn(f"sim fault: {res.message}")
        return res

    def _press_start(self, _req, res):
        self._start_pending = True
        res.success, res.message = True, "Start pressed"
        self.get_logger().info(res.message)
        return res

    def _press_reset(self, _req, res):
        self._reset_pending = True
        res.success, res.message = True, "Reset pressed"
        return res

    def _tick(self) -> None:
        if not self.valid:
            return  # a dead DIO link publishes nothing: consumers see staleness
        m = PanelState()
        m.valid = not self._flag_invalid
        m.mode_auto = self.auto
        m.start_edge, self._start_pending = self._start_pending, False
        m.reset_edge, self._reset_pending = self._reset_pending, False
        if hasattr(m, "emergency"):  # amr_interfaces built with the E-stop fields (2026-11-16)
            m.estop_ok = not self.estop
            note = self.emergency.step(time.monotonic(),
                                       emergency.Inputs(bool(m.valid), m.estop_ok, m.reset_edge, None))
            if note:
                self.get_logger().info(note)
            m.emergency = self.emergency.state
        self.seq += 1
        m.seq = self.seq
        levels = [bool(self.get_parameter(n).value) for n in PENDANT_PARAMS]
        m.pendant_fwd, m.pendant_rvs, m.pendant_left, m.pendant_right = panel_core.pendant_intent(*levels)
        t = time.monotonic() - self._t0
        m = self._hk.out(t, m)
        if m is None:
            return
        if self._hk.mode(t) == fh.FREEZE:
            m.start_edge = m.reset_edge = False  # a frozen image carries no new press
        m.seq = self.seq  # the link still counts on
        m.header.stamp = self.get_clock().now().to_msg()
        self._pub.publish(m)
        if self._ui.due(time.monotonic()):
            self._pub_ui.publish(m)


def main(args=None) -> None:
    run(FakePanel, args)


if __name__ == "__main__":
    main()
