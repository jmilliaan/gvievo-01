"""nav.launch.py (spec §9): immutable saved map, AMCL, readiness. Grows through T5-T8.

sim:=true   fake base/IMU + scan_synth (clutter optional) + the estimation chain
sim:=false  real drivers: NOT wired until T9/T10 (raises)

The bundle <maps_dir>/<map_id>/rev<revision>/ is verified (hashes) before
anything starts; a bundle that fails verification refuses to launch. No SLAM
here: mapping.launch.py and nav.launch.py are mutually exclusive.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _resolve(context):
    from amr_mission import map_bundle as mb  # noqa: PLC0415 - launch-time import

    maps_dir = os.path.expanduser(LaunchConfiguration("maps_dir").perform(context))
    map_id = LaunchConfiguration("map_id").perform(context)
    revision = LaunchConfiguration("revision").perform(context)
    if revision in ("", "latest"):
        revs = mb.list_revisions(maps_dir, map_id)
        if not revs:
            raise RuntimeError(f"no revisions of '{map_id}' under {maps_dir}")
        revision = revs[-1]
    rev_dir = mb.revision_dir(maps_dir, map_id, int(revision))
    manifest = mb.verify(rev_dir)  # raises BundleError on any mismatch
    map_yaml = os.path.join(rev_dir, "map.yaml")

    from amr_navigation import footprint as fpmod  # noqa: PLC0415

    loc = get_package_share_directory("amr_localization")
    params = os.path.join(loc, "config", "amcl.yaml")
    nav2 = os.path.join(get_package_share_directory("amr_navigation"), "config", "nav2_params.yaml")
    footprint_yaml = LaunchConfiguration("footprint_yaml").perform(context) or fpmod.default_path()
    footprint = fpmod.load(footprint_yaml).as_costmap_string()  # single source of truth, injected
    actions = [
        Node(
            package="nav2_map_server",
            executable="map_server",
            name="map_server",
            output="screen",
            parameters=[params, {"yaml_filename": map_yaml}],
        ),
        Node(package="nav2_amcl", executable="amcl", name="amcl", output="screen", parameters=[params]),
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package="nav2_lifecycle_manager",
                    executable="lifecycle_manager",
                    name="lifecycle_manager_localization",
                    output="screen",
                    parameters=[params],
                )
            ],
        ),
        Node(
            package="amr_localization",
            executable="localization_monitor_node",
            name="localization_monitor",
            output="screen",
        ),
        # --- T7: straights and turns (spec §5). No planner, no BT: nothing undrawn can move the vehicle.
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            output="screen",
            parameters=[nav2, {"local_costmap.local_costmap.footprint": footprint}],
            remappings=[("cmd_vel", "/cmd_vel")],
        ),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            output="screen",
            parameters=[nav2],
            remappings=[("cmd_vel", "/cmd_vel_rotate")],
        ),
        # Started late so the servers' lifecycle services exist under startup load;
        # the manager gives up (not retries) when a get_state call fails.
        TimerAction(
            period=6.0,
            actions=[
                Node(
                    package="nav2_lifecycle_manager",
                    executable="lifecycle_manager",
                    name="lifecycle_manager_navigation",
                    output="screen",
                    parameters=[nav2],
                )
            ],
        ),
        Node(
            package="amr_mission",
            executable="route_executor_node",
            name="route_executor",
            output="screen",
            parameters=[{"maps_dir": maps_dir, "footprint_yaml": footprint_yaml}],
        ),
        Node(
            package="amr_web",
            executable="web_node",
            name="amr_web",
            output="screen",
            parameters=[{"maps_dir": maps_dir}],
            condition=IfCondition(LaunchConfiguration("web")),
        ),
    ]
    if LaunchConfiguration("sim").perform(context).lower() != "true":
        raise RuntimeError("nav.launch.py sim:=false needs drivers.launch.py (T9/T10); not available yet")
    actions += [
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                os.path.join(get_package_share_directory("amr_bringup"), "launch", "sim.launch.py")
            ),
            launch_arguments={
                "slip_noise_std": LaunchConfiguration("slip_noise_std"),
                "panel_auto": LaunchConfiguration("panel_auto"),
            }.items(),
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
    print(f"[nav.launch] map {map_id} rev{revision} bundle {manifest.sha256[:12]} ({map_yaml})")
    return actions


def generate_launch_description() -> LaunchDescription:
    default_world = os.path.join(
        get_package_share_directory("amr_maps"), "worlds", "sim_factory", "world.yaml"
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("sim", default_value="true"),
            DeclareLaunchArgument("maps_dir", default_value=os.path.expanduser("~/amr_maps")),
            DeclareLaunchArgument("map_id", default_value="sim_factory"),
            DeclareLaunchArgument("revision", default_value="latest"),
            DeclareLaunchArgument("slip_noise_std", default_value="0.02"),
            DeclareLaunchArgument("world_yaml", default_value=default_world),
            DeclareLaunchArgument("clutter_count", default_value="0"),
            DeclareLaunchArgument("foxglove", default_value="false"),
            DeclareLaunchArgument("web", default_value="true", description="operator pages on :5001"),
            DeclareLaunchArgument(
                "footprint_yaml", default_value="", description="override amr_description's footprint.yaml"
            ),
            DeclareLaunchArgument("panel_auto", default_value="false"),
            OpaqueFunction(function=_resolve),
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
