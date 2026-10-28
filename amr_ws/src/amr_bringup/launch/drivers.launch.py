"""drivers.launch.py: base.launch.py real:=true - the bench entry point.

Hardware Layer 1 plus the estimation chain: drive_node on can0, panel_node on
the DIO island (panel:=fake is a SIMULATED panel, bench only - never with the
vehicle on the floor and people nearby), nanoScan3, mux/odom/bias/EKF, URDF.
drive_node and panel_node take the can/dio owner locks (agv_core.ownerlock), so a
second owner refuses to start. Needs ROS_DOMAIN_ID=10 (env/vehicle.sh).
"""

from agv_core import config
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

from amr_bringup.launch_helpers import include


def generate_launch_description() -> LaunchDescription:
    cfg = LaunchConfiguration
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "lidar", default_value="true", description="also start the nanoScan3 driver"
            ),
            DeclareLaunchArgument(
                "pc_loss_ms", default_value=str(config.PC_LOSS_MS), description="1016h on the drives; 0 = off"
            ),
            DeclareLaunchArgument(
                "feedback_hz",
                default_value=str(config.DRIVE_FEEDBACK_HZ),
                description="drive TPDO event timer rate",
            ),
            DeclareLaunchArgument("gyro_sign", default_value="1.0", description="+1 if CCW reads positive"),
            DeclareLaunchArgument(
                "panel", default_value="real", description="real (DIO island) | fake (SIMULATED, bench only)"
            ),
            include(
                "amr_bringup",
                "base.launch.py",
                real="true",
                lidar=cfg("lidar"),
                pc_loss_ms=cfg("pc_loss_ms"),
                feedback_hz=cfg("feedback_hz"),
                gyro_sign=cfg("gyro_sign"),
                panel=cfg("panel"),
            ),
        ]
    )
