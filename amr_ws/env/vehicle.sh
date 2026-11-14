# Source this in a shell that will run HARDWARE launches (drivers/mapping/nav
# with sim:=false). amr_bringup.domains enforces it: a hardware launch in any
# other domain refuses to start. ~/.bashrc sources this by default on the vehicle.
export ROS_DOMAIN_ID=10
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$HOME/agv_can/amr_ws/src/amr_bringup/config/cyclonedds-local.xml"

# The vehicle library at the repo root, so `ros2 run amr_base drive_node` and a
# bare `python3 -c "from agv_core import config"` resolve the same code. The only
# place PYTHONPATH is set: amr.service gets it through amr-supervisor.sh sourcing
# this file. AGV_CAN_ROOT overrides the root.
export PYTHONPATH="${AGV_CAN_ROOT:-$HOME/agv_can}${PYTHONPATH:+:$PYTHONPATH}"

# Which vehicle this PC is (manuals/agv-02-plan.md R1): one local line, never in the repo,
#   AGV_PROFILE=agv-02
# in $AMR_STATE_DIR/vehicle.env. No file: the default profile (agv-01). An AGV_PROFILE already in the
# environment wins, so `AGV_PROFILE=agv-01 python3 ...` still works in a shell. Only that one key, a
# plain name, is read: the file is data, not a script. agv_core.identity checks the result against
# the host name before the service starts anything.
_amr_vehicle_env="${AMR_STATE_DIR:-$HOME/.amr}/vehicle.env"
if [ -z "${AGV_PROFILE:-}" ] && [ -f "$_amr_vehicle_env" ]; then
  _amr_profile=$(sed -n 's/^[[:space:]]*AGV_PROFILE=\([A-Za-z0-9_-]\{1,32\}\)[[:space:]]*$/\1/p' \
    "$_amr_vehicle_env" | tail -n 1)
  if [ -n "$_amr_profile" ]; then
    export AGV_PROFILE="$_amr_profile"
  else
    echo "vehicle.sh: $_amr_vehicle_env has no AGV_PROFILE=<name> line; the default profile applies" >&2
  fi
fi
unset _amr_vehicle_env _amr_profile
