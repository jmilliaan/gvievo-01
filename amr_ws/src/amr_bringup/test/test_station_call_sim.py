"""P7 of the station call plan: the whole chain in simulation. Opt-in: AMR_SIM_TESTS=1 and AMR_MQTT_TESTS=1.

    station (paho, the contract's 6.1 table) <-> Mosquitto on loopback <-> the real station_bridge_node
    <-> the ROS graph <-> a real FollowJob on the site_fixture plant (calling_world), with the panel and
    the rear lidar as that plant's inputs.

Sim tests check mechanisms: tolerances are settled on the vehicle. The last test uses the real
line_follow_node, on no site mission, for its service and OrderState wiring over the same broker.
"""

import json
import os
import sys
import time

import pytest

if os.environ.get("AMR_SIM_TESTS") != "1" or os.environ.get("AMR_MQTT_TESTS") != "1":
    pytest.skip("set AMR_SIM_TESTS=1 and AMR_MQTT_TESTS=1", allow_module_level=True)
os.environ["ROS_DOMAIN_ID"] = "86"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (
    os.path.abspath(os.path.join(SRC, "..", "..")),
    os.path.join(SRC, "amr_line"),
    os.path.join(SRC, "amr_sim"),
    os.path.join(SRC, "amr_base"),
    os.path.join(SRC, "amr_station"),
    os.path.join(SRC, "amr_line", "test"),
    os.path.join(SRC, "amr_station", "test"),
):
    if p not in sys.path:
        sys.path.insert(0, p)

import rclpy  # noqa: E402
from agv_core import config  # noqa: E402
from calling_world import CallingWorld, go_on, parked_at, spin  # noqa: E402
from contract import call_state  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from site_fixture import graph, site  # noqa: E402
from test_mosquitto_loop import PORT, USERS, Broker, mqtt  # noqa: E402

from amr_base.lean_node import LeanNode  # noqa: E402
from amr_base.qos import LATCHED, RELIABLE_1  # noqa: E402
from amr_interfaces.msg import (  # noqa: E402
    LineState,
    ModeState,
    MuxState,
    OrderState,
    PanelState,
    TrolleyState,
)
from amr_interfaces.srv import LineTeach  # noqa: E402
from amr_line import job as lj  # noqa: E402
from amr_station import station_bridge_node as sb  # noqa: E402
from amr_station import vda_order as vo  # noqa: E402

T = "vda5050/v3/gvi/agv1/"
TROLLEY = {"absent": TrolleyState.ABSENT, "present": TrolleyState.PRESENT, "unknown": TrolleyState.UNKNOWN}
TICK_WALL_S = 0.0015


class Station:
    """The station's side of the contract: orders with a fresh seenStateHeaderId, and the 6.1 table."""

    def __init__(self, m):
        self.m = m
        self.state = None
        self.seen = []
        self.shown = False
        self.order_id = None
        self.c = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="gvi-station",
            protocol=mqtt.MQTTv311,
        )
        self.c.username_pw_set("station", USERS["station"])
        self.c.on_connect = lambda c, _u, _f, _rc, _p: c.subscribe(T + "state")
        self.c.on_message = self._msg
        self.c.reconnect_delay_set(1, 1)
        self.c.connect("127.0.0.1", PORT, keepalive=10)
        self.c.loop_start()

    def _msg(self, _c, _u, msg):
        self.state = json.loads(msg.payload)
        if self.order_id and self.state["operatingMode"] != "STARTUP":
            self.shown = self.shown or self.state["orderId"] == self.order_id
            row = call_state(self.state, self.order_id, self.shown)
            if not self.seen or self.seen[-1] != row:
                self.seen.append(row)

    def send(self, order_id, machine="M1"):
        self.order_id, self.shown, self.seen = order_id, False, []
        doc = {
            "headerId": 1,
            "timestamp": "t",
            "version": "3.0.0",
            "manufacturer": "gvi",
            "serialNumber": "agv1",
            "orderId": order_id,
            "orderUpdateId": 0,
            "seenStateHeaderId": self.state["headerId"],
            **vo.canonical_order(self.m, machine, order_id),
        }
        self.c.publish(T + "order", json.dumps(doc))

    def errors(self):
        return [e["errorType"] for e in (self.state or {}).get("errors", [])]

    def close(self):
        self.c.disconnect()
        self.c.loop_stop()


