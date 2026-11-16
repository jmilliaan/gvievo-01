"""rear_scanner.launch.py: the rear nanoScan3's driver and nothing else (station call plan P4).

Namespace `rear`: the driver's topics are relative (scan, output_paths), so they come up as /rear/scan
and /rear/output_paths and the front unit's /scan and /output_paths do not move. Check that on the
vehicle at P8. Only amr_base.trolley_node reads them. It respawns for the same reason the front does.

Addresses (WP-P10, 2026-11-16): the profile's rear.sensor_ip / host_ip / port
(agv_core.scanner_config), passed after the yaml so the profile wins; the yaml keeps the rest.
"""

import os

from agv_core import config, scanner_config
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

from amr_bringup.launch_helpers import quiet_logs


def generate_launch_description() -> LaunchDescription:
    params = os.path.join(get_package_share_directory("amr_bringup"), "config", "nanoscan3_rear.yaml")
    return LaunchDescription(
        [
            Node(
                package="sick_safetyscanners2",
                executable="sick_safetyscanners2_node",
                name="sick_safetyscanners2_rear_node",
                namespace="rear",
                output="screen",
                **quiet_logs(),  # its output already reaches logs/base.log (WP-P4)
                emulate_tty=True,
                parameters=[params, scanner_config.driver_params(config, scanner_config.REAR)],
                respawn=True,
                respawn_delay=5.0,
            ),
        ]
    )
