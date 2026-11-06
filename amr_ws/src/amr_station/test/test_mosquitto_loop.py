"""The MQTT link against a real broker on loopback, with the contract's ACL. Opt-in: AMR_MQTT_TESTS=1 with
mosquitto and mosquitto_passwd on the path. test_station_call_sim uses the same broker fixture."""

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time

import contract
import pytest

if os.environ.get("AMR_MQTT_TESTS") != "1" or not shutil.which("mosquitto"):
    pytest.skip("set AMR_MQTT_TESTS=1 with mosquitto on the path", allow_module_level=True)

mqtt = pytest.importorskip("paho.mqtt.client")

from amr_station import bridge_core as bc  # noqa: E402
from amr_station import mqtt_link as ml  # noqa: E402
from amr_station import vda_order as vo  # noqa: E402

PORT = 18883
USERS = {"station": "s3", "agv1": "a1", "watch": "w4"}
ACL = """\
user station
topic write vda5050/v3/gvi/+/order
topic write vda5050/v3/gvi/+/instantActions
topic read vda5050/v3/gvi/+/state
topic read vda5050/v3/gvi/+/connection
user agv1
topic write vda5050/v3/gvi/agv1/state
topic write vda5050/v3/gvi/agv1/connection
topic read vda5050/v3/gvi/agv1/order
topic read vda5050/v3/gvi/agv1/instantActions
user watch
topic read vda5050/v3/gvi/#
"""


class Broker:
    def __init__(self, tmp):
        self.tmp, self.proc = tmp, None
        pw = tmp / "passwd"
        pw.touch()
        for u, p in USERS.items():
            subprocess.run(["mosquitto_passwd", "-b", str(pw), u, p], check=True)
        (tmp / "acl").write_text(ACL)
        (tmp / "m.conf").write_text(
            f"listener {PORT} 127.0.0.1\npersistence false\nallow_anonymous false\n"
            f"password_file {pw}\nacl_file {tmp / 'acl'}\n"
        )

    def start(self):
        self.proc = subprocess.Popen(
            ["mosquitto", "-c", str(self.tmp / "m.conf")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.3)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(5)
            self.proc = None


@pytest.fixture()
def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


def client(user, password=None, cid=None):
    got = []
    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=cid or f"t-{user}-{time.time()}",
        protocol=mqtt.MQTTv311,
    )
    c.username_pw_set(user, password or USERS[user])
    c.on_message = lambda _c, _u, m: got.append((m.topic, bytes(m.payload), bool(m.retain)))
    c.got = got
    c.connect("127.0.0.1", PORT, keepalive=10)
    c.loop_start()
    time.sleep(0.2)
    return c


def until(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def bridge():
    lk = ml.MqttLink("127.0.0.1", PORT, "gvi", "agv1", "agv1", USERS["agv1"])
    lk.start()
    assert until(lambda: lk.connected), "the bridge did not connect"
    assert lk.service() == "up"
    time.sleep(0.2)
    return lk


def order(seen):
    oid = "MRU3-X"
    return json.dumps(
        {
            "headerId": 1,
            "timestamp": "t",
            "version": "3.0.0",
            "manufacturer": "gvi",
            "serialNumber": "agv1",
            "orderId": oid,
            "orderUpdateId": 0,
            "seenStateHeaderId": seen,
            **vo.canonical_order(contract.site(), "MRU3", oid),
        }
    )


T = "vda5050/v3/gvi/agv1/"


def test_last_will_arrives_after_kill(broker):
    w = client("watch")
    w.subscribe("vda5050/v3/gvi/#")
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.path.dirname(os.path.dirname(ml.__file__))!r})
        from amr_station import mqtt_link as ml
        lk = ml.MqttLink("127.0.0.1", {PORT}, "gvi", "agv1", "agv1", {USERS["agv1"]!r})
        lk.start()
        while True:
            lk.service(); time.sleep(0.05)
    """)
    p = subprocess.Popen([sys.executable, "-c", script])
    states = lambda: [json.loads(x[1])["connectionState"] for x in w.got if x[0].endswith("/connection")]  # noqa: E731
    assert until(lambda: "ONLINE" in states())
    p.send_signal(signal.SIGKILL)
    p.wait(3)
    assert until(lambda: "CONNECTION_BROKEN" in states(), 20.0), states()
    w.loop_stop()


def retained_connection():
    """What a station connecting now is told: the retained connection message, from a fresh client."""
    w = client("watch")
    w.subscribe(T + "connection")
    assert until(lambda: w.got), "nothing retained"
    w.loop_stop()
    w.disconnect()
    return json.loads(w.got[0][1])["connectionState"]


def test_a_will_from_the_old_session_cannot_stay_the_last_word(broker):
    """The Wi-Fi case: the old session is still open at the broker (its keepalive has not run out) when
    the AGV comes back under the same client id. Frozen with SIGSTOP, so it sends no DISCONNECT."""
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.path.dirname(os.path.dirname(ml.__file__))!r})
        from amr_station import mqtt_link as ml
        lk = ml.MqttLink("127.0.0.1", {PORT}, "gvi", "agv1", "agv1", {USERS["agv1"]!r})
        lk.start()
        while True:
            lk.service(); time.sleep(0.05)
    """)
    old = subprocess.Popen([sys.executable, "-c", script])
    try:
        time.sleep(1.0)
        old.send_signal(signal.SIGSTOP)
        lk = bridge()   # the same client id takes the session over
        for _ in range(100):
            lk.service()
            time.sleep(0.02)
        assert retained_connection() == "ONLINE"
        # Past the frozen session's keepalive too: nothing arrives late to replace it.
        end = time.monotonic() + 20.0
        while time.monotonic() < end:
            lk.service()
            time.sleep(0.05)
        assert lk.ready and retained_connection() == "ONLINE"
        lk.stop()
    finally:
        old.kill()
        old.wait(3)


