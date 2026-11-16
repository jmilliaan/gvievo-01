"""scanner.launch.py: the nanoScan3 driver and nothing else (unified plan U1).

No URDF here - base.launch.py owns the one robot_state_publisher. For a
standalone scanner + TF session use lidar.launch.py. ROS owns UDP 6060.

The driver aborts (exit -6) if the scanner is unreachable when it starts - a
cable out at boot left it dead until the next service restart (2026-10-02). It
respawns instead, so plugging the cable back in recovers the data link by itself.
The STOP path (OSSD pair into the FX3) does not depend on this node.

Addresses (WP-P10, 2026-11-16): the profile's lidar.sensor_ip / host_ip / port
(agv_core.scanner_config), passed after the yaml so the profile wins; the yaml keeps the rest.
"""

import os

from agv_core import config, scanner_config
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

from amr_bringup.launch_helpers import quiet_logs


def generate_launch_description() -> LaunchDescription:
    params = os.path.join(get_package_share_directory("amr_bringup"), "config", "nanoscan3.yaml")
    return LaunchDescription(
        [
            Node(
                package="sick_safetyscanners2",
                executable="sick_safetyscanners2_node",
                name="sick_safetyscanners2_node",
                output="screen",
                **quiet_logs(),  # its output already reaches logs/base.log (WP-P4)
                emulate_tty=True,
                parameters=[params, scanner_config.driver_params(config, scanner_config.FRONT)],
                respawn=True,
                respawn_delay=5.0,
            ),
        ]
    )
