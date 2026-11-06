"""A paho client stand-in, injected into MqttLink (the style of tests/test_dio.py)."""


class FakeMqttClient:
    def __init__(self):
        self.calls, self.published, self.subscribed = [], [], []
        self.on_connect = self.on_disconnect = self.on_message = None

    def username_pw_set(self, u, p):
        self.calls.append(("username_pw_set", u, p))

    def will_set(self, topic, payload, qos=0, retain=False):
        self.calls.append(("will_set", topic, payload, qos, retain))

    def reconnect_delay_set(self, a, b):
        self.calls.append(("reconnect_delay_set", a, b))

    def connect_async(self, host, port, keepalive=60):
        self.calls.append(("connect_async", host, port, keepalive))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def subscribe(self, topics):
        self.subscribed.append(topics)
        self.calls.append(("subscribe",))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        self.calls.append(("publish", topic))

    # the broker's side
    def fire_connect(self, code=0):
        self.on_connect(self, None, {}, code, None)

    def fire_disconnect(self):
        self.on_disconnect(self, None, {}, 0, None)
