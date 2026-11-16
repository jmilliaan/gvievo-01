"""base.launch.py: the persistent base layer (unified plan §3.1, U1).

    supervised:=true   mux and drive_node require the supervisor's ControlLease
                       and the keyboard teleop input is off (production);
                       false = unsupervised bench (wrappers), no lease needed
    real:=true    drive_node (can0), panel_node (DIO) or fake panel, nanoScan3
    real:=false   fake_base, fake_imu, fake_panel, optional scan_synth, + diff_drive_odom,
                  imu_bias (drive_node does both on the vehicle, WP-C5/C10, 2026-11-16)
    both          exactly one robot_state_publisher, cmd_mux, scan_gate, ekf_local

No web app, no SLAM, no AMCL: those are the supervisor's other
groups. Every node listed as REQUIRED ends the launch when it exits, so a
dead node cannot hide behind a live `ros2 launch` parent. Every other node respawns
(the station bridge, the scanners, trolley_node, imu_bias) or is sim-only:
test_launch_layers' walk holds that list (unified plan WP-H4).

The event recorder (WP-H3) writes /amr/events and /amr/device_health to the state dir in
every base, respawning and optional. The black box (WP-P6, amr_bringup.blackbox) runs only with
blackbox:=true (env AMR_BLACKBOX, default off until the owner's pidstat check): a snapshot-mode
`ros2 bag record` (node amr_blackbox) plus its trigger, both respawning, neither required.

The RFID reader starts only with the profile's rfid.enabled (decision 23, 2026-11-16:
RFID is not used; false on both units). Every node here passes
--disable-external-lib-logs (launch_helpers.quiet_logs, WP-P4): its output="screen"
already reaches logs/base.log, so it writes no second copy under ~/.ros/log.

Domain guard: real:=true needs ROS_DOMAIN_ID=10; real:=false refuses it.
"""

import os
import sys

from agv_core import config, paths
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from amr_bringup import blackbox, domains, scanner_fields
from amr_bringup.launch_helpers import (
    QUIET_FLAG,
    default_world,
    field_source,
    include,
    quiet_logs,
    required,
    sim_fields,
)


