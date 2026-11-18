"""panel_node (T12): the real operator panel and the horns, over the DIO island.

    DIO discrete inputs (Modbus TCP, drivers/dio.DioLink thread)
        -> /amr/panel_state (PanelState, once per DIO acquisition + a 50 ms fallback,
           WP-C3): debounced Reset/Start edges and levels, AUTO/MANUAL selector,
           valid=false while comms are down or before the first baseline; jog
           pendant direction levels
    /drives/status `turning` + /amr/mux_state + /amr/line_state + /amr/run_state
        -> dio.motion_on / alarm_on coils, renewed every tick, expiring on their
           own (config.HORN_HOLD_S) if this node dies. The legacy horn.* engine
           (/cmd_wheel_vel) is retired (lean plan D16, WP-C7, 2026-11-16)
    the DIO link (dio.DioLink snapshot)
        -> /amr/device_health (DeviceHealth `dio`, 2 Hz + edges; unified plan WP-H1)
    DI09 (panel.di_estop, Flexi Soft Q3, HIGH = E-stop) + Reset + /drives/status
        -> PanelState.estop_ok / emergency (amr_base/emergency.py) and the ESTOP* events, every
           transition logged; while not NORMAL every coil this node drives is LOW
           (emergency-suite plan Part B, 2026-11-16)

The panel is the ONLY thing that can authorise motion on the ROS side (the mux
takes authority from /amr/panel_state, the executor needs a Start edge under
AUTO). This node reports what the operator did; it decides nothing about
motion. It has no services and no parameters that could fake an edge.

Never runs beside another DIO owner: two writers on the same coil (ownerlock).
"""

from __future__ import annotations

import time

from agv_core import (
    config,
    health,
    ownerlock,  # repo module: core/ownerlock.py
)
from agv_core.drivers import dio  # repo module: drivers/dio.py

from amr_base import emergency, health_pub, panel_io
from amr_base.lean_node import UI_PERIOD_FAST_S, LeanNode, UiThrottle, run
from amr_base.qos import LATCHED, RELIABLE_1
from amr_interfaces.msg import (
    DriveStatus,
    Event,
    IoImage,
    LineState,
    MuxState,
    PanelState,
    RunState,
    WheelStates,
)

WHEELS_FRESH_S = 0.3  # /drives/status is 10 Hz: three periods
MUX_FRESH_S = 0.5  # /amr/mux_state is 10 Hz
LINE_FRESH_S = 3.0  # /amr/line_state: on change and at 1 Hz; older = no stop call
TURNING_RAD_S = panel_io.TURNING_RAD_S  # wheel speed above which a motor counts as turning
# DriveStatus.turning (WP-C7): appended 2026-11-16. A message built before it falls back to the
# 41 Hz /wheel_states, as before, so the motion lamp never goes dark on a half-rebuilt install.
HAS_TURNING = "turning" in DriveStatus.get_fields_and_field_types()
# PanelState.estop_ok / emergency (emergency-suite plan Part B): appended 2026-11-16. An install whose
# amr_interfaces is not rebuilt yet publishes without them; the consumers then read NORMAL (0).
HAS_EMERGENCY = "emergency" in PanelState.get_fields_and_field_types()
_EVENT_LEVEL = {"info": Event.INFO, "warn": Event.WARN, "error": Event.ERROR}


