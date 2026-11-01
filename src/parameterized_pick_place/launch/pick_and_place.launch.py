import os

import yaml
from ament_index_python.packages import get_package_share_directory
from crane_plus_description.robot_description_loader import RobotDescriptionLoader
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter
from launch_ros.parameter_descriptions import ParameterValue


def load_file(package_name, file_path):
    path = os.path.join(get_package_share_directory(package_name), file_path)
    with open(path, encoding="utf-8") as source:
        return source.read()


def load_yaml(package_name, file_path):
    path = os.path.join(get_package_share_directory(package_name), file_path)
    with open(path, encoding="utf-8") as source:
        return yaml.safe_load(source)


def generate_launch_description():
    description_loader = RobotDescriptionLoader()
    robot_description = {
        "robot_description": description_loader.load()
    }
    semantic = {
        "robot_description_semantic": load_file(
            "crane_plus_moveit_config", "config/crane_plus.srdf"
        )
    }
    kinematics = load_yaml(
        "crane_plus_moveit_config", "config/kinematics.yaml"
    )

    arguments = [
        DeclareLaunchArgument("episode_id", default_value="pick-place-000"),
        DeclareLaunchArgument("cube_x", default_value="0.0"),
        DeclareLaunchArgument("cube_y", default_value="-0.1"),
        DeclareLaunchArgument("place_x", default_value="0.15"),
        DeclareLaunchArgument("place_y", default_value="0.0"),
        DeclareLaunchArgument("velocity_scale", default_value="0.8"),
        DeclareLaunchArgument("acceleration_scale", default_value="0.8"),
        DeclareLaunchArgument("route_profile", default_value="home_safe"),
        DeclareLaunchArgument("optimization_goal", default_value="stability"),
        DeclareLaunchArgument("route_cue", default_value="orange"),
        DeclareLaunchArgument("recommended_strategy", default_value="home_transfer"),
        DeclareLaunchArgument("direct_path_clear", default_value="false"),
        DeclareLaunchArgument("use_jev", default_value="true"),
        DeclareLaunchArgument("jev_input_mode", default_value="text"),
    ]

    node = Node(
        package="parameterized_pick_place",
        executable="pick_and_place",
        output="screen",
        parameters=[
            robot_description,
            semantic,
            kinematics,
            {
                "episode_id": LaunchConfiguration("episode_id"),
                "cube_x": ParameterValue(
                    LaunchConfiguration("cube_x"), value_type=float
                ),
                "cube_y": ParameterValue(
                    LaunchConfiguration("cube_y"), value_type=float
                ),
                "place_x": ParameterValue(
                    LaunchConfiguration("place_x"), value_type=float
                ),
                "place_y": ParameterValue(
                    LaunchConfiguration("place_y"), value_type=float
                ),
                "velocity_scale": ParameterValue(
                    LaunchConfiguration("velocity_scale"), value_type=float
                ),
                "acceleration_scale": ParameterValue(
                    LaunchConfiguration("acceleration_scale"), value_type=float
                ),
                "route_profile": LaunchConfiguration("route_profile"),
                "optimization_goal": LaunchConfiguration("optimization_goal"),
                "route_cue": LaunchConfiguration("route_cue"),
                "recommended_strategy": LaunchConfiguration(
                    "recommended_strategy"
                ),
                "direct_path_clear": ParameterValue(
                    LaunchConfiguration("direct_path_clear"), value_type=bool
                ),
                "use_phase_selector": ParameterValue(
                    LaunchConfiguration("use_jev"), value_type=bool
                ),
            },
        ],
    )

    phase_selector = Node(
        package="jev_crane_data_generator",
        executable="phase_selector",
        output="screen",
        parameters=[
            {
                "use_jev": ParameterValue(
                    LaunchConfiguration("use_jev"), value_type=bool
                ),
                "input_mode": LaunchConfiguration("jev_input_mode"),
            }
        ],
    )

    stop_when_motion_finishes = RegisterEventHandler(
        OnProcessExit(
            target_action=node,
            on_exit=[
                EmitEvent(
                    event=Shutdown(
                        reason="pick-and-place motion process completed"
                    )
                )
            ],
        )
    )

    return LaunchDescription(
        arguments
        + [
            SetParameter(name="use_sim_time", value=True),
            phase_selector,
            node,
            stop_when_motion_finishes,
        ]
    )