def _compose(context):
    real = LaunchConfiguration("real").perform(context).lower() == "true"
    what = f"base.launch.py real:={str(real).lower()}"
    domains.require_vehicle_domain(what) if real else domains.refuse_vehicle_domain(what)
    ekf_yaml = os.path.join(get_package_share_directory("amr_localization"), "config", "ekf.yaml")
    cfg = LaunchConfiguration
    supervised = cfg("supervised").perform(context).lower() == "true"
    gate = {"require_supervisor": supervised}

    rear_scanner = real and config.REAR_SOURCE == "scanner"
    description = {}
    if rear_scanner:
        description = {"rear_lidar": "true", "rear_laser_x": str(config.REAR_LASER_X_M),
                       "rear_laser_y": str(config.REAR_LASER_Y_M), "rear_laser_z": str(config.REAR_LASER_Z_M),
                       "rear_laser_yaw": str(config.REAR_LASER_YAW_RAD)}
    actions = [include("amr_description", "description.launch.py", **description)]
    if config.STATION_ENABLED:
        # manuals/station-call-plan.md. Not required: a dead bridge must not end the base. An order
        # already running finishes without it. In base, so it reports STARTUP through layer changes.
        actions.append(
            Node(
                package="amr_station",
                executable="station_bridge_node",
                name="station_bridge",
                output="screen",
                **quiet_logs(),
                respawn=True,
                respawn_delay=5.0,
                parameters=[{"state_dir": paths.state_dir()}],
            )
        )
    if real:
        actions += required(
            Node(
                package="amr_base",
                executable="drive_node",
                name="drive_node",
                output="screen",
                **quiet_logs(),
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
                **quiet_logs(),
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
                **quiet_logs(),
                parameters=[{"auto": False}],
                condition=LaunchConfigurationEquals("panel", "fake"),
            )
        )
        if cfg("lidar").perform(context).lower() == "true":
            actions.append(include("amr_bringup", "scanner.launch.py"))
        if rear_scanner:
            # The rear lidar (station plan P4): set at P8, not by the switch. Only trolley_node reads
            # it: no costmap, AMCL or mux. Optional and respawning, like the RFID reader.
            actions.append(include("amr_bringup", "rear_scanner.launch.py"))
            actions.append(
                Node(
                    package="amr_base",
                    executable="trolley_node",
                    name="trolley_node",
                    output="screen",
                    **quiet_logs(),
                    respawn=True,
                    respawn_delay=5.0,
                )
            )
        # RFID reader (2026-10-02): optional - a missing reader leaves plain line
        # following and SLAM untouched; respawns so a late cable recovers by itself.
        # Only when the profile enables it (decision 23: not used; false on both units).
        if config.RFID_ENABLED:
            actions.append(
                Node(
                    package="amr_base",
                    executable="rfid_node",
                    name="rfid_node",
                    output="screen",
                    **quiet_logs(),
                    respawn=True,
                    respawn_delay=5.0,
                )
            )
    else:
        actions += required(
            Node(
                package="amr_sim",
                executable="fake_base_node",
                name="fake_base",
                output="screen",
                **quiet_logs(),
                parameters=[{"slip_noise_std": cfg("slip_noise_std"), **gate}],
            ),
            "fake_base",
        )
        actions.append(Node(package="amr_sim", executable="fake_imu_node", name="fake_imu", output="screen",
                                    **quiet_logs()))
        # SIM ONLY since WP-C5/C10 (2026-11-16): on the vehicle drive_node publishes /odom_raw and the
        # bias-corrected /imu/data itself. Running these there too would put two publishers on each.
        actions += required(
            Node(package="amr_base", executable="diff_drive_odom_node", name="diff_drive_odom", output="screen",
                 **quiet_logs()),
            "diff_drive_odom",
        )
        # Not required (a dead bias filter must not end the base), so it respawns (WP-H4, H-P1-5).
        actions.append(
            Node(package="amr_localization", executable="imu_bias_node", name="imu_bias", output="screen",
                 respawn=True, respawn_delay=2.0, **quiet_logs())
        )
        if config.STATION_ENABLED:
            # The sim's rear lidar. Never on real:=true: there is no bypass on a vehicle.
            actions.append(
                Node(package="amr_sim", executable="fake_trolley_node", name="fake_trolley", output="screen",
                     **quiet_logs())
            )
        actions.append(
            Node(
                package="amr_sim",
                executable="fake_panel_node",
                name="fake_panel",
                output="screen",
                **quiet_logs(),
                parameters=[{"auto": cfg("panel_auto")}],
            )
        )
        if sim_fields():
            # SIM ONLY (WP-T2): /output_paths from scan_synth's /scan and the field rectangles, so the
            # sim exercises field stops through the real mux. Needs scan_synth:=true. Never a field
            # monitor, never on real:=true (test_launch_layers).
            actions.append(
                Node(package="amr_sim", executable="fake_output_paths_node", name="fake_output_paths",
                     output="screen", **quiet_logs(),
                     parameters=[{"fields_yaml": scanner_fields.default_path()}])
            )
        actions.append(
            Node(
                package="amr_sim",
                executable="scan_synth_node",
                name="scan_synth",
                output="screen",
                **quiet_logs(),
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
            **quiet_logs(),
            # Autonomous starts at 0.3 m/s^2 (2026-10-02, was 0.15): 2.0 s to the 0.60 trackless
            # speed, 2.5 s to the 0.75 tracked cruise; 0.85 s to 0.34 rad/s. Stops
            # at the hardware-class 0.5 m/s^2 / 1.0 rad/s^2, stated explicitly: leaving delta_max at
            # its "same as alpha_max" default made every Spin coast 2.6 deg past its target
            # (0.19 rad/s stopped at 0.4 rad/s^2, vehicle 2026-09-17).
            # Manual (pendant / browser jog, 2026-09-18): the node's defaults - 0.6 m/s (2026-10-28),
            # S-curve to 0.3 m/s^2 with 1.0 m/s^3, arcs with the slow wheel at 66 % of the fast one, spins at
            # 0.39 rad/s, 0.27 rad/s while surveying (gating.DEFAULT and the mux's own params).
            parameters=[
                {
                    **gate,
                    "teleop_enabled": not supervised,
                    # Scanner fields gate AUTO (2026-10-02). The sim has no scanner, so there
                    # and ONLY there the fields are assumed clear.
                    "field_source": field_source(real),
                    # path indices, polarity, the x0.5 factor and the warning-2 stop distance: config/scanner_fields.yaml
                    **scanner_fields.mux_params(scanner_fields.load()),
                    "a_max": 0.3,
                    "alpha_max": 0.4,
                    "d_max": 0.5,
                    "delta_max": 1.0,
                }
            ],
        ),
        "cmd_mux_kinematics",
    )
    # /scan_gated for slam_toolbox and AMCL: scans released only once their odom
    # transform exists, so their tf2 MessageFilters take the synchronous path
    # (the asynchronous one hung slam_toolbox on the vehicle, 2026-09-17).
    actions += required(
        Node(package="amr_localization", executable="scan_gate_node", name="scan_gate", output="screen",
             **quiet_logs()),
        "scan_gate",
    )
    if supervised:  # the /blind replacement (unified plan §7.2); an exclusive IDLE substate
        # REQUIRED since WP-H4 (H-P1-5): it can drive the wheels (blind runs), so a dead one
        # must end the base and say so, not leave a half-done job behind a live launch.
        actions += required(
            Node(
                package="amr_base",
                executable="commissioning_node",
                name="commissioning_node",
                output="screen",
                **quiet_logs(),
                parameters=[{"state_dir": paths.state_dir()}],
            ),
            "commissioning_node",
        )
    # Forensics independent of the web (WP-H3): optional, so it respawns and never ends the base.
    actions.append(
        Node(
            package="amr_base",
            executable="event_recorder_node",
            name="event_recorder",
            output="screen",
            **quiet_logs(),
            respawn=True,
            respawn_delay=2.0,
            parameters=[{"state_dir": paths.state_dir()}],
        )
    )
    if blackbox.enabled(cfg("blackbox").perform(context)):
        actions += _blackbox(int(cfg("blackbox_cache_mb").perform(context)))
    actions += required(
        Node(
            package="robot_localization",
            executable="ekf_node",
            name="ekf_local",
            output="screen",
            **quiet_logs(),
            parameters=[ekf_yaml],
        ),
        "ekf_local",
    )
    return actions


