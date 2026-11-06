#!/usr/bin/env python3
"""The beam count in the trolley zone over 30 s (station call plan 11.3, P8). Read only: it
subscribes to /rear/scan and prints; the rear driver must be running. Record the figures for each case
in the plan's calibration table, and put the chosen values into the profile's rear block.

    source amr_ws/install/setup.bash; python3 tools/trolley_calibrate.py [--seconds 30]
"""
import argparse
import statistics
import time

import rclpy
from amr_base.qos import SENSOR_DATA
from amr_base.trolley_detect import Params, TrolleyDetect
from sensor_msgs.msg import LaserScan

from agv_core import config


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=30.0)
    a = ap.parse_args()
    detect = TrolleyDetect(Params.from_profile(config))
    counts = []

    def on_scan(m):
        detect.scan(time.monotonic(), m.ranges, m.angle_min, m.angle_increment, m.range_min, m.range_max)
        counts.append(detect.points)

    rclpy.init()
    node = rclpy.create_node("trolley_calibrate")
    node.create_subscription(LaserScan, "/rear/scan", on_scan, SENSOR_DATA)
    end = time.monotonic() + a.seconds
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_node()
    rclpy.shutdown()
    if not counts:
        raise SystemExit("no /rear/scan received: is the rear driver running?")
    print(f"{len(counts)} scans, beams in the zone: min {min(counts)} "
          f"median {statistics.median(counts):.0f} max {max(counts)} "
          f"(present_points {config.REAR_PRESENT_POINTS}, absent_points {config.REAR_ABSENT_POINTS})")


if __name__ == "__main__":
    main()
