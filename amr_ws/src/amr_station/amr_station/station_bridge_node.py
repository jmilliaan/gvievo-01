"""station_bridge_node: the MQTT link to the station PC. A subset of VDA5050 3.0.0, NOT compliant
(manuals/station-call-plan.md, contract section 10).

Launched in base only with station.enabled. Motion authority: one service action, `depart`, which the job
may refuse. It publishes MQTT and /amr/events, and calls only /amr/line/order. It has no lease, no
command topic and no panel input, and it cannot start, resume, stop or pause anything else. Stopping is
physical. test_bridge_authority pins this.

Threads (plan 12.4): paho's network thread only queues bytes (amr_station.mqtt_link) and triggers a
GuardCondition (WP-C17, 2026-11-16). Everything else runs on this executor: the drain, woken by that
guard on every message, connect, drop and SUBACK (no 20 Hz poll); a 10 Hz state timer, which also runs
the drain for the time-based parts (ONLINE republish, SUBACK retry, the home alarm, never-up);
subscriptions; call_async with no wait. No parameter services (nothing sets one live).

Failure modes: broker or Wi-Fi down: nothing published, retried every 2 s, an active order finishes
because the job has no network input. Bridge crash: respawned in 5 s, headerId from 0, STARTUP until an
OrderState arrives. Line layer down: STARTUP, and an order is refused LINE_LAYER_DOWN. paho missing or
credentials wrong: STATION_LINK_DOWN, exit, respawn. In every case nothing is stored to move later.

Health (unified plan WP-H1): the link is DeviceHealth `station_link` on /amr/device_health, at 2 Hz and
on every edge, from the 10 Hz state timer. Reporting only, like the events above.
"""

from __future__ import annotations

import time

from agv_core import alarms, health, mission, paths
from agv_core import config as vehicle_config

from amr_base import emergency, health_pub
from amr_base.lean_node import LeanNode, run
from amr_base.qos import LATCHED, RELIABLE_1
from amr_interfaces.msg import Event, LineState, ModeState, MuxState, OrderState, PanelState
from amr_interfaces.srv import LineTeach
from amr_station import bridge_core, mqtt_link, vda_state

ORDER_FIELDS = [f for f in OrderState.get_fields_and_field_types() if f != "header"]
PANEL_FRESH_S = 0.5  # /amr/panel_state_ui is 10 Hz
NEVER_UP_S = 5.0


