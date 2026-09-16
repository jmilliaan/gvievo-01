"""sim.launch.py (spec §9): amr_sim Layer-1 fakes + the real estimation chain.

fake_base + fake_imu  ->  cmd_mux, diff_drive_odom, imu_bias, ekf_local  ->  robot_state_publisher.
No hardware is touched. `foxglove:=true` adds the bridge; drive it with
`ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_teleop`.
The EKF owns odom->base_footprint; diff_drive_odom publishes no TF here.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from amr_bringup import domains


def generate_launch_description() -> LaunchDescription:
    domains.refuse_vehicle_domain("sim.launch.py")
    slip = LaunchConfiguration("slip_noise_std")
    ekf_yaml = os.path.join(get_package_share_directory("amr_localization"), "config", "ekf.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "slip_noise_std", default_value="0.0", description="fake_base wheel slip noise (fraction, 1σ)"
            ),
            DeclareLaunchArgument(
                "panel_auto", default_value="false", description="fake panel selector starts in AUTO"
            ),
            DeclareLaunchArgument(
                "foxglove", default_value="false", description="Also start foxglove_bridge on :8765"
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("amr_description"), "launch", "description.launch.py"
                    )
                ),
            ),
            # --- Layer 1, simulated ---
            Node(
                package="amr_sim",
                executable="fake_base_node",
                name="fake_base",
                output="screen",
                parameters=[{"slip_noise_std": slip}],
            ),
            Node(package="amr_sim", executable="fake_imu_node", name="fake_imu", output="screen"),
            # The panel is authority for the mux: MANUAL here, so teleop works in plain sim.
            Node(
                package="amr_sim",
                executable="fake_panel_node",
                name="fake_panel",
                output="screen",
                parameters=[{"auto": LaunchConfiguration("panel_auto")}],
            ),
            # --- Layer 2, real ---
            Node(
                package="amr_base",
                executable="cmd_mux_kinematics_node",
                name="cmd_mux_kinematics",
                output="screen",
            ),
            Node(
                package="amr_base", executable="diff_drive_odom_node", name="diff_drive_odom", output="screen"
            ),
            Node(package="amr_localization", executable="imu_bias_node", name="imu_bias", output="screen"),
            Node(
                package="robot_localization",
                executable="ekf_node",
                name="ekf_local",
                output="screen",
                parameters=[ekf_yaml],
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
