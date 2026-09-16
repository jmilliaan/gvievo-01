#!/bin/bash
# systemd ExecStart wrapper: a unit cannot `source`, and every ROS process on
# the vehicle must come up in the same overlay, domain and DDS scope as an
# interactive shell (amr_ws/README.md "ROS domain / DDS scope"), or custom
# amr_interfaces messages will not decode and nodes will not discover each other.
set -eo pipefail  # no -u: the ROS setup scripts read unset variables
WS="${AMR_WS:-$HOME/agv_can/amr_ws}"
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
source "$WS/env/vehicle.sh"
export PYTHONUNBUFFERED=1
exec ros2 launch "$@"
