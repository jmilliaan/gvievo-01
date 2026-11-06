"""rear_scanner.launch.py: the rear nanoScan3's driver and nothing else (station call plan P4).

Namespace `rear`: the driver's topics are relative (scan, output_paths), so they come up as /rear/scan
and /rear/output_paths and the front unit's /scan and /output_paths do not move. Check that on the
vehicle at P8. Only amr_base.trolley_node reads them. It respawns for the same reason the front does.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


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
                emulate_tty=True,
                parameters=[params],
                respawn=True,
                respawn_delay=5.0,
            ),
        ]
    )
