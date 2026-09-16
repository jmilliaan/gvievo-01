#!/bin/bash
# systemd entry point for the unified service. The supervisor starts web and
# hardware in IDLE; mapping/navigation are selected later by the operator.
set -eo pipefail

AMR_WORKSPACE="${AMR_WS:-$HOME/agv_can/amr_ws}"
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
source "$AMR_WORKSPACE/install/setup.bash"
source "$AMR_WORKSPACE/env/vehicle.sh"

export AMR_STATE_DIR="${AMR_STATE_DIR:-$HOME/.amr}"
export PYTHONUNBUFFERED=1

exec python3 -m amr_bringup.supervisor_node --ros-args \
  -p real:=true \
  -p maps_dir:="${AMR_MAPS_DIR:-$HOME/amr_maps}" \
  -p state_dir:="$AMR_STATE_DIR" \
  -p web:="${AMR_WEB:-true}" \
  -p foxglove:="${AMR_FOXGLOVE:-true}" \
  -p lidar:="${AMR_LIDAR:-true}"
