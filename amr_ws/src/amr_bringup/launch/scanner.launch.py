"""scanner.launch.py: the nanoScan3 driver and nothing else (unified plan U1).

No URDF here - base.launch.py owns the one robot_state_publisher. For a
standalone scanner + TF session use lidar.launch.py. ROS owns UDP 6060.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    params = os.path.join(get_package_share_directory("amr_bringup"), "config", "nanoscan3.yaml")
    return LaunchDescription(
        [
            Node(
                package="sick_safetyscanners2",
                executable="sick_safetyscanners2_node",
                name="sick_safetyscanners2_node",
                output="screen",
                emulate_tty=True,
                parameters=[params],
            ),
        ]
    )
