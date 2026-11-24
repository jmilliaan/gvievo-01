#!/usr/bin/env python3
"""zone_probe: a no-motion stand-in for the line layer, for the contract v1.6 joint test (section 13).

Run it ONLY with amr.service stopped: it serves /amr/line/order and publishes /amr/line/order_state as the
line layer would, and nothing else. It has no drive, panel or lease interface: it cannot move anything.
The real station bridge (station_bridge_node) runs beside it, unchanged, and talks to the real station.

It uses the real amr_line.zones.ZoneClient, with its grant file in a directory of its own (default
~/.amr/zone-probe), so a test leaves the vehicle's real state alone.

Commands, by service (LineTeach on /zone_probe/cmd, action = the command, arg = its argument):
    ask out | ask home     a CLUSTER request (:1 out, :2 home-bound) for the probe's order id
    drop <n>               release request n: the tail is clear ("tail_clear")
    trolleys               trolleys off at HOME: every home-bound grant goes ("trolleys_off")
    where none|outside|inside   where the AGV "is" when a REVOKED arrives (13.7)
    reset                  the operator's Reset (drops a REVOKED entry, ZONE_RELEASE_LOST)
    oprelease              Run page "release zone" (13.6)
    show                   the current entries

    ros2 service call /zone_probe/cmd amr_interfaces/srv/LineTeach "{action: ask, arg: out}"
"""

import argparse
import os
import time

import rclpy
from rclpy.node import Node

from amr_interfaces.msg import ModeState, OrderState
from amr_interfaces.srv import LineTeach
from amr_line import zones as zmod

LATCHED_DEPTH = 1


class ZoneProbe(Node):
    def __init__(self, state_dir, zone_set_id, order_id):
        super().__init__("zone_probe")
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

        latched = QoSProfile(depth=LATCHED_DEPTH, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        os.makedirs(state_dir, exist_ok=True)
        self.zc = zmod.ZoneClient(state_dir, zone_set_id)
        self.order_id = order_id
        self.where = "none"
        self.rids = {}                                  # n -> requestId of this probe's order
        for _level, text in self.zc.log:
            self.get_logger().info(text)
        self.zc.log.clear()
        self.pub = self.create_publisher(OrderState, "/amr/line/order_state", latched)
        self.mode_pub = self.create_publisher(ModeState, "/amr/mode_state", latched)
        self.create_service(LineTeach, "/amr/line/order", self._srv_order)
        self.create_service(LineTeach, "/zone_probe/cmd", self._srv_cmd)
        self.create_timer(1.0, self._publish)
        self.get_logger().warning(f"zone_probe: NO MOTION stand-in for the line layer; order {order_id}, "
                                  f"grants in {state_dir}")

    def _publish(self):
        m = OrderState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.generation = 0
        m.not_ready = ["ZONE_PROBE"]                    # the station never dispatches to a probe
        for k, v in self.zc.snapshot().items():
            setattr(m, k, v)
        m.zone_capable = True
        self.pub.publish(m)
        ms = ModeState()
        ms.generation, ms.mode, ms.requested_mode = 0, ModeState.LINE, ModeState.LINE
        ms.base_ready = ms.layer_ready = True
        ms.phase = "zone_probe"
        self.mode_pub.publish(ms)
        for _level, text in self.zc.log:
            self.get_logger().info(text)
        self.zc.log.clear()

    def _srv_order(self, req, res):
        parts = (req.arg or "").split()
        if req.action == "zone" and parts == ["link", "up"]:
            self.zc.link_seen(time.monotonic())
            res.ok, res.message = True, "link"
        elif req.action == "zone" and len(parts) == 2:
            act = self.zc.on_response(parts[0], parts[1], self.where)
            if act == zmod.REREQUEST:
                n = next((k for k, r in self.rids.items() if r == parts[0]), None)
                if n is not None:
                    self.rids[n] = self.zc.request(self.order_id, "CLUSTER", home_bound=(n == 2))
            res.ok, res.message = True, act
            self.get_logger().info(f"response {parts[1]} for {parts[0]}: {act}")
        else:
            res.ok, res.message = False, "zone_probe: no orders here (no motion)"
        self._publish()
        return res

    def _srv_cmd(self, req, res):
        a, arg = req.action.strip(), (req.arg or "").strip()
        try:
            if a == "ask" and arg in ("out", "home"):
                n = 1 if arg == "out" else 2
                self.rids[n] = self.zc.request(self.order_id, "CLUSTER", home_bound=(n == 2))
                res.message = self.rids[n]
            elif a == "drop":
                rid = self.rids.get(int(arg)) or arg
                res.message = f"released {rid}" if self.zc.release(rid, "tail_clear") else f"no {rid}"
            elif a == "trolleys":
                res.message = f"released {self.zc.release_home_bound()}"
            elif a == "where" and arg in ("none", "outside", "inside"):
                self.where = arg
                res.message = f"where {arg}"
            elif a == "reset":
                res.message = f"dropped {self.zc.operator_reset()}"
            elif a == "oprelease":
                res.message = f"released {self.zc.operator_release()}"
            elif a == "show":
                res.message = str({rid: e["status"] for rid, e in self.zc.entries.items()})
            else:
                raise ValueError("ask out|home, drop <n>, trolleys, where none|outside|inside, reset, "
                                 "oprelease, show")
            res.ok = True
        except (ValueError, zmod.ZoneError) as e:
            res.ok, res.message = False, str(e)
        self.get_logger().info(f"cmd {a} {arg}: {res.message}")
        self._publish()
        return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-dir", default=os.path.expanduser("~/.amr/zone-probe"))
    ap.add_argument("--zone-set-id", default="SITE103-TRAFFIC-1")
    ap.add_argument("--order-id", default=time.strftime("PROBE-%Y%m%dT%H%M%S"))
    args = ap.parse_args()
    rclpy.init()
    node = ZoneProbe(args.state_dir, args.zone_set_id, args.order_id)
    from rclpy.executors import ExternalShutdownException

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
