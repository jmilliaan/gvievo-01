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
