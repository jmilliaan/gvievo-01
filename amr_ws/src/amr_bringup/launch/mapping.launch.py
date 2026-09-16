"""mapping.launch.py (spec §9): estimation chain + live async SLAM + session coordinator.

sim:=true   fake base/IMU + scan_synth against the sim_factory world
sim:=false  drivers.launch.py: drive_node on can0 + nanoScan3 (stop agv_controller first)
No AMCL, no route actions. `foxglove:=true` adds the bridge.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _sim_layer(context):
    if LaunchConfiguration("sim").perform(context).lower() != "true":
        return [
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(get_package_share_directory("amr_bringup"), "launch", "drivers.launch.py")
                ),
                launch_arguments={"lidar": "true", "foxglove": "false"}.items(),
            )
        ]
    return [
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                os.path.join(get_package_share_directory("amr_bringup"), "launch", "sim.launch.py")
            ),
            launch_arguments={"slip_noise_std": LaunchConfiguration("slip_noise_std")}.items(),
        ),
        Node(
            package="amr_sim",
            executable="scan_synth_node",
            name="scan_synth",
            output="screen",
            parameters=[
                {
                    "world_yaml": LaunchConfiguration("world_yaml"),
                    "clutter_count": LaunchConfiguration("clutter_count"),
                }
            ],
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    bringup = get_package_share_directory("amr_bringup")
    default_world = os.path.join(
        get_package_share_directory("amr_maps"), "worlds", "sim_factory", "world.yaml"
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("sim", default_value="true"),
            DeclareLaunchArgument("slip_noise_std", default_value="0.02"),
            DeclareLaunchArgument("world_yaml", default_value=default_world),
            DeclareLaunchArgument("clutter_count", default_value="0"),
            DeclareLaunchArgument("maps_dir", default_value=os.path.expanduser("~/amr_maps")),
            DeclareLaunchArgument("foxglove", default_value="false"),
            DeclareLaunchArgument("web", default_value="true", description="operator pages on :5001"),
            OpaqueFunction(function=_sim_layer),
            Node(
                package="amr_web",
                executable="web_node",
                name="amr_web",
                output="screen",
                parameters=[{"maps_dir": LaunchConfiguration("maps_dir")}],
                condition=IfCondition(LaunchConfiguration("web")),
            ),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                output="screen",
                parameters=[os.path.join(bringup, "config", "slam_mapping.yaml")],
            ),
            Node(
                package="amr_mission",
                executable="mapping_session_node",
                name="mapping_session",
                output="screen",
                parameters=[{"maps_dir": LaunchConfiguration("maps_dir")}],
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("foxglove_bridge"), "launch", "foxglove_bridge_launch.xml"
                    )
                ),
                condition=IfCondition(LaunchConfiguration("foxglove")),
            ),
        ]
    )
