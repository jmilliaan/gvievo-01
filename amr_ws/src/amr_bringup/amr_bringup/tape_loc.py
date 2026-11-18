"""The localization group for tape-graph localization (tracked plan 3, sections 2.1, 2.7).

One verified map revision -> map_server, AMCL, the localization lifecycle manager, and
(in the LINE layer) the readiness monitor. Shared by line_layer.launch.py (profile
tape_loc.enabled) and p0_localization.launch.py (P0 measurement beside a running LINE
layer). EKF and scan_gate already run in base.

Nothing here commands motion: the group publishes /amcl_pose, /particle_cloud, the
map->odom transform and /amr/localization_state.
"""

from __future__ import annotations

import math
import os

from ament_index_python.packages import get_package_share_directory
from launch.actions import ExecuteProcess, TimerAction
from launch_ros.actions import Node

from amr_bringup.launch_helpers import quiet_logs, required

# Plan section 2.7: the tape removes most of the search, so fewer particles may do.
PARAM_SETS = {
    "default": {},
    "lean": {"max_particles": 800, "update_min_d": 0.10, "update_min_a": 0.05},
}


def verified_map(maps_dir: str, map_id: str, revision) -> tuple[str, int, object]:
    """(map.yaml, revision, manifest); raises map_bundle.BundleError on any hash mismatch."""
    from amr_mission import map_bundle as mb  # noqa: PLC0415 - launch-time import

    if revision in ("", "latest", None):
        revs = mb.list_revisions(maps_dir, map_id)
        if not revs:
            raise mb.BundleError(f"no revisions of '{map_id}' under {maps_dir}")
        revision = revs[-1]
    revision = int(revision)
    rev_dir = mb.revision_dir(maps_dir, map_id, revision)
    manifest = mb.load_manifest(rev_dir, map_id, revision)
    return os.path.join(rev_dir, "map.yaml"), revision, manifest


def initial_pose_cmd(start: dict, delay_s: float) -> TimerAction:
    """Publish the survey-start pose once, after AMCL is active (P0 initial:=start)."""
    x, y, yaw = float(start["x_m"]), float(start["y_m"]), float(start["yaw_rad"])
    from amr_line.tape_locator import initial_pose_cov  # noqa: PLC0415 - launch-time import

    cov = initial_pose_cov()
    msg = (
        f"{{header: {{frame_id: map}}, pose: {{pose: {{position: {{x: {x:f}, y: {y:f}}}, "
        f"orientation: {{z: {math.sin(yaw / 2.0):f}, w: {math.cos(yaw / 2.0):f}}}}}, "
        f"covariance: [{', '.join(f'{c:g}' for c in cov)}]}}}}"
    )
    return TimerAction(
        period=delay_s,
        actions=[
            ExecuteProcess(
                cmd=["ros2", "topic", "pub", "-w", "1", "--once", "/initialpose",
                     "geometry_msgs/msg/PoseWithCovarianceStamped", msg],
                output="screen",
            )
        ],
    )


def group(map_yaml: str, *, params_set: str = "default", generation: int = 0, monitor: bool = True,
          dynamic_yaml: str = "", require: bool = True, jump_dist_m: float | None = None,
          autostart: bool = True, map_loc_yaml: str | None = None) -> list:
    """The launch actions, for both layers (L D53: the LINE layer's tape localization and the
    navigation layer build the group here, once). require=True: map_server, AMCL, the lifecycle
    manager or the monitor exiting ends the launch (the supervisor then reports LAYER_EXITED).
    The manager runs with bond_timeout 0 (amcl.yaml, WP-C15): required() is what catches a dead node.

    autostart: false when the supervisor drives the manager itself (navigation layer).
    map_loc_yaml: AMCL localises on this derived map, served by a second map_server on /map_loc
    (navigation_layer blank_dynamic); /map stays the reviewed map."""
    if params_set not in PARAM_SETS:
        raise ValueError(f"params {params_set!r}: expected one of {sorted(PARAM_SETS)}")
    params = os.path.join(get_package_share_directory("amr_localization"), "config", "amcl.yaml")

    def node(n: Node, what: str) -> list:
        return required(n, what) if require else [n]

    actions = node(
        Node(package="nav2_map_server", executable="map_server", name="map_server", output="screen",
             **quiet_logs(), parameters=[params, {"yaml_filename": map_yaml}]),
        "map_server",
    )
    lifecycle = {"autostart": autostart}
    amcl_remap = []
    if map_loc_yaml:
        actions += node(
            Node(package="nav2_map_server", executable="map_server", name="map_server_loc", output="screen",
                 **quiet_logs(), parameters=[params, {"yaml_filename": map_loc_yaml, "topic_name": "map_loc",
                                      "frame_id": "map"}]),
            "map_server_loc",
        )
        amcl_remap = [("map", "map_loc")]
        lifecycle["node_names"] = ["map_server", "map_server_loc", "amcl"]
    actions += node(
        Node(package="nav2_amcl", executable="amcl", name="amcl", output="screen", **quiet_logs(),
             parameters=[params, PARAM_SETS[params_set]], remappings=amcl_remap),
        "amcl",
    )
    # REQUIRED like the nodes it manages (WP-H4): with no bond, a dead manager would go unseen.
    actions.append(
        TimerAction(period=3.0, actions=node(
            Node(package="nav2_lifecycle_manager", executable="lifecycle_manager",
                 name="lifecycle_manager_localization", output="screen", **quiet_logs(),
                 parameters=[params, lifecycle]),
            "lifecycle_manager_localization",
        ))
    )
    if monitor:
        actions += node(
            Node(package="amr_localization", executable="localization_monitor_node",
                 name="localization_monitor", output="screen", **quiet_logs(),
                 parameters=[{"generation": generation, "dynamic_yaml": dynamic_yaml,
                              **({} if jump_dist_m is None else {"jump_dist_m": float(jump_dist_m)})}]),
            "localization_monitor",
        )
    return actions
