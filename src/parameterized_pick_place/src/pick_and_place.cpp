// Derived from AI-Robot-Book-Humble/crane_plus pick_and_place.cpp (Apache-2.0).

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "geometry_msgs/msg/pose.hpp"
#include "moveit/move_group_interface/move_group_interface.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/float64_multi_array.hpp"
#include "std_msgs/msg/string.hpp"
#include "tf2_geometry_msgs/tf2_geometry_msgs.hpp"

using MoveGroupInterface = moveit::planning_interface::MoveGroupInterface;
using namespace std::chrono_literals;

double to_radians(const double degrees)
{
  return degrees * M_PI / 180.0;
}

bool succeeded(const moveit::core::MoveItErrorCode & result)
{
  return result == moveit::core::MoveItErrorCode::SUCCESS;
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::NodeOptions options;
  options.automatically_declare_parameters_from_overrides(true);
  auto arm_node = rclcpp::Node::make_shared("parameterized_pick_place_arm", options);
  auto gripper_node = rclcpp::Node::make_shared(
    "parameterized_pick_place_gripper", options);

  auto get_double = [&](const std::string & name, const double default_value) {
      if (!arm_node->has_parameter(name)) {
        arm_node->declare_parameter(name, default_value);
      }
      return arm_node->get_parameter(name).as_double();
    };
  auto get_string = [&](const std::string & name, const std::string & default_value) {
      if (!arm_node->has_parameter(name)) {
        arm_node->declare_parameter(name, default_value);
      }
      return arm_node->get_parameter(name).as_string();
    };
  auto get_bool = [&](const std::string & name, const bool default_value) {
      if (!arm_node->has_parameter(name)) {
        arm_node->declare_parameter(name, default_value);
      }
      return arm_node->get_parameter(name).as_bool();
    };

  const double cube_x = get_double("cube_x", 0.0);
  const double cube_y = get_double("cube_y", -0.1);
  const double place_x = get_double("place_x", 0.15);
  const double place_y = get_double("place_y", 0.0);
  const double velocity_scale = get_double("velocity_scale", 0.8);
  const double acceleration_scale = get_double("acceleration_scale", 0.8);
  const std::string episode_id = get_string("episode_id", "pick-place-000");
  const std::string route_profile = get_string("route_profile", "home_safe");
  const std::string optimization_goal = get_string("optimization_goal", "stability");
  const std::string route_cue = get_string("route_cue", "orange");
  const std::string recommended_strategy = get_string(
    "recommended_strategy", "home_transfer");
  const bool direct_path_clear = get_bool("direct_path_clear", false);
  const bool use_phase_selector = get_bool("use_phase_selector", true);

  auto context_pub = arm_node->create_publisher<std_msgs::msg::Float64MultiArray>(
    "/pick_place/task_context", 10);
  auto phase_pub = arm_node->create_publisher<std_msgs::msg::String>(
    "/pick_place/phase", 10);
  auto phase_request_pub = arm_node->create_publisher<std_msgs::msg::String>(
    "/jev_crane/phase_request", 10);
  auto decision_pub = arm_node->create_publisher<std_msgs::msg::String>(
    "/jev_crane/decision", 10);

  std::mutex selection_mutex;
  std::condition_variable selection_condition;
  std::string selected_request_id;
  std::string selected_strategy;
  auto selected_sub = arm_node->create_subscription<std_msgs::msg::String>(
    "/jev_crane/selected_phase", 10,
    [&](const std_msgs::msg::String::SharedPtr message) {
      const auto separator = message->data.find('|');
      if (separator == std::string::npos) {
        return;
      }
      {
        std::lock_guard<std::mutex> lock(selection_mutex);
        selected_request_id = message->data.substr(0, separator);
        selected_strategy = message->data.substr(separator + 1);
      }
      selection_condition.notify_all();
    });

  auto publish_context = [&]() {
      std_msgs::msg::Float64MultiArray message;
      message.data = {cube_x, cube_y, place_x, place_y};
      context_pub->publish(message);
    };
  auto context_timer = arm_node->create_wall_timer(50ms, publish_context);

  auto publish_phase = [&](const std::string & phase) {
      std_msgs::msg::String message;
      message.data = "{\"episode_id\":\"" + episode_id +
        "\",\"phase\":\"" + phase + "\"}";
      phase_pub->publish(message);
      RCLCPP_INFO(arm_node->get_logger(), "phase=%s", phase.c_str());
    };

  int strategy_request_index = 0;
  auto choose_strategy = [&](const std::string & current_phase,
      const std::string & recommended,
      const std::vector<std::string> & candidates) {
      if (!use_phase_selector) {
        return recommended;
      }

      const std::string request_id = episode_id + "-strategy-" +
        std::to_string(++strategy_request_index);
      {
        std::lock_guard<std::mutex> lock(selection_mutex);
        selected_request_id.clear();
        selected_strategy.clear();
      }

      std::ostringstream json;
      json << "{\"request_id\":\"" << request_id
           << "\",\"episode_id\":\"" << episode_id
           << "\",\"current_phase\":\"" << current_phase
           << "\",\"recommended\":\"" << recommended
           << "\",\"candidates\":[";
      for (std::size_t index = 0; index < candidates.size(); ++index) {
        if (index > 0) {
          json << ',';
        }
        json << "\"" << candidates[index] << "\"";
      }
      json << "],\"task_context\":{\"cube_x\":" << cube_x
           << ",\"cube_y\":" << cube_y
           << ",\"place_x\":" << place_x
           << ",\"place_y\":" << place_y
           << ",\"route_profile\":\"" << route_profile
           << "\",\"direct_path_clear\":"
           << (direct_path_clear ? "true" : "false")
           << ",\"optimization_goal\":\"" << optimization_goal
           << "\",\"route_cue\":\"" << route_cue << "\"}}";

      std_msgs::msg::String request;
      request.data = json.str();
      phase_request_pub->publish(request);

      std::unique_lock<std::mutex> lock(selection_mutex);
      const bool received = selection_condition.wait_for(
        lock, 15s, [&]() {return selected_request_id == request_id;});
      if (!received) {
        std_msgs::msg::String fallback;
        fallback.data = "{\"request_id\":\"" + request_id +
          "\",\"choice\":\"" + recommended +
          "\",\"fallback_reason\":\"selector_timeout\"}";
        decision_pub->publish(fallback);
        RCLCPP_WARN(
          arm_node->get_logger(),
          "Phase selector timed out; using %s", recommended.c_str());
        return recommended;
      }

      const std::string choice = selected_strategy;
      if (std::find(candidates.begin(), candidates.end(), choice) == candidates.end()) {
        RCLCPP_WARN(
          arm_node->get_logger(),
          "Phase selector returned invalid choice %s; using %s",
          choice.c_str(), recommended.c_str());
        return recommended;
      }
      RCLCPP_INFO(
        arm_node->get_logger(), "Jev selected transfer strategy: %s", choice.c_str());
      return choice;
    };

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(arm_node);
  executor.add_node(gripper_node);
  std::thread executor_thread([&executor]() {executor.spin();});

  MoveGroupInterface arm(arm_node, "arm");
  arm.setMaxVelocityScalingFactor(velocity_scale);
  arm.setMaxAccelerationScalingFactor(acceleration_scale);
  arm.setPlanningTime(10.0);
  arm.setNumPlanningAttempts(10);

  MoveGroupInterface gripper(gripper_node, "gripper");
  gripper.setMaxVelocityScalingFactor(velocity_scale);
  gripper.setMaxAccelerationScalingFactor(acceleration_scale);
  gripper.setPlanningTime(5.0);
  gripper.setNumPlanningAttempts(5);
  auto gripper_values = gripper.getCurrentJointValues();
  if (gripper_values.empty()) {
    RCLCPP_WARN(
      gripper_node->get_logger(),
      "Current gripper state was unavailable; using 0.0 as the initial target");
    gripper_values = {0.0};
  }

  auto fail = [&](const std::string & phase) {
      publish_phase("failed:" + phase);
      executor.cancel();
      if (executor_thread.joinable()) {
        executor_thread.join();
      }
      rclcpp::shutdown();
      return 1;
    };

  auto move_named = [&](const std::string & name) {
      arm.setNamedTarget(name);
      return succeeded(arm.move());
    };
  auto move_pose = [&](const geometry_msgs::msg::Pose & pose) {
      arm.setPoseTarget(pose);
      return succeeded(arm.move());
    };
  auto move_gripper = [&](const double value) {
      gripper_values[0] = value;
      gripper.setJointValueTarget(gripper_values);
      return succeeded(gripper.move());
    };

  const double gripper_default = 0.0;
  const double gripper_open = to_radians(-30.0);
  const double gripper_close = to_radians(10.0);

  publish_context();
  publish_phase("started");

  publish_phase("vertical");
  if (!move_named("vertical")) return fail("vertical");
  if (!move_gripper(gripper_default)) return fail("gripper_default");

  publish_phase("home_before_pick");
  if (!move_named("home")) return fail("home_before_pick");
  if (!move_gripper(gripper_open)) return fail("gripper_open");

  geometry_msgs::msg::Pose target_pose;
  tf2::Quaternion orientation;
  target_pose.position.x = cube_x;
  target_pose.position.y = cube_y + 0.01;
  target_pose.position.z = 0.17;
  orientation.setRPY(to_radians(0), to_radians(90), to_radians(-90));
  target_pose.orientation = tf2::toMsg(orientation);

  publish_phase("approach");
  if (!move_pose(target_pose)) return fail("approach");

  orientation.setRPY(to_radians(0), to_radians(180), to_radians(-90));
  target_pose.orientation = tf2::toMsg(orientation);
  if (!move_pose(target_pose)) return fail("orient_for_grasp");

  publish_phase("descend");
  target_pose.position.z = 0.14;
  if (!move_pose(target_pose)) return fail("descend");

  publish_phase("grasp");
  if (!move_gripper(gripper_close)) return fail("grasp");

  publish_phase("lift");
  target_pose.position.z = 0.17;
  if (!move_pose(target_pose)) return fail("lift");

  const std::string transfer_strategy = choose_strategy(
    "lift", recommended_strategy, {"home_transfer", "direct_transfer"});
  publish_phase("transfer:" + transfer_strategy);
  if (transfer_strategy == "home_transfer" && !move_named("home")) {
    return fail("home_with_object");
  }

  target_pose.position.x = place_x;
  target_pose.position.y = place_y;
  target_pose.position.z = 0.06;
  orientation.setRPY(to_radians(0), to_radians(90), to_radians(0));
  target_pose.orientation = tf2::toMsg(orientation);
  if (!move_pose(target_pose)) {
    if (transfer_strategy != "direct_transfer") {
      return fail("place_pose");
    }
    publish_phase("transfer_fallback:home_transfer");
    if (!move_named("home") || !move_pose(target_pose)) {
      return fail("place_pose_after_direct_fallback");
    }
  }

  publish_phase("release");
  if (!move_gripper(gripper_open)) return fail("release");

  publish_phase("return_home");
  if (!move_named("home")) return fail("home_after_place");
  if (!move_named("vertical")) return fail("vertical_after_place");
  if (!move_gripper(gripper_default)) return fail("gripper_reset");

  publish_phase("completed");
  std::this_thread::sleep_for(250ms);
  executor.cancel();
  if (executor_thread.joinable()) {
    executor_thread.join();
  }
  rclcpp::shutdown();
  return 0;
}
