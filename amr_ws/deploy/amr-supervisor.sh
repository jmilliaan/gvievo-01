#!/bin/bash
# systemd entry point for the unified service. The supervisor starts web and
# hardware in IDLE, then enters LINE unless the profile says tracked=false;
# mapping/navigation are selected later by the operator.
set -eo pipefail

AMR_WORKSPACE="${AMR_WS:-$HOME/agv_can/amr_ws}"
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
source "$AMR_WORKSPACE/install/setup.bash"
source "$AMR_WORKSPACE/env/vehicle.sh"

export AMR_STATE_DIR="${AMR_STATE_DIR:-$HOME/.amr}"
export PYTHONUNBUFFERED=1

# Which vehicle (manuals/agv-02-plan.md R3): host gvipc-evo-NN must run profile agv-NN, read from
# $AMR_STATE_DIR/vehicle.env by vehicle.sh. A mismatch exits here, before anything opens can0 or the
# station link; systemd's restart limit then leaves the unit failed. Fix vehicle.env, then
# `sudo systemctl reset-failed amr && sudo systemctl start amr`.
python3 -m agv_core.identity

exec python3 -m amr_bringup.supervisor_node --ros-args \
  -p real:=true \
  -p maps_dir:="${AMR_MAPS_DIR:-$HOME/amr_maps}" \
  -p state_dir:="$AMR_STATE_DIR" \
  -p web:="${AMR_WEB:-true}" \
  -p lidar:="${AMR_LIDAR:-true}"
