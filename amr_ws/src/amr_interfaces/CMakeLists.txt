cmake_minimum_required(VERSION 3.8)
project(amr_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/WheelVelocities.msg"
  "msg/WheelStates.msg"
  "msg/DriveStatus.msg"
  "msg/SafetyFieldStatus.msg"
  "msg/StationDetection.msg"
  "srv/RunMission.srv"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
