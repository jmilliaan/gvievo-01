cmake_minimum_required(VERSION 3.8)
project(amr_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/WheelVelocities.msg"
  "msg/WheelStates.msg"
  "msg/DriveStatus.msg"
  "msg/SafetyFieldStatus.msg"
  "msg/StationDetection.msg"
  "msg/MappingState.msg"
  "msg/LocalizationState.msg"
  "msg/MotionPermit.msg"
  "msg/RunState.msg"
  "msg/PanelState.msg"
  "srv/RunMission.srv"
  "srv/StartSurvey.srv"
  "srv/SaveMap.srv"
  "srv/SetPose2D.srv"
  "srv/AddObstacle.srv"
  DEPENDENCIES std_msgs geometry_msgs builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
