"""The MQTT client, on a fake (contract section 1, plan 12.5)."""

import json
import os
import types

import pytest
from fake_mqtt import FakeMqttClient

from amr_station import mqtt_link as ml


def link():
    c = FakeMqttClient()
    return ml.MqttLink("192.168.2.5", 1883, "gvi", "agv9", "u", "p", client=c, clock=lambda: "T"), c


def names(c):
    return [x[0] for x in c.calls]


def test_will_is_set_before_connect():
    lk, c = link()
    lk.start()
    n = names(c)
    assert n.index("will_set") < n.index("connect_async") < n.index("loop_start")
    w = next(x for x in c.calls if x[0] == "will_set")
    doc = json.loads(w[2])
    assert w[1] == "vda5050/v3/gvi/agv9/connection" and w[3:] == (1, True)
    assert doc["connectionState"] == "CONNECTION_BROKEN" and doc["version"] == "3.0.0"
    assert ("connect_async", "192.168.2.5", 1883, 10) in c.calls and ("reconnect_delay_set", 2, 2) in c.calls


def test_connect_order():
    lk, c = link()
    lk.start()
    c.calls.clear()
    c.fire_connect()
    assert c.calls == [], "paho's thread only sets a flag"
    assert lk.service() == "up"
    assert names(c) == ["subscribe", "publish"]
    assert c.subscribed[0] == [("vda5050/v3/gvi/agv9/order", 0), ("vda5050/v3/gvi/agv9/instantActions", 0)]
    t, p, q, r = c.published[0]
    assert t.endswith("/connection") and json.loads(p)["connectionState"] == "ONLINE" and (q, r) == (1, True)
    assert lk.service() == ""


def clocked():
    t = [100.0]
    c = FakeMqttClient()
    lk = ml.MqttLink("h", 1883, "gvi", "agv9", "u", "p", client=c, clock=lambda: "T", monotonic=lambda: t[0])
    lk.start()
    return lk, c, t


def online_count(c):
    return sum(1 for p in c.published if p[0].endswith("/connection"))


def test_a_drop_and_reconnect_between_two_checks_announces_again():
    lk, c, _t = clocked()
    c.fire_connect()
    assert lk.service() == "up"
    c.fire_suback()
    # The drop and the reconnect both happen before the next service().
    c.fire_disconnect()
    c.fire_connect()
    assert lk.connected and not lk.ready, "connected, but the new clean session has no subscriptions"
    assert lk.service() == "up"
    assert len(c.subscribed) == 2 and online_count(c) == 2
    c.fire_suback()
    assert lk.ready
    assert lk.service() == ""


def test_a_failed_reconnect_is_not_a_new_connection():
    lk, c, _t = clocked()
    c.fire_connect()
    lk.service()
    c.fire_disconnect()
    c.fire_connect(types.SimpleNamespace(is_failure=True))
    assert lk.service() == "down"
    assert len(c.subscribed) == 1


def test_not_ready_until_the_broker_accepts_the_subscriptions():
    lk, c, t = clocked()
    c.fire_connect()
    lk.service()
    assert not lk.ready
    c.fire_suback(codes=(0, types.SimpleNamespace(is_failure=True)))
    assert not lk.ready, "a refused topic means orders cannot arrive"
    t[0] += ml.SUBACK_WAIT_S - 0.1
    lk.service()
    assert len(c.subscribed) == 1
    t[0] += 0.1
    lk.service()
    assert len(c.subscribed) == 2, "subscribes again"
    c.fire_suback()
    assert lk.ready
    t[0] += 60.0
    lk.service()
    assert len(c.subscribed) == 2, "and stops once accepted"


def test_an_old_suback_does_not_count_for_a_new_connection():
    lk, c, _t = clocked()
    c.fire_connect()
    lk.service()
    c.fire_suback()
    c.fire_disconnect()
    lk.service()
    c.fire_connect()
    lk.service()
    assert not lk.ready


def test_online_is_republished_retained_every_15_s_while_connected():
    lk, c, t = clocked()
    c.fire_connect()
    lk.service()
    assert online_count(c) == 1
    t[0] += ml.ONLINE_REPUBLISH_S - 0.1
    lk.service()
    assert online_count(c) == 1
    t[0] += 0.1
    lk.service()
    assert online_count(c) == 2
    topic, payload, qos, retain = c.published[-1]
    assert json.loads(payload)["connectionState"] == "ONLINE" and (qos, retain) == (1, True)
    c.fire_disconnect()
    lk.service()
    c.published.clear()
    t[0] += 60.0
    lk.service()
    assert c.published == [], "nothing while disconnected"


def test_a_failed_connect_is_not_connected():
    lk, c = link()
    c.fire_connect(types.SimpleNamespace(is_failure=True))
    assert not lk.connected and lk.service() == ""


def test_offline_then_disconnect_on_shutdown():
    lk, c = link()
    lk.start()
    c.fire_connect()
    lk.service()
    c.calls.clear()
    lk.stop()
    assert names(c)[:2] == ["publish", "disconnect"]
    assert json.loads(c.published[-1][1])["connectionState"] == "OFFLINE"


def test_no_publish_while_disconnected():
    lk, c = link()
    lk.start()
    assert lk.publish_state({}) is None
    lk.publish_connection("ONLINE")
    assert c.published == []
    c.fire_connect()
    lk.service()
    c.fire_disconnect()
    assert lk.service() == "down"
    c.published.clear()
    assert lk.publish_state({}) is None and c.published == []


def test_on_message_only_queues():
    lk, c = link()
    calls = len(c.calls)
    for n in range(40):
        c.on_message(c, None, types.SimpleNamespace(topic="t", payload=b"x%d" % n, retain=n == 39))
    assert len(c.calls) == calls and len(lk.queue) == ml.QUEUE_MAX, "bounded"
    assert lk.queue[-1] == ("t", b"x39", True)


def test_header_ids_count_per_topic():
    lk, c = link()
    lk.start()  # the will took connection 0
    c.fire_connect()
    lk.service()
    assert lk.publish_state({}) == 0 and lk.publish_state({}) == 1
    docs = [json.loads(p[1]) for p in c.published]
    assert [d["headerId"] for d in docs] == [1, 0, 1]
    assert docs[1]["timestamp"] == "T" and docs[1]["serialNumber"] == "agv9"


def test_topics_use_the_configured_serial():
    lk, _c = link()
    assert set(lk.topics.values()) == {
        f"vda5050/v3/gvi/agv9/{n}" for n in ("order", "instantActions", "state", "connection")
    }


def test_the_timestamp_format():
    import re

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", ml.utc_now())


def test_credentials_are_refused_with_a_wider_mode(tmp_path):
    p = tmp_path / ml.CREDENTIALS
    p.write_text(json.dumps({"username": "a", "password": "b"}))
    os.chmod(p, 0o644)
    with pytest.raises(ml.CredentialsError, match="must be 600"):
        ml.load_credentials(str(tmp_path))
    os.chmod(p, 0o600)
    assert ml.load_credentials(str(tmp_path)) == ("a", "b")
    p.write_text("{}")
    with pytest.raises(ml.CredentialsError):
        ml.load_credentials(str(tmp_path))
    with pytest.raises(ml.CredentialsError):
        ml.load_credentials(str(tmp_path / "nope"))