def test_the_retained_online_is_repaired_while_connected(broker, monkeypatch):
    """Whatever got retained, the next republish replaces it."""
    monkeypatch.setattr(ml, "ONLINE_REPUBLISH_S", 0.5)
    lk = bridge()
    assert until(lambda: lk.ready or lk.service() == "" and lk.ready), "the broker accepts the subscriptions"
    # The contract's ACL lets agv1 write its own connection topic: put a stale will there.
    lk.c.publish(T + "connection", json.dumps({"connectionState": "CONNECTION_BROKEN"}), qos=1, retain=True)
    time.sleep(0.2)
    assert retained_connection() == "CONNECTION_BROKEN"
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        lk.service()
        time.sleep(0.05)
    assert retained_connection() == "ONLINE"
    lk.stop()


def test_a_broker_restart_ends_ready_again(broker):
    lk = bridge()
    assert until(lambda: lk.ready)
    broker.stop()
    assert until(lambda: not lk.connected)
    assert lk.service() == "down" and not lk.ready
    broker.start()
    assert until(lambda: lk.connected, 8.0)
    assert lk.service() == "up"
    assert until(lambda: lk.ready), "the new clean session is subscribed"
    lk.stop()


def test_orderly_stop_is_offline_and_no_will(broker):
    w = client("watch")
    w.subscribe("vda5050/v3/gvi/#")
    lk = bridge()
    lk.stop()
    states = lambda: [json.loads(x[1])["connectionState"] for x in w.got if x[0].endswith("/connection")]  # noqa: E731
    assert until(lambda: "OFFLINE" in states())
    time.sleep(0.5)
    assert "CONNECTION_BROKEN" not in states()
    w.loop_stop()


def test_no_offline_queue(broker):
    lk = bridge()
    broker.stop()
    assert until(lambda: not lk.connected)
    assert lk.publish_state({"x": 1}) is None
    broker.start()
    w = client("watch")
    w.subscribe("vda5050/v3/gvi/#")
    assert until(lambda: lk.connected, 8.0), "reconnects every 2 s"
    lk.service()
    time.sleep(0.5)
    assert not [x for x in w.got if x[0].endswith("/state")], "nothing queued"
    lk.stop()
    w.loop_stop()


def test_retained_order_is_discarded(broker):
    """Published with the bridge disconnected: delivered on subscribe with the flag set."""
    s = client("station")
    s.publish(T + "order", order(0), qos=0, retain=True)
    time.sleep(0.2)
    lk = bridge()
    assert until(lambda: lk.queue)
    topic, payload, retained = lk.queue.popleft()
    assert topic.endswith("/order") and retained
    core = bc.BridgeCore(contract.site(), "gvi", "agv1")
    assert core.on_order(payload, retained, 1.0) is None and core.refusal is None
    lk.stop()
    s.loop_stop()


def test_a_retained_publish_while_connected_is_a_normal_order(broker):
    """The flag is clear on delivery, so it goes on to the other checks, check 4 included."""
    lk = bridge()
    s = client("station")
    s.publish(T + "order", order(77), qos=0, retain=True)
    assert until(lambda: lk.queue)
    _topic, payload, retained = lk.queue.popleft()
    assert not retained
    core = bc.BridgeCore(contract.site(), "gvi", "agv1")
    assert core.on_order(payload, retained, 1.0) is None and core.refusal["type"] == vo.STALE_ORDER
    core.ring.sent(77, 1.0)
    assert core.on_order(payload, retained, 1.0) == ("depart", "MRU3-X", "MRU3")
    lk.stop()
    s.loop_stop()


def test_acl_refuses_a_wrong_user(broker):
    rc = []
    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="bad", protocol=mqtt.MQTTv311
    )
    c.username_pw_set("agv1", "wrong")
    c.on_connect = lambda _c, _u, _f, code, _p: rc.append(code)
    c.connect("127.0.0.1", PORT)
    c.loop_start()
    assert until(lambda: rc)
    assert rc[0].is_failure
    c.loop_stop()


def test_the_agv_cannot_publish_an_order(broker):
    lk = bridge()
    lk.c.publish(T + "order", order(1))
    time.sleep(0.3)
    assert not lk.queue, "the ACL drops its own write to order"
    lk.stop()


def test_order_after_reconnect_needs_a_fresh_state(broker):
    core = bc.BridgeCore(contract.site(), "gvi", "agv1")
    core.ring.sent(5, 0.0)
    lk = bridge()
    s = client("station")
    s.publish(T + "order", order(5))
    assert until(lambda: lk.queue)
    _t, payload, retained = lk.queue.popleft()
    assert core.on_order(payload, retained, 10.0) is None and core.refusal["type"] == vo.STALE_ORDER
    lk.stop()
    s.loop_stop()


def test_the_watch_user_reads_and_cannot_publish(broker):
    lk = bridge()
    w = client("watch")
    w.subscribe("vda5050/v3/gvi/#")
    time.sleep(0.2)
    assert lk.publish_state({"x": 1}) == 0
    assert until(lambda: [x for x in w.got if x[0].endswith("/state")]), "reads"
    w.publish(T + "order", order(1))
    time.sleep(0.3)
    assert not lk.queue, "cannot publish"
    lk.stop()
    w.loop_stop()
