"""drivers.launch.py (T9/T10): the REAL Layer 1 - drive_node on can0 (both BLV-R
drives + the MLS gyro), the nanoScan3, and the estimation chain above them.

Replaces sim.launch.py's fake base/IMU/scan for hardware runs:
    drive_node -> cmd_mux, diff_drive_odom, imu_bias, ekf_local -> URDF TF
    lidar:=true also includes lidar.launch.py (UDP 6060 must be free).

*** agv_controller must be stopped first *** - it owns can0 and the panel, and
two owners on one bus is exactly what spec §3.1 forbids. drive_node refuses to
start if the bus cannot be opened, and drive_node / panel_node refuse to
start while the agv_controller unit is active (amr_base.legacy_guard).

panel:=real (default) is panel_node (T12): the DIO island's Reset/Start/AUTO
and the horn coil. Without a valid /amr/panel_state the mux grants no
authority and the wheels stay at zero. panel:=fake is a SIMULATED panel for
bench work only - never with the vehicle on the floor and people nearby.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from amr_bringup import domains


def generate_launch_description() -> LaunchDescription:
    domains.require_vehicle_domain("drivers.launch.py")
    bringup = get_package_share_directory("amr_bringup")
    ekf_yaml = os.path.join(get_package_share_directory("amr_localization"), "config", "ekf.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "lidar", default_value="true", description="also start the nanoScan3 driver"
            ),
            DeclareLaunchArgument("foxglove", default_value="false"),
            DeclareLaunchArgument(
                "pc_loss_ms", default_value="500", description="drive-side PC-loss timeout (1016h); 0 = off"
            ),
            DeclareLaunchArgument(
                "feedback_hz", default_value="50.0", description="drive TPDO event timer rate"
            ),
            DeclareLaunchArgument(
                "gyro_sign", default_value="1.0", description="+1 if CCW reads positive on the vehicle"
            ),
            DeclareLaunchArgument(
                "panel",
                default_value="real",
                description="real (DIO island, T12) | fake (SIMULATED panel, bench only, MANUAL) | none",
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory("amr_description"), "launch", "description.launch.py"
                    )
                ),
            ),
            # --- Layer 1, real ---
            Node(
                package="amr_base",
                executable="drive_node",
                name="drive_node",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {
                        "pc_loss_ms": LaunchConfiguration("pc_loss_ms"),
                        "feedback_hz": LaunchConfiguration("feedback_hz"),
                        "gyro_sign": LaunchConfiguration("gyro_sign"),
                    }
                ],
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(os.path.join(bringup, "launch", "lidar.launch.py")),
                launch_arguments={"foxglove": "false"}.items(),
                condition=IfCondition(LaunchConfiguration("lidar")),
            ),
            Node(
                package="amr_sim",
                executable="fake_panel_node",
                name="fake_panel",
                output="screen",
                parameters=[{"auto": False}],
                condition=LaunchConfigurationEquals("panel", "fake"),
            ),
            Node(
                package="amr_base",
                executable="panel_node",
                name="panel_node",
                output="screen",
                condition=LaunchConfigurationEquals("panel", "real"),
            ),
            # --- Layer 2, same as sim.launch.py ---
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
