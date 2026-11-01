import os

from ament_index_python.packages import get_package_share_directory
from crane_plus_description.robot_description_loader import RobotDescriptionLoader
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node, SetParameter


def generate_launch_description():
    environment = {
        "IGN_GAZEBO_SYSTEM_PLUGIN_PATH": os.environ["LD_LIBRARY_PATH"],
        "IGN_GAZEBO_RESOURCE_PATH": os.path.dirname(
            get_package_share_directory("crane_plus_description")
        ),
    }
    world_file = os.path.join(
        get_package_share_directory("jev_crane_data_generator"),
        "worlds",
        "table_camera.sdf",
    )

    gazebo = ExecuteProcess(
        cmd=["ign gazebo -r -s", world_file],
        output="screen",
        additional_env=environment,
        shell=True,
    )

    description_loader = RobotDescriptionLoader()
    description_loader.use_gazebo = "true"
    description_loader.use_ignition = "true"
    description_loader.gz_control_config_package = "crane_plus_control"
    description_loader.gz_control_config_file_path = (
        "config/crane_plus_controllers.yaml"
    )
    description = description_loader.load()

    spawn_entity = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-topic",
            "/robot_description",
            "-name",
            "crane_plus",
            "-z",
            "1.015",
            "-allow_renaming",
            "true",
        ],
    )

    move_group = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [
                get_package_share_directory("crane_plus_moveit_config"),
                "/launch/run_move_group.launch.py",
            ]
        ),
        launch_arguments={"loaded_description": description}.items(),
    )

    joint_state_spawner = ExecuteProcess(
        cmd=["ros2 run controller_manager spawner joint_state_broadcaster"],
        shell=True,
        output="screen",
    )
    arm_spawner = ExecuteProcess(
        cmd=["ros2 run controller_manager spawner crane_plus_arm_controller"],
        shell=True,
        output="screen",
    )
    gripper_spawner = ExecuteProcess(
        cmd=["ros2 run controller_manager spawner crane_plus_gripper_controller"],
        shell=True,
        output="screen",
    )
    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock",
            "/camera/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
        ],
        output="screen",
    )

    return LaunchDescription(
        [
            SetParameter(name="use_sim_time", value=True),
            gazebo,
            TimerAction(period=3.0, actions=[spawn_entity]),
            move_group,
            TimerAction(
                period=7.0,
                actions=[joint_state_spawner, arm_spawner, gripper_spawner],
            ),
            bridge,
        ]
    )
