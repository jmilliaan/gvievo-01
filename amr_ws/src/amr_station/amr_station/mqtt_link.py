"""The MQTT client (contract section 1). paho is imported lazily and the client can be injected, so
everything else, and the offline test suite, runs without it.

Threads: paho's network thread only sets a flag and appends to a bounded deque. Parsing, publishing and
everything else happens on the caller's thread (the node's executor). publish() is a no-op while not
connected: a publish while disconnected is dropped, QoS 1 included, as the contract requires.
"""

from __future__ import annotations

import collections
import datetime
import json
import os
import stat
import time

KEEPALIVE_S = 10
RECONNECT_S = 2
ONLINE_REPUBLISH_S = 15.0  # the retained ONLINE again: a stale will cannot stay the last word for longer
SUBACK_WAIT_S = 5.0  # no accepted SUBACK by then: subscribe again
QUEUE_MAX = 32
CREDENTIALS = "station-mqtt.json"
VERSION = "3.0.0"


class CredentialsError(RuntimeError):
    pass


def load_credentials(state_dir: str) -> tuple[str, str]:
    """<state_dir>/station-mqtt.json, mode 600, never in the repo. Refused if the mode is wider."""
    path = os.path.join(os.path.expanduser(state_dir), CREDENTIALS)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            raise CredentialsError(f"{path} is mode {mode:o}: it must be 600")
        with open(path) as fh:
            doc = json.load(fh)
        return str(doc["username"]), str(doc["password"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CredentialsError(f"{path}: {e}") from e


def utc_now() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _paho_client(client_id: str):
    import paho.mqtt.client as mqtt  # noqa: PLC0415 - lazily: absent on a dev box, unused when off

    # VERSION2 explicitly: paho 1.x has no such thing, so a wrong version fails at once.
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )


class MqttLink:
    def __init__(
        self,
        host: str,
        port: int,
        manufacturer: str,
        serial: str,
        username: str,
        password: str,
        client=None,
        clock=utc_now,
        monotonic=time.monotonic,
    ) -> None:
        self.host, self.port = host, int(port)
        self.manufacturer, self.serial = manufacturer, serial
        base = f"vda5050/v3/{manufacturer}/{serial}"
        self.topics = {name: f"{base}/{name}" for name in ("order", "instantActions", "state", "connection")}
        self.clock = clock
        self.connected = False
        self.queue: collections.deque = collections.deque(maxlen=QUEUE_MAX)
        self.monotonic = monotonic
        self.connections = 0  # counted on paho's thread; a new number means re-announce
        self._announced = 0  # the connection number subscribed and ONLINE was sent for
        self._up = False  # service() has reported "up" and not yet "down"
        self._sub_mid = self._suback_mid = None
        self._sub_t = self._online_t = 0.0
        self._header = {"state": 0, "connection": 0}
        self.c = client if client is not None else _paho_client(f"gvi-{serial}")
        self.c.username_pw_set(username, password)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = self._on_message
        self.c.on_subscribe = self._on_subscribe

    # -- paho's network thread: set a flag, queue bytes, nothing else --------------------------
    def _on_connect(self, _c, _u, _flags, reason_code, _props=None):
        ok = not getattr(reason_code, "is_failure", bool(reason_code))
        if ok:
            self.connections += 1  # before `connected`: service() must never see the old number as new
        self.connected = ok

    def _on_disconnect(self, _c, _u, *_rest):
        self.connected = False

    def _on_subscribe(self, _c, _u, mid, reason_codes, _props=None):
        if not any(getattr(rc, "is_failure", bool(rc)) for rc in reason_codes):
            self._suback_mid = mid

    def _on_message(self, _c, _u, msg):
        self.queue.append((msg.topic, bytes(msg.payload), bool(msg.retain)))

    # -- the caller's thread ---------------------------------------------------------------------
    def _next_header(self, topic: str) -> int:
        n = self._header[topic]
        self._header[topic] = n + 1
        return n

    def _envelope(self, topic: str, body: dict) -> tuple[int, dict]:
        n = self._next_header(topic)
        return n, {
            "headerId": n,
            "timestamp": self.clock(),
            "version": VERSION,
            "manufacturer": self.manufacturer,
            "serialNumber": self.serial,
            **body,
        }

    def start(self) -> None:
        """The last will first, then connect. Its header is as of connect: old when delivered."""
        _n, will = self._envelope("connection", {"connectionState": "CONNECTION_BROKEN"})
        self.c.will_set(self.topics["connection"], json.dumps(will), qos=1, retain=True)
        self.c.reconnect_delay_set(RECONNECT_S, RECONNECT_S)
        self.c.connect_async(self.host, self.port, keepalive=KEEPALIVE_S)
        self.c.loop_start()

    def service(self) -> str:
        """Run on the caller's thread: "up" on any new connection, including one whose drop happened
        between two calls (subscribed, ONLINE sent: the caller publishes `state` next), "down" when one
        just ended, "" otherwise. Also keeps the connection's subscriptions and retained ONLINE current."""
        now = self.monotonic()
        if self.connected:
            if self._announced != self.connections:
                self._announced = self.connections
                self._up = True
                self._subscribe(now)
                self.publish_connection("ONLINE")
                self._online_t = now
                return "up"
            if not self.subscribed and now - self._sub_t >= SUBACK_WAIT_S:
                self._subscribe(now)
            if now - self._online_t >= ONLINE_REPUBLISH_S:
                self.publish_connection("ONLINE")
                self._online_t = now
            return ""
        if self._up:
            self._up = False
            return "down"
        return ""

    def _subscribe(self, now: float) -> None:
        topics = [(self.topics["order"], 0), (self.topics["instantActions"], 0)]
        self._sub_mid, self._sub_t = self.c.subscribe(topics)[1], now

    @property
    def subscribed(self) -> bool:
        """The broker accepted the subscriptions of the latest subscribe."""
        return self._sub_mid is not None and self._suback_mid == self._sub_mid

    @property
    def ready(self) -> bool:
        """Orders can reach this AGV: connected, announced, and subscribed."""
        return self.connected and self._announced == self.connections and self.subscribed

    def publish_connection(self, state: str) -> None:
        if self.connected:
            _n, doc = self._envelope("connection", {"connectionState": state})
            self.c.publish(self.topics["connection"], json.dumps(doc), qos=1, retain=True)

    def publish_state(self, body: dict) -> int | None:
        """The state message. Its headerId, or None if not connected (nothing sent, none used)."""
        if not self.connected:
            return None
        n, doc = self._envelope("state", body)
        self.c.publish(self.topics["state"], json.dumps(doc), qos=0, retain=False)
        return n

    def stop(self) -> None:
        """An orderly end: OFFLINE, then disconnect. The broker then sends no will."""
        self.publish_connection("OFFLINE")
        self.c.disconnect()
        self.c.loop_stop()