class PanelNode(LeanNode):
    def __init__(self, link=None) -> None:
        super().__init__("panel_node", start_parameter_services=False)  # WP-C11: nobody sets params live
        self.declare_parameter("rate_hz", 50.0)  # PANEL_DEBOUNCE_SCANS was tuned at canworker's 50 Hz

        self.link = link or dio.DioLink()
        self.adapter = panel_io.PanelAdapter()
        self._pub = self.create_publisher(PanelState, "/amr/panel_state", 10)
        self._gate = panel_io.PublishGate()  # once per acquisition + fallback (WP-C3)
        # 10 Hz copy for displays (CPU, 2026-10-02): the web shows the selector at 2 Hz.
        # Edges ride only the full topic - nothing that acts on Start/Reset reads this one.
        self._pub_ui = self.create_publisher(PanelState, "/amr/panel_state_ui", 10)
        self._ui = UiThrottle(UI_PERIOD_FAST_S)
        self._pub_io = self.create_publisher(IoImage, "/amr/io", 5)
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._event_seq = 0
        self._health = health_pub.Outbox(self)  # DeviceHealth `dio` (WP-H1), reporting only
        self._health_t0 = time.monotonic()
        self._io_every = 10  # 50 Hz tick -> 5 Hz image (unified plan §7.1)
        self._io_n = 0
        # dio.motion_on outputs follow the measured wheels: drive_node's DriveStatus.turning (10 Hz),
        # not the 41 Hz /wheel_states (WP-C7, cpu-load plan C#15). Nothing else here reads either.
        # /drives/status also carries the drive states the emergency machine reads (STO held).
        self.create_subscription(DriveStatus, "/drives/status", self._on_drives, RELIABLE_1)
        if not HAS_TURNING:
            from rclpy.qos import qos_profile_sensor_data  # noqa: PLC0415

            self.create_subscription(WheelStates, "/wheel_states", self._on_wheels, qos_profile_sensor_data)
        self._turning = False
        self._wheels_t: float | None = None
        # The PC's emergency picture (amr_base/emergency.py): starts NORMAL; only DI09 leaves it.
        self.emergency = emergency.Emergency(config.PANEL_ESTOP_RESET_TIMEOUT_S)
        self._drive_states: tuple[str, str, str] = ("", "", "")  # left, right, link_state
        self._drives_t: float | None = None
        # dio.alarm_on: the run states and the scanner fields as the mux sees them.
        self.create_subscription(MuxState, "/amr/mux_state", self._on_mux, RELIABLE_1)
        self.create_subscription(LineState, "/amr/line_state", self._on_line, LATCHED)
        self.create_subscription(RunState, "/amr/run_state", self._on_run, LATCHED)
        self._mux: MuxState | None = None
        self._mux_t: float | None = None
        self._line_state: int | None = None
        self._line_cause = ""
        self._line_where = ""
        self._line_t: float | None = None
        self._call_since: float | None = None  # the stop call's phase origin; None = not calling
        self._run_state: int | None = None
        self._run_premove = False
        self._alarm = False

        if not config.DIO_ENABLED:
            self.get_logger().warn("dio.enabled is false in the profile: no panel, no horn, valid=false")
        if not config.PANEL_ENABLED:
            self.get_logger().warn("panel.enabled is false in the profile: publishing valid=false forever")
        self._dio_lock = ownerlock.acquire("dio", "panel_node")  # before any Modbus I/O (plan §9.2)
        self.link.start()
        self._dio_retried = 0
        self.create_steady_timer(1.0 / float(self.get_parameter("rate_hz").value), self._tick)
        self.get_logger().info(
            f"panel on DIO {config.DIO_IP}:{config.DIO_PORT}: reset DI{config.PANEL_DI_RESET}, "
            f"start DI{config.PANEL_DI_START}, selector DI{config.PANEL_DI_AUTO} "
            f"(ON = {'AUTO' if config.PANEL_AUTO_WHEN_ON else 'MANUAL'}), "
            f"manual arm DI{config.PANEL_DI_MANUAL_ARM}, "
            + (f"E-stop DI{config.PANEL_DI_ESTOP:02X} (active "
               f"{'HIGH' if config.PANEL_ESTOP_ACTIVE_HIGH else 'LOW'} over "
               f"{config.PANEL_ESTOP_CONFIRM_SCANS} scans); "
               if config.PANEL_ESTOP_SIGNAL_ENABLED else
               f"E-stop DI{config.PANEL_DI_ESTOP:02X} BYPASSED (panel.estop_signal_enabled false): "
               "known only from torque loss; ")
            + (
                f"pendant fwd DI{config.PENDANT_DI_FWD}, "
                f"rvs DI{config.PENDANT_DI_RVS}, left DI{config.PENDANT_DI_LEFT}, "
                f"right DI{config.PENDANT_DI_RIGHT}"
                if config.PENDANT_ENABLED
                else "pendant disabled"
            )
        )

    # -- inputs --

    def _on_mux(self, m: MuxState) -> None:
        self._mux, self._mux_t = m, time.monotonic()

    def _on_line(self, m: LineState) -> None:
        self._line_state = int(m.state)
        self._line_cause = m.hold_cause
        self._line_where = m.stop_where or m.station
        self._line_t = time.monotonic()

    def _on_run(self, m: RunState) -> None:
        self._run_state = int(m.state)
        self._run_premove = bool(m.premove)

    def _on_wheels(self, m: WheelStates) -> None:  # only on a DriveStatus without `turning`
        self._turning = panel_io.wheels_turning(m.left_valid, m.left_vel_rad_s,
                                                m.right_valid, m.right_vel_rad_s)
        self._wheels_t = time.monotonic()

    def _on_drives(self, m: DriveStatus) -> None:
        now = time.monotonic()
        self._drive_states = (str(m.left_state), str(m.right_state), str(m.link_state))
        self._drives_t = now
        if HAS_TURNING:
            self._turning = bool(m.turning)
            self._wheels_t = now

    # -- tick --

    def _tick(self) -> None:
        snap = self.link.snapshot()
        now = time.monotonic()
        # The link as it is, before the panel.enabled override below: the coils still use it.
        up_s = now - self._health_t0
        self._health.publish(now, lambda: [health.dio(up_s, snap, config.PANEL_SOURCE_MAX_AGE_S)])
        retried = snap.get("retried", 0)
        if retried != self._dio_retried:
            # No stop came of it, but a module doing this often is worth hearing about.
            self._dio_retried = retried
            text = f"DIO scan retried, no stop ({retried} so far): {snap.get('last_retry')}"
            self.get_logger().warn(text)
            self._event(Event.WARN, "DIO_SCAN_RETRIED", text)  # a code, not a PANEL text (WP-H2)
        if not config.PANEL_ENABLED:
            snap = dict(snap, comms_ok=False)
        # The pendant mask follows the state the last tick ended in (panel_io.PanelAdapter.tick).
        frame = self.adapter.tick(snap, normal=self.emergency.state == emergency.NORMAL)
        if frame.changed:
            self.get_logger().info(frame.changed)
        # The link edge under its own code (WP-H2): nothing downstream matches on the text.
        if frame.link == panel_io.LINK_LOST:
            self._event(Event.WARN, "DIO_LINK_LOST", f"{frame.link_text}, {config.DIO_IP}:{config.DIO_PORT}")
        elif frame.link == panel_io.LINK_OK:
            self._event(Event.INFO, "DIO_LINK_OK", f"{frame.link_text}, {config.DIO_IP}:{config.DIO_PORT}")
        if frame.other:
            self._event(Event.WARN if frame.warn else Event.INFO, "PANEL", frame.other)
        moved = self._emergency_step(frame, now)
        normal = self.emergency.state == emergency.NORMAL
        self._io_n = (self._io_n + 1) % self._io_every
        if self._io_n == 0:
            self._publish_io(snap)
        m = PanelState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.valid = frame.valid
        m.mode_auto = frame.mode_auto
        m.start_edge = frame.start_edge
        m.reset_edge = frame.reset_edge
        m.seq = frame.seq
        m.pendant_fwd, m.pendant_rvs, m.pendant_left, m.pendant_right = frame.pendant
        m.manual_arm = frame.manual_arm
        if hasattr(m, "start_held"):  # amr_interfaces not rebuilt yet: publish without the levels
            m.start_held, m.reset_held = frame.start_held, frame.reset_held
        if HAS_EMERGENCY:
            m.estop_ok, m.emergency = frame.estop_ok, self.emergency.state
        # every acquisition (so every edge) once, a state transition on its tick, else a 50 ms repeat
        if self._gate.due(now, frame, force=moved):
            self._pub.publish(m)
        if self._ui.due(time.monotonic()):
            self._pub_ui.publish(m)

        # dio.motion_on (DO00, DO08): on while the motors turn, off when they do not, in any
        # mode. Feedback older than WHEELS_FRESH_S counts as not turning.
        fresh = self._wheels_t is not None and time.monotonic() - self._wheels_t <= WHEELS_FRESH_S

        # dio.alarm_on (DO01): AUTO run active and a scanner field occupied, or the
        # pre-move warning after a Start.
        mux = self._mux
        mux_fresh = mux is not None and time.monotonic() - self._mux_t <= MUX_FRESH_S
        hazard = normal and panel_io.alarm_wanted(
            frame.valid and frame.mode_auto, self._line_state, self._run_state,
            mux_fresh and mux.field_fresh,
            bool(mux.protective_clear) if mux_fresh else True,
            bool(mux.warning_active) if mux_fresh else False,
            run_premove=self._run_premove,
        )
        # The stop call (manuals/stop-call-alarm-plan.md): parked waiting for attach / release and a
        # physical Start, the same coil pulses. A hazard above keeps it continuous.
        now = time.monotonic()
        line_fresh = self._line_t is not None and now - self._line_t <= LINE_FRESH_S
        call = normal and config.DIO_CALL_ALARM_ON_S > 0.0 and panel_io.call_wanted(
            frame.valid and frame.mode_auto, self._line_state, self._line_cause, line_fresh)
        if call != (self._call_since is not None):
            self._call_since = now if call else None
            text = (f"stop call alarm on: {self._line_cause} at {self._line_where or '?'}" if call
                    else "stop call alarm off")
            self.get_logger().info(text)
            self._event(Event.INFO, "CALL_ALARM", text)
        alarm = hazard or (call and panel_io.call_phase(
            now, self._call_since, config.DIO_CALL_ALARM_ON_S, config.DIO_CALL_ALARM_OFF_S))
        # dio.alarm_on, then dio.motion_on (the movement horn, DO00, gives way to the alarm horn).
        # Not NORMAL: every coil LOW, the pre-move warning and the stop call included (emergency plan §4).
        for ch, on in panel_io.coil_image(normal, alarm, self._turning and fresh).items():
            self.link.set_coil(ch, on, config.HORN_HOLD_S)
        if hazard != self._alarm:  # the pulse logs its own on/off above, not every beat
            self._alarm = hazard
            self.get_logger().info(f"alarm horn {'on' if hazard else 'off'}")

    def _emergency_step(self, frame: panel_io.PanelFrame, now: float) -> bool:
        """Run the emergency state machine; log every transition and report it. True on a transition."""
        e = self.emergency
        left, right, link = self._drive_states
        age = None if self._drives_t is None else now - self._drives_t
        prev = e.state
        note = e.step(now, emergency.Inputs(
            frame.valid, frame.estop_ok, frame.reset_edge, emergency.sto_held(left, right, link, age)))
        if not note:
            return False
        # Two call sites, not one picked at run time: rclpy refuses a logging call site whose
        # severity changes between calls (ValueError; it killed kyb's panel_node, 2026-10-30).
        if e.state == emergency.NORMAL:
            self.get_logger().info(note)
        else:
            self.get_logger().warn(note)
        ev = panel_io.emergency_event(e.state, prev, note)
        if ev:
            self._event(_EVENT_LEVEL[ev[0]], ev[1], ev[2])
        return True

    def _event(self, level: int, code: str, text: str) -> None:
        self._pub_event.publish(self.build_event("panel_node", level, code, text))

    def _publish_io(self, snap: dict) -> None:
        """The owner's full I/O image (unified plan §7): requested vs readback kept apart."""
        m = IoImage()
        m.header.stamp = self.get_clock().now().to_msg()
        m.comms_ok = bool(snap.get("comms_ok"))
        age = snap.get("rx_age_s")
        m.rx_age_s = -1.0 if age is None else float(age)
        m.di_names = list(snap.get("di_names", []))
        m.di = [bool(x) for x in snap.get("di", [])]
        m.do_names = list(snap.get("do_names", []))
        m.do_readback = [bool(x) for x in snap.get("do", [])]
        wanted = snap.get("commanded", {})
        m.do_requested = [bool(wanted.get(str(i), False)) for i in range(len(m.do_names))]
        m.scans, m.errors, m.writes = (
            int(snap.get("scans", 0)),
            int(snap.get("errors", 0)),
            int(snap.get("writes", 0)),
        )
        m.detail = str(snap.get("detail", ""))
        self._pub_io.publish(m)

    def close(self) -> None:
        try:
            self.link.stop()  # quiesces the coil low before the socket closes
        except Exception:  # noqa: BLE001
            pass


def main(args=None) -> None:
    run(PanelNode, args, before_destroy=lambda n: n.close(), catch_runtime=False)


if __name__ == "__main__":
    main()
