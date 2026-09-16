# Source this in a shell that will run HARDWARE launches (drivers/mapping/nav
# with sim:=false). amr_bringup.domains enforces it: a hardware launch in any
# other domain refuses to start. ~/.bashrc sources this by default on the vehicle.
export ROS_DOMAIN_ID=10
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$HOME/agv_can/amr_ws/src/amr_bringup/config/cyclonedds-local.xml"
