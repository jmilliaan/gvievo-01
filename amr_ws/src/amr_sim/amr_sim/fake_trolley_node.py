"""fake_trolley_node: the rear lidar in simulation (station call plan P3). Sim only, never on a vehicle:
the launch adds it from the sim branch of base.launch.py, and there is no real-vehicle bypass.

Publishes /amr/rear/trolley at 10 Hz, starting UNKNOWN. Driven from a test or a terminal:
    /sim/trolley/set   amr_interfaces/srv/LineTeach   action: absent | present | unknown
                                                      arg: "" (rear field clear) | violated | unknown
"""

from amr_base.lean_node import LeanNode, run
from amr_base.qos import RELIABLE_1
from amr_interfaces.msg import TrolleyState
from amr_interfaces.srv import LineTeach

STATES = {"absent": TrolleyState.ABSENT, "present": TrolleyState.PRESENT, "unknown": TrolleyState.UNKNOWN}
FIELDS = {
    "": TrolleyState.FIELD_CLEAR,
    "clear": TrolleyState.FIELD_CLEAR,
    "violated": TrolleyState.FIELD_VIOLATED,
    "unknown": TrolleyState.FIELD_UNKNOWN,
}


class FakeTrolley(LeanNode):
    def __init__(self) -> None:
        super().__init__("fake_trolley")
        self.state = TrolleyState.UNKNOWN
        self.field = TrolleyState.FIELD_UNKNOWN
        self._pub = self.create_publisher(TrolleyState, "/amr/rear/trolley", RELIABLE_1)
        self.create_service(LineTeach, "/sim/trolley/set", self._set)
        self.create_timer(0.1, self._tick)

    def _set(self, req, res):
        action, arg = req.action.strip(), (req.arg or "").strip()
        if action not in STATES or arg not in FIELDS:
            res.ok, res.message = False, "action: absent|present|unknown, arg: clear|violated|unknown"
            return res
        self.state, self.field = STATES[action], FIELDS[arg]
        res.ok, res.message = True, f"trolley {action}, rear field {arg or 'clear'}"
        self.get_logger().info(res.message)
        return res

    def _tick(self):
        m = TrolleyState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.state = self.state
        m.rear_field = self.field
        m.rear_case = TrolleyState.CASE_NO_TROLLEY
        m.detail = "simulated"
        self._pub.publish(m)


def main() -> None:
    run(FakeTrolley)


if __name__ == "__main__":
    main()