class Host(LeanNode):
    """What the line layer, supervisor, panel and mux publish, from the plant."""

    def __init__(self):
        super().__init__("sim_host")
        self.world = None
        self.publishing = True
        self.pub_order = self.create_publisher(OrderState, "/amr/line/order_state", LATCHED)
        self.pub_line = self.create_publisher(LineState, "/amr/line_state", LATCHED)
        self.pub_mode = self.create_publisher(ModeState, "/amr/mode_state", LATCHED)
        self.pub_panel = self.create_publisher(PanelState, "/amr/panel_state_ui", 10)
        self.pub_mux = self.create_publisher(MuxState, "/amr/mux_state", RELIABLE_1)
        self.create_service(LineTeach, "/amr/line/order", self._srv)
        self.create_timer(0.1, self._slow)

    def _srv(self, req, res):
        a, b = req.arg.split()
        res.ok, res.message = (
            self.world.job.order_request(a, b)
            if req.action == "depart"
            else self.world.job.order_cancel(a, b)
        )
        return res

    def publish(self):
        w = self.world
        if w is None or not self.publishing:
            return
        m = OrderState()
        for k, v in w.job.order_snapshot().items():
            setattr(m, k, v)
        m.driving = w.job.state == lj.RUNNING
        m.trolley, m.rear_field = TROLLEY[w.trolley], TrolleyState.FIELD_CLEAR if w.rear_clear else 0
        self.pub_order.publish(m)
        self.pub_line.publish(LineState(state=w.job.state, hold_cause=w.job.hold_cause, code="X"))

    def _slow(self):
        self.pub_mode.publish(ModeState(mode=ModeState.LINE, layer_ready=True))
        self.pub_panel.publish(PanelState(valid=True, mode_auto=True))
        self.pub_mux.publish(MuxState(field_fresh=True, protective_clear=True))


class HostWorld(CallingWorld):
    """Every tick of the plant also turns the ROS graph, a little faster than real time."""

    pump = None

    def tick(self, **over):
        out = super().tick(**over)
        if self.pump:
            self.pump()
        return out


