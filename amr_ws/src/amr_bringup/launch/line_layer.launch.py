"""line_layer.launch.py: the tape follower, and nothing else (dual-product plan, Increment 1).

One node. Increment 1 follows straight tape and stops; there is no mission
store, no RFID station handling and no branch selection yet, so nothing has to
be handed to the layer to start it - which is why `_ready_line` waits only for
the layer's own LineState on the current generation and makes no RPC.

The node is REQUIRED: if the follower exits, the layer is gone, and the
supervisor must read that as a fault rather than leave LINE mode standing with
nothing driving. This matters more here than for a survey helper - the mux
keeps applying the last command only until its freshness window closes, so a
dead follower means a vehicle that coasts to a stop with the layer still
nominally up.

    generation:=N   stamped into LineState so consumers can drop old layers;
                    also selects the generation-private /amr/line_cmd topic
                    the mux subscribes to for this layer
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from amr_base import gating
from amr_bringup.launch_helpers import required


def _compose(context):
    generation = int(LaunchConfiguration("generation").perform(context))
    # The follower publishes on plain /amr/line_cmd; the mux of THIS generation
    # listens on the generation-private topic (unified plan §4.3 item 4), like
    # Nav2's cmd_vel in navigation_layer.launch.py. Without this remap the mux
    # sees "line: no fresh command" for the whole run (found in sim, 2026-09-21).
    line_cmd = gating.nav_topic("/amr/line_cmd", generation)
    return required(
        Node(
            package="amr_line",
            executable="line_follow_node",
            name="line_follow",
            output="screen",
            parameters=[
                {
                    "generation": generation,
                    # Increment 1 is a bench and first-floor-run increment.
                    # The mux applies the same ceiling independently.
                    "v_max_mps": 0.30,
                }
            ],
            remappings=[("/amr/line_cmd", line_cmd)],
        ),
        "line_follow",
    )


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("generation", default_value="0"),
            OpaqueFunction(function=_compose),
        ]
    )