class StationBridge(LeanNode):
    def __init__(self) -> None:
        super().__init__("station_bridge", start_parameter_services=False)
        self.declare_parameter("state_dir", paths.state_dir())
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._health = health_pub.Outbox(self)
        self._health_t0 = time.monotonic()
        self._link_up = None
        self._down_t = None  # when the link last went down, for the "back after" of the next up
        self._home_alarm = bridge_core.HomeLinkAlarm()
        site = mission.load_site(str(vehicle_config.TAPE_LOC_SITE_MISSION))
        self.core = bridge_core.BridgeCore(
            site, vehicle_config.STATION_MANUFACTURER, vehicle_config.STATION_SERIAL_NUMBER,
            pairs="mw2_status" in ORDER_FIELDS,
        )
        self._site = site
        self._mode, self._panel, self._panel_t, self._line, self._mux = None, None, None, None, None
        self._generation = None
        self._client = self.create_client(LineTeach, "/amr/line/order")
        self.create_subscription(OrderState, "/amr/line/order_state", self._on_order_state, LATCHED)
        self.create_subscription(LineState, "/amr/line_state", self._on_line, LATCHED)
        self.create_subscription(ModeState, "/amr/mode_state", self._on_mode, LATCHED)
        self.create_subscription(PanelState, "/amr/panel_state_ui", self._on_panel, 10)
        self.create_subscription(MuxState, "/amr/mux_state", self._on_mux, RELIABLE_1)
        try:
            user, password = mqtt_link.load_credentials(str(self.get_parameter("state_dir").value))
            self.link = mqtt_link.MqttLink(
                vehicle_config.STATION_BROKER_HOST,
                vehicle_config.STATION_BROKER_PORT,
                vehicle_config.STATION_MANUFACTURER,
                vehicle_config.STATION_SERIAL_NUMBER,
                user,
                password,
            )
        except (mqtt_link.CredentialsError, ImportError) as e:
            self._event("STATION_LINK_DOWN", f"station bridge cannot start: {e}")
            now = time.monotonic()
            self._health.publish(now, [health.station_link(
                bool(vehicle_config.STATION_ENABLED), now - self._health_t0, False, False, failed=str(e))])
            self.get_logger().error(f"station bridge cannot start: {e}")
            raise SystemExit(1) from e
        self._started_t = time.monotonic()
        # The drain runs when paho has something (a message, an edge), on this executor's next spin.
        self.link.on_wake = self.create_guard_condition(self._drain).trigger
        self.link.start()
        self.create_timer(0.1, self._state_tick)
        self.get_logger().info(
            f"station bridge: broker {self.link.host}:{self.link.port}, topics {self.link.topics['state']}"
        )

    def _event(self, code: str, text: str) -> None:
        self._pub_event.publish(self.build_event("station_bridge", alarms.level(code), code, text))

    # -- ROS inputs ------------------------------------------------------------------------------
    def _on_mode(self, m) -> None:
        self._mode = m
        self._generation = int(m.generation)

    def _on_panel(self, m) -> None:
        self._panel, self._panel_t = m, time.monotonic()

    def _on_line(self, m) -> None:
        if self._generation is None or int(m.generation) == self._generation:
            self._line = m

    def _on_mux(self, m) -> None:
        self._mux = m

    def _on_order_state(self, m) -> None:
        if self._generation is not None and int(m.generation) != self._generation:
            return
        self.core.on_order_state({f: getattr(m, f) for f in ORDER_FIELDS}, time.monotonic())

    # -- MQTT in ---------------------------------------------------------------------------------
    def _drain(self) -> None:
        """Every queued message, and the link's edges. Run by the wake and by the 10 Hz state tick;
        several messages behind one wake are all handled (the guard's triggers coalesce)."""
        change = self.link.service()
        if change == "up":
            if self._link_up:  # the drop and the reconnect both fell between two calls
                self._event("STATION_LINK_UP", f"link reconnected after a brief drop, {self._where()}")
            self._set_link(True)
            self._state_tick(force=True)
        elif change == "down":
            self._set_link(False)
        now = time.monotonic()
        self._home_alarm_tick(now)
        if self._link_up is None and not self.link.connected and now - self._started_t > NEVER_UP_S:
            self._set_link(False)  # a broker that never answered says nothing else
        for topic, payload, retained in self.link.take():
            if topic == self.link.topics["order"]:
                self._ask(self.core.on_order(payload, retained, now), refuse_as=True)
            elif topic == self.link.topics["instantActions"]:
                for act in self.core.on_instant(payload, retained):
                    self._ask(act, refuse_as=False)

    def _set_link(self, up: bool) -> None:
        if up != self._link_up:
            self._link_up = up
            now, where = time.monotonic(), self._where()
            if up:
                back = f" after {now - self._down_t:.0f} s" if self._down_t is not None else ""
                self._down_t = None
                self._event("STATION_LINK_UP", f"link to the broker back{back}, {where}")
            else:
                self._down_t = now
                self._event(
                    "STATION_LINK_DOWN", f"no link to the broker {self.link.host}:{self.link.port}, {where}"
                )
            self.get_logger().info(f"station link {'up' if up else 'down'}, {where}")

    def _where(self) -> str:
        """The trip position, so the next real trip's log shows where the link went and came back."""
        m = self._line
        if m is None:
            return "line layer not reporting"
        place = f"S {m.loc_s_m:.1f} m on {m.loc_leg}" if m.loc_leg else "no tape position"
        return f"{place}, {'at home' if m.at_home else 'away from home'}"

    def _home_alarm_tick(self, now: float) -> None:
        at_home = self._line is not None and bool(self._line.at_home)
        act = self._home_alarm.update(now, at_home, self.link.ready)
        if act == "raise":
            self._event("STATION_LINK_HOME", f"at home with no link to {self.link.host}:{self.link.port}")
        elif act == "clear":
            self._pub_event.publish(
                self.build_event("station_bridge", 0, "STATION_LINK_HOME", "cleared: link back, or left home")
            )

    def _ask(self, action, refuse_as: bool) -> None:
        """Hand one action to the job, with no wait. Its result comes back in OrderState."""
        if action is None:
            return
        verb, a, b = action
        if not self._client.service_is_ready():
            if refuse_as:
                self.core.refuse("MOBILE_ROBOT_NOT_AVAILABLE", a, "LINE_LAYER_DOWN")
            return
        self._client.call_async(LineTeach.Request(action=verb, arg=f"{a} {b}"))

    # -- MQTT out --------------------------------------------------------------------------------
    def _state_tick(self, force: bool = False) -> None:
        if not force:
            self._drain()  # the time-based half of the link (it was a 20 Hz timer of its own)
        now = time.monotonic()
        self._health.publish(now, lambda: [health.station_link(
            bool(vehicle_config.STATION_ENABLED), now - self._health_t0, self.link.connected, self.link.ready,
            reconnects=max(0, getattr(self.link, "connections", 0) - 1),
            down_for=None if self._down_t is None else now - self._down_t,
        )])
        m, line, mux, panel = self._mode, self._line, self._mux, self._panel
        panel_ok = panel is not None and self._panel_t is not None and now - self._panel_t <= PANEL_FRESH_S
        view = self.core.view(
            now,
            mode=int(m.mode) if m is not None else None,
            layer_ready=bool(m.layer_ready) if m is not None else False,
            panel_valid=bool(panel_ok and panel.valid),
            panel_auto=bool(panel_ok and panel.mode_auto),
            # E7: the emergency state as a status field only (None: no fresh, valid image, an
            # amr_interfaces without the field, or the E-stop signal bypassed, plan §9)
            emergency=emergency.reading(panel, panel_ok),
            line_state=int(line.state) if line is not None else None,
            hold_cause=str(line.hold_cause) if line is not None else "",
            line_code=str(line.code) if line is not None else "",
            field_fresh=bool(mux.field_fresh) if mux is not None else False,
            protective_clear=bool(mux.protective_clear) if mux is not None else False,
        )
        body = vda_state.build_state(view, self._site)
        if (self.core.state_due(body, now) or force) and self.link.connected:
            header_id = self.link.publish_state(body)
            if header_id is not None:
                self.core.ring.sent(header_id, now)


def _stop(node) -> None:
    node.link.stop()


def main() -> None:
    run(StationBridge, before_destroy=_stop)


if __name__ == "__main__":
    main()
