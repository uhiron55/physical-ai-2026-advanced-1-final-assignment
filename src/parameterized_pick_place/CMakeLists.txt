cmake_minimum_required(VERSION 3.8)
project(parameterized_pick_place)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

add_executable(pick_and_place src/pick_and_place.cpp)
ament_target_dependencies(
  pick_and_place
  geometry_msgs
  moveit_ros_planning_interface
  rclcpp
  std_msgs
  tf2_geometry_msgs
)

install(TARGETS pick_and_place DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

ament_package()
