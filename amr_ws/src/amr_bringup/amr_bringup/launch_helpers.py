"""Shared launch construction (unified plan §3.2, §3.3).

`required(node)` returns the node plus an exit handler that shuts the whole
launch down when that node exits - for ANY exit code. A ROS node that dies
would otherwise leave its `ros2 launch` parent alive and looking healthy;
the supervisor treats any unrequested layer termination as a fault, so a
launch must end when a required member ends. During an orderly shutdown the
handler fires too and is harmless (the launch is already stopping).

The handler also records which node it was, with its exit code, in
$AMR_STATE_DIR/exits/<role>.json (amr_bringup.exits, WP-H4), so the supervisor's
BASE_EXITED names the node instead of the launch leader. First exit wins.

`quiet_logs()` (WP-P4, S-`ros-log-bounding`): `--disable-external-lib-logs` for a node
whose output="screen" already reaches the role log, so it writes no second copy under
~/.ros/log (unbounded there: 7628 files, 59 MB on agv-01).
"""

from __future__ import annotations

import inspect
import os

from agv_core import paths
from ament_index_python.packages import get_package_share_directory
from launch.actions import IncludeLaunchDescription, RegisterEventHandler, Shutdown
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_ros.actions import Node

from amr_bringup import exits

QUIET_FLAG = "--disable-external-lib-logs"
# Sim only (WP-T2): fake_output_paths computes /output_paths from the synthetic scan, and the mux,
# follower and executor read it instead of assuming the field clear. Opt-in; never on a vehicle.
SIM_FIELDS_ENV = "AMR_SIM_FIELDS"


def sim_fields() -> bool:
    return os.environ.get(SIM_FIELDS_ENV, "").strip() == "1"


def field_source(real: bool) -> str:
    """The vehicle reads the scanner. The sim has none: the field is assumed clear there, and ONLY
    there, unless AMR_SIM_FIELDS=1 runs fake_output_paths (then the sim reads its /output_paths)."""
    return "scanner" if real or sim_fields() else "assume_clear"


def _on_required_exit(what: str):
    def on_exit(event, _context):
        exits.record(paths.state_dir(), os.environ.get(exits.ROLE_ENV, ""),
                     what, getattr(event, "returncode", None))
        return [Shutdown(reason=f"required process {what} exited")]

    return on_exit


def required(node: Node, what: str) -> list:
    return [
        node,
        RegisterEventHandler(OnProcessExit(target_action=node, on_exit=_on_required_exit(what))),
    ]


def quiet_logs() -> dict:
    """Node(...) keyword arguments that pass QUIET_FLAG as a ROS argument. `ros_arguments` where
    this launch_ros has it, else a second --ros-args block (rcl accepts several)."""
    if "ros_arguments" in inspect.signature(Node.__init__).parameters:
        return {"ros_arguments": [QUIET_FLAG]}
    return {"arguments": ["--ros-args", QUIET_FLAG]}


def include(package: str, launch_file: str, **launch_arguments) -> IncludeLaunchDescription:
    return IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(get_package_share_directory(package), "launch", launch_file)),
        launch_arguments={k: v for k, v in launch_arguments.items()}.items(),
    )


def default_world() -> str:
    return os.path.join(get_package_share_directory("amr_maps"), "worlds", "sim_factory", "world.yaml")
