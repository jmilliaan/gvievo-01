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

KEEPALIVE_S = 10
RECONNECT_S = 2
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
    ) -> None:
        self.host, self.port = host, int(port)
        self.manufacturer, self.serial = manufacturer, serial
        base = f"vda5050/v3/{manufacturer}/{serial}"
        self.topics = {name: f"{base}/{name}" for name in ("order", "instantActions", "state", "connection")}
        self.clock = clock
        self.connected = False
        self.queue: collections.deque = collections.deque(maxlen=QUEUE_MAX)
        self._announced = False  # subscribed and ONLINE for this connection
        self._header = {"state": 0, "connection": 0}
        self.c = client if client is not None else _paho_client(f"gvi-{serial}")
        self.c.username_pw_set(username, password)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = self._on_message

    # -- paho's network thread: set a flag, queue bytes, nothing else --------------------------
    def _on_connect(self, _c, _u, _flags, reason_code, _props=None):
        self.connected = not getattr(reason_code, "is_failure", bool(reason_code))

    def _on_disconnect(self, _c, _u, *_rest):
        self.connected = False

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
        """Run on the caller's thread: "up" on a fresh connection (subscribed, ONLINE sent: the caller
        publishes `state` next), "down" when one just ended, "" otherwise."""
        if self.connected and not self._announced:
            self._announced = True
            self.c.subscribe([(self.topics["order"], 0), (self.topics["instantActions"], 0)])
            self.publish_connection("ONLINE")
            return "up"
        if not self.connected and self._announced:
            self._announced = False
            return "down"
        return ""

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