class Rig:
    def __init__(self, tmp, monkeypatch):
        for k, v in (
            ("STATION_ENABLED", True),
            ("STATION_BROKER_HOST", "127.0.0.1"),
            ("STATION_BROKER_PORT", PORT),
        ):
            monkeypatch.setattr(config, k, v)
        self.m = site(trip_calls=1)
        monkeypatch.setattr(sb.mission, "load_site", lambda _n: self.m)
        self.state_dir = tmp / "state"
        self.state_dir.mkdir()
        cred = self.state_dir / "station-mqtt.json"
        cred.write_text(json.dumps({"username": "agv1", "password": USERS["agv1"]}))
        cred.chmod(0o600)
        self.broker = Broker(tmp)
        self.broker.start()
        rclpy.init()
        self.ex = SingleThreadedExecutor()
        self.host = Host()
        self.ex.add_node(self.host)
        self.bridge = None
        self.start_bridge()
        self.station = Station(self.m)
        self.world = self.new_world()

    def start_bridge(self):
        # The launch passes state_dir as a parameter; here, with the same override rclpy would apply.
        real_declare = LeanNode.declare_parameter

        def declare(node, name, value=None, *a, **kw):
            return real_declare(node, name, str(self.state_dir) if name == "state_dir" else value, *a, **kw)

        LeanNode.declare_parameter = declare
        try:
            self.bridge = sb.StationBridge()
        finally:
            del LeanNode.declare_parameter
        self.ex.add_node(self.bridge)

    def kill_bridge(self):
        """As a crash: no OFFLINE, no orderly disconnect from the job's point of view."""
        self.ex.remove_node(self.bridge)
        self.bridge.link.c.loop_stop()
        self.bridge.link.c._sock_close()
        self.bridge.destroy_node()
        self.bridge = None

    def new_world(self):
        w = HostWorld(self.m, graph(self.m))
        w.pump = self.pump
        self.host.world = w
        self.world = w
        w.drive(5.2)
        return w

    def pump(self):
        self.host.publish()
        self.ex.spin_once(timeout_sec=0)
        time.sleep(TICK_WALL_S)

    def wait(self, cond, seconds=8.0):
        """Wall time, with the plant still ticking."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.world.tick()
            if cond():
                return True
        return False

    def close(self):
        self.station.close()
        if self.bridge is not None:
            self.bridge.link.stop()
            self.bridge.destroy_node()
        self.host.destroy_node()
        rclpy.shutdown()
        self.broker.stop()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch)
    assert r.wait(lambda: r.station.state is not None and r.station.state["operatingMode"] == "AUTOMATIC"), (
        r.station.state
    )
    assert r.wait(lambda: "NOT_READY" not in r.station.errors()), r.station.state
    yield r
    r.close()


def accepted(r, order_id):
    r.station.send(order_id)
    assert r.wait(lambda: r.world.job.state == lj.ARMED, 3.0), (r.world.job.reason, r.station.state)


def press(r, trolley):
    r.world.trolley = trolley
    r.world.drive(0.1)
    go_on(r.world)


def test_a_full_call_in_sim(rig):
    r, w = rig, rig.world
    accepted(r, "O1")
    parked_at(w, "ATT")
    assert r.wait(lambda: r.station.seen[-1:] == ["AT_PICKUP"])
    w.press_start()  # no trolley: refused
    assert r.wait(lambda: "START_REFUSED" in r.station.errors()), r.station.state
    assert w.job.state == lj.HOLD and r.station.seen[-1] == "AT_PICKUP"
    press(r, "present")
    parked_at(w, "MW-1")
    press(r, "absent")
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
    spin(w)
    parked_at(w, "ME-1")
    press(r, "present")
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    assert r.wait(lambda: r.station.seen[-1:] == ["Closed"]), r.station.seen
    assert r.station.seen == [
        "TO_PICKUP",
        "AT_PICKUP",
        "TO_MACHINE",
        "AT_RELEASE",
        "TURNING",
        "AT_ATTACH",
        "RETURNING",
        "Closed",
    ]


def test_trolley_still_on_blocks_the_next_order(rig):
    r, w = rig, rig.world
    accepted(r, "O1")
    parked_at(w, "ATT")
    press(r, "present")
    parked_at(w, "MW-1")
    press(r, "absent")
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
    spin(w)
    parked_at(w, "ME-1")
    press(r, "present")
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    w.still = True
    w.drive(0.1)
    assert r.wait(lambda: "NOT_READY" in r.station.errors())
    r.station.send("O2")
    assert r.wait(lambda: "DEPARTURE_REFUSED" in r.station.errors()), r.station.state
    assert w.job.state == lj.DONE and w.job.order.order_id == "O1", "no horn, no motion"
    assert any(
        ref["referenceValue"] == "TROLLEY_PRESENT"
        for e in r.station.state["errors"]
        for ref in e["errorReferences"]
    )


def test_bridge_killed_mid_trip_finishes_the_trip(rig):
    r, w = rig, rig.world
    accepted(r, "O1")
    parked_at(w, "ATT")
    r.kill_bridge()
    press(r, "present")
    parked_at(w, "MW-1")
    r.start_bridge()
    assert r.wait(lambda: r.station.seen[-1:] == ["AT_RELEASE"], 10.0), r.station.seen
    assert r.station.state["headerId"] < 200, "headerId restarted"
    press(r, "absent")
    assert w.until(lambda: w.job.tape.uturn_req is not None, 60.0)
    spin(w)
    parked_at(w, "ME-1")
    press(r, "present")
    assert w.until(lambda: w.job.state == lj.DONE, 200.0), w.job.reason
    assert r.wait(lambda: r.station.seen[-1:] == ["Closed"], 5.0), r.station.seen


def test_layer_restart_shows_order_lost(rig):
    r, w = rig, rig.world
    accepted(r, "O1")
    parked_at(w, "ATT")
    assert r.wait(lambda: r.station.seen[-1:] == ["AT_PICKUP"])
    r.host.publishing = False
    assert r.wait(lambda: r.station.state["operatingMode"] == "STARTUP", 5.0), r.station.state
    assert r.station.seen[-1] == "AT_PICKUP", "the station ignores STARTUP messages"
    r.host.publishing = True
    r.new_world()  # a new process: no order, no trip
    assert r.wait(lambda: r.station.state["orderId"] == "" and r.station.state["operatingMode"] != "STARTUP")
    assert r.wait(lambda: r.station.seen[-1:] == ["Aborted"], 3.0), r.station.seen


def test_wifi_style_broker_stop_mid_trip(rig):
    r, w = rig, rig.world
    accepted(r, "O1")
    parked_at(w, "ATT")
    assert r.wait(lambda: r.station.seen[-1:] == ["AT_PICKUP"])
    r.broker.stop()
    assert r.wait(lambda: not r.bridge.link.connected, 5.0)
    press(r, "present")
    parked_at(w, "MW-1")  # the trip goes on: the job has no network input
    assert w.job.order.status["att"] == "FINISHED"
    r.broker.start()
    assert r.wait(lambda: r.bridge.link.connected and r.station.seen[-1:] == ["AT_RELEASE"], 12.0), (
        r.station.seen
    )


def test_the_real_node_and_the_bridge_refuse_over_the_wire(rig):
    """The real line_follow_node's /amr/line/order and OrderState: on no site mission, refused."""
    from amr_line import line_follow_node as lfn

    r = rig
    r.ex.remove_node(r.host)
    r.host.destroy_node()
    node = lfn.LineFollowNode()
    r.ex.add_node(node)
    mode = LeanNode("sim_mode")
    pub = mode.create_publisher(ModeState, "/amr/mode_state", LATCHED)
    pub.publish(ModeState(mode=ModeState.LINE, layer_ready=True, generation=node._generation))
    r.ex.add_node(mode)
    r.host = LeanNode("sim_host_gone")
    r.world.pump = lambda: (r.ex.spin_once(timeout_sec=0), time.sleep(0.002))
    end = time.monotonic() + 10.0
    while time.monotonic() < end and not (
        r.station.state
        and r.station.state.get("orderId") == ""
        and any(
            ref["referenceValue"] == "SITE_NOT_LIVE"
            for e in r.station.state["errors"]
            for ref in e["errorReferences"]
        )
    ):
        r.world.pump()
    assert any(
        ref["referenceValue"] == "SITE_NOT_LIVE"
        for e in r.station.state["errors"]
        for ref in e["errorReferences"]
    ), r.station.state
    r.station.send("O1")
    end = time.monotonic() + 5.0
    while time.monotonic() < end and "DEPARTURE_REFUSED" not in r.station.errors():
        r.world.pump()
    assert "DEPARTURE_REFUSED" in r.station.errors(), r.station.state
    assert node.job.state == lj.IDLE and node.job.order is None
    assert node._order_published["refusal_reason"] == "SITE_NOT_LIVE"
    r.ex.remove_node(node)
    node.destroy_node()
    r.ex.remove_node(mode)
    mode.destroy_node()
    r.world.pump = None
