"""base.launch.py: the persistent base layer (unified plan §3.1, U1).

    supervised:=true   mux and drive_node require the supervisor's ControlLease
                       and the keyboard teleop input is off (production);
                       false = unsupervised bench (wrappers), no lease needed
    real:=true    drive_node (can0), panel_node (DIO) or fake panel, nanoScan3
    real:=false   fake_base, fake_imu, fake_panel, optional scan_synth
    both          exactly one robot_state_publisher, cmd_mux, diff_drive_odom,
                  imu_bias, ekf_local

No web app, no Foxglove, no SLAM, no AMCL: those are the supervisor's other
groups. Every node listed as REQUIRED ends the launch when it exits, so a
dead node cannot hide behind a live `ros2 launch` parent.

Domain guard: real:=true needs ROS_DOMAIN_ID=10; real:=false refuses it.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from amr_bringup import domains
from amr_bringup.launch_helpers import default_world, include, required


def _compose(context):
    real = LaunchConfiguration("real").perform(context).lower() == "true"
    what = f"base.launch.py real:={str(real).lower()}"
    domains.require_vehicle_domain(what) if real else domains.refuse_vehicle_domain(what)
    ekf_yaml = os.path.join(get_package_share_directory("amr_localization"), "config", "ekf.yaml")
    cfg = LaunchConfiguration
    supervised = cfg("supervised").perform(context).lower() == "true"
    gate = {"require_supervisor": supervised}

    actions = [include("amr_description", "description.launch.py")]
    if real:
        actions += required(
            Node(
                package="amr_base",
                executable="drive_node",
                name="drive_node",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {
                        "pc_loss_ms": cfg("pc_loss_ms"),
                        "feedback_hz": cfg("feedback_hz"),
                        "gyro_sign": cfg("gyro_sign"),
                        **gate,
                    }
                ],
            ),
            "drive_node",
        )
        actions += required(
            Node(
                package="amr_base",
                executable="panel_node",
                name="panel_node",
                output="screen",
                condition=LaunchConfigurationEquals("panel", "real"),
            ),
            "panel_node",
        )
        actions.append(
            Node(
                package="amr_sim",
                executable="fake_panel_node",
                name="fake_panel",
                output="screen",
                parameters=[{"auto": False}],
                condition=LaunchConfigurationEquals("panel", "fake"),
            )
        )
        if cfg("lidar").perform(context).lower() == "true":
            actions.append(include("amr_bringup", "scanner.launch.py"))
    else:
        actions += required(
            Node(
                package="amr_sim",
                executable="fake_base_node",
                name="fake_base",
                output="screen",
                parameters=[{"slip_noise_std": cfg("slip_noise_std"), **gate}],
            ),
            "fake_base",
        )
        actions.append(Node(package="amr_sim", executable="fake_imu_node", name="fake_imu", output="screen"))
        actions.append(
            Node(
                package="amr_sim",
                executable="fake_panel_node",
                name="fake_panel",
                output="screen",
                parameters=[{"auto": cfg("panel_auto")}],
            )
        )
        actions.append(
            Node(
                package="amr_sim",
                executable="scan_synth_node",
                name="scan_synth",
                output="screen",
                parameters=[{"world_yaml": cfg("world_yaml"), "clutter_count": cfg("clutter_count")}],
                condition=IfCondition(cfg("scan_synth")),
            )
        )
    actions += required(
        Node(
            package="amr_base",
            executable="cmd_mux_kinematics_node",
            name="cmd_mux_kinematics",
            output="screen",
            parameters=[{**gate, "teleop_enabled": not supervised}],
        ),
        "cmd_mux_kinematics",
    )
    actions += required(
        Node(package="amr_base", executable="diff_drive_odom_node", name="diff_drive_odom", output="screen"),
        "diff_drive_odom",
    )
    actions.append(
        Node(package="amr_localization", executable="imu_bias_node", name="imu_bias", output="screen")
    )
    actions += required(
        Node(
            package="robot_localization",
            executable="ekf_node",
            name="ekf_local",
            output="screen",
            parameters=[ekf_yaml],
        ),
        "ekf_local",
    )
    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("real", default_value="false", description="true = vehicle hardware"),
            DeclareLaunchArgument(
                "supervised", default_value="false", description="true = ControlLease required (production)"
            ),
            # hardware
            DeclareLaunchArgument(
                "lidar", default_value="true", description="real: also start the nanoScan3"
            ),
            DeclareLaunchArgument("pc_loss_ms", default_value="500"),
            DeclareLaunchArgument("feedback_hz", default_value="50.0"),
            DeclareLaunchArgument("gyro_sign", default_value="1.0"),
            DeclareLaunchArgument(
                "panel", default_value="real", description="real: DIO island | fake: SIMULATED, bench only"
            ),
            # simulation
            DeclareLaunchArgument("slip_noise_std", default_value="0.0"),
            DeclareLaunchArgument("panel_auto", default_value="false"),
            DeclareLaunchArgument("scan_synth", default_value="false", description="sim: raycast the world"),
            DeclareLaunchArgument("world_yaml", default_value=default_world()),
            DeclareLaunchArgument("clutter_count", default_value="0"),
            OpaqueFunction(function=_compose),
        ]
    )
