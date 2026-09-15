"""nanoScan3 only: sick_safetyscanners2 + robot_state_publisher (static TF from the URDF).

First-milestone launch (P2, lidar half). Add `foxglove:=true` to also start
foxglove_bridge on :8765. URDF args pass through, e.g. `laser_x:=0.42`.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    bringup = get_package_share_directory("amr_bringup")
    params = os.path.join(bringup, "config", "nanoscan3.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "foxglove",
                default_value="false",
                description="Also start foxglove_bridge on :8765",
            ),
            Node(
                package="sick_safetyscanners2",
                executable="sick_safetyscanners2_node",
                name="sick_safetyscanners2_node",
                output="screen",
                emulate_tty=True,
                parameters=[params],
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("amr_description"),
                        "launch",
                        "description.launch.py",
                    )
                ),
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("foxglove_bridge"),
                        "launch",
                        "foxglove_bridge_launch.xml",
                    )
                ),
                condition=IfCondition(LaunchConfiguration("foxglove")),
            ),
        ]
    )