def _blackbox(cache_mb: int) -> list:
    """The black box (WP-P6): the recorder and its trigger. Never required(): a dead one respawns
    and the vehicle carries on. Both outputs reach logs/base.log."""
    state_dir = paths.state_dir()
    return [
        ExecuteProcess(cmd=blackbox.recorder_cmd(state_dir, cache_mb), name="blackbox_recorder",
                       output="screen", respawn=True, respawn_delay=5.0),
        ExecuteProcess(
            cmd=[sys.executable, "-m", "amr_bringup.blackbox_node", "--ros-args", QUIET_FLAG, "-p",
                 f"state_dir:={state_dir}"],
            name="blackbox_trigger", output="screen", respawn=True, respawn_delay=5.0,
        ),
    ]


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
            # the profile's freshness block (WP-A10); a bench run may override them
            DeclareLaunchArgument("pc_loss_ms", default_value=str(config.PC_LOSS_MS)),
            DeclareLaunchArgument("feedback_hz", default_value=str(config.DRIVE_FEEDBACK_HZ)),
            DeclareLaunchArgument("gyro_sign", default_value="1.0"),
            # the black box (WP-P6): off until the owner's pidstat check (plan §6 OP-1)
            DeclareLaunchArgument("blackbox", default_value=os.environ.get(blackbox.ENV, "false")),
            DeclareLaunchArgument("blackbox_cache_mb", default_value=str(blackbox.CACHE_MB)),
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
