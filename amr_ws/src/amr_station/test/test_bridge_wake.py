"""The bridge's drain is woken from paho's thread, not polled at 20 Hz (unified plan WP-C17).

paho's network thread queues the message and then calls MqttLink.on_wake, which the node sets to a
GuardCondition's trigger. A guard's triggers coalesce into one callback on the executor's next spin,
so the drain takes the whole queue. The guard is faked here as a flag; rclpy is not needed."""

import pathlib
import threading
import types

from fake_mqtt import FakeMqttClient

from amr_station import mqtt_link as ml

NODE = (pathlib.Path(__file__).resolve().parents[1] / "amr_station" / "station_bridge_node.py").read_text()


class FakeGuard:
    """rclpy GuardCondition semantics: trigger() from any thread; one callback per spin however
    many triggers came before it."""

    def __init__(self, callback):
        self.callback, self.triggered, self.calls = callback, threading.Event(), 0

    def trigger(self):
        self.triggered.set()

    def spin_once(self):
        if self.triggered.is_set():
            self.triggered.clear()
            self.calls += 1
            self.callback()


def _msg(topic, body=b"{}", retain=False):
    return types.SimpleNamespace(topic=topic, payload=body, retain=retain)


def _setup():
    c = FakeMqttClient()
    lk = ml.MqttLink("192.168.2.5", 1883, "gvi", "agv9", "u", "p", client=c, clock=lambda: "T")
    handled = []
    guard = FakeGuard(lambda: handled.extend(lk.take()))
    lk.on_wake = guard.trigger
    lk.start()
    return lk, c, guard, handled


def test_a_queued_message_is_handled_on_the_next_spin():
    lk, c, guard, handled = _setup()
    guard.spin_once()
    assert handled == [] and guard.calls == 0, "nothing queued: no wake, no drain"
    c.on_message(c, None, _msg(lk.topics["order"], b'{"orderId": "o1"}'))
    assert guard.triggered.is_set(), "paho's callback woke the executor"
    guard.spin_once()
    assert handled == [(lk.topics["order"], b'{"orderId": "o1"}', False)]
    assert not lk.queue


def test_none_is_lost_when_several_arrive_at_once():
    lk, c, guard, handled = _setup()
    topics = [lk.topics["order"], lk.topics["instantActions"]] * 5

    def network_thread():
        for i, t in enumerate(topics):
            c.on_message(c, None, _msg(t, str(i).encode()))

    th = threading.Thread(target=network_thread)
    th.start()
    th.join()
    guard.spin_once()  # ten triggers, one callback: it takes them all
    assert guard.calls == 1
    assert [p for _t, p, _r in handled] == [str(i).encode() for i in range(10)]
    assert [t for t, _p, _r in handled] == topics


def test_a_message_landing_mid_drain_is_taken_or_woken_again():
    lk, c, guard, handled = _setup()
    c.on_message(c, None, _msg(lk.topics["order"], b"a"))
    seen = []
    for item in lk.take():  # the drain, with paho appending while it runs
        seen.append(item[1])
        if item[1] == b"a":
            c.on_message(c, None, _msg(lk.topics["order"], b"b"))
    assert seen == [b"a", b"b"]
    guard.spin_once()  # the second trigger finds an empty queue: harmless
    assert not lk.queue


def test_link_edges_wake_the_drain_too():
    """service() runs in the drain: a connect, a drop and a SUBACK must not wait for the 10 Hz tick."""
    lk, c, guard, _ = _setup()
    for fire in (c.fire_connect, c.fire_suback, c.fire_disconnect):
        guard.triggered.clear()
        fire()
        assert guard.triggered.is_set(), fire.__name__


def test_the_node_has_no_drain_timer_and_no_parameter_services():
    assert "create_timer(0.05" not in NODE
    assert "self.link.on_wake = self.create_guard_condition(self._drain).trigger" in NODE
    assert NODE.index("self.link.on_wake =") < NODE.index("self.link.start()"), "wake set before paho runs"
    assert "create_timer(0.1, self._state_tick)" in NODE  # the state stays 10 Hz
    assert 'super().__init__("station_bridge", start_parameter_services=False)' in NODE
