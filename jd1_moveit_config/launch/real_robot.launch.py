from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launches import (
    generate_move_group_launch,
    generate_rsp_launch,
    generate_static_virtual_joint_tfs_launch,
)


def generate_launch_description():
    package_path = Path(__file__).resolve().parents[1]
    moveit_config = (
        MoveItConfigsBuilder("jd1", package_name="jd1_moveit_config")
        .robot_description(
            file_path="config/jd1.urdf.xacro",
            mappings={"use_fake_hardware": "false"},
        )
        .trajectory_execution(
            file_path="config/moveit_controllers.yaml"
        )
        .planning_pipelines(
            default_planning_pipeline="ompl",
            pipelines=["ompl"],
        )
        .to_moveit_configs()
    )

    description = moveit_config.robot_description
    port = LaunchConfiguration("port")
    config_file = LaunchConfiguration("config_file")
    launch_description = LaunchDescription(
        [
            DeclareLaunchArgument("port", default_value="/dev/ttyUSB0"),
            DeclareLaunchArgument("use_rviz", default_value="true"),
            DeclareLaunchArgument(
                "config_file",
                default_value=str(Path.cwd() / "arm_config.json"),
            ),
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[
                    description,
                    str(package_path / "config/ros2_controllers.yaml"),
                ],
                output="screen",
            ),
            Node(
                package="flexible_arm_ros2_control",
                executable="flexible_arm_bridge",
                parameters=[
                    {
                        "port": port,
                        "config_file": config_file,
                        "state_limit_tolerance_deg": 1.0,
                        "ros_joint_names": [
                            "Joint_1",
                            "Joint_2",
                            "Joint_3",
                        ],
                        "sdk_joint_names": [
                            "base",
                            "shoulder",
                            "elbow",
                        ],
                    }
                ],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["joint_state_broadcaster"],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["jd1_controller"],
                output="screen",
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                arguments=[
                    "-d",
                    str(package_path / "config/moveit.rviz"),
                ],
                parameters=[
                    moveit_config.planning_pipelines,
                    moveit_config.robot_description_kinematics,
                    moveit_config.joint_limits,
                ],
                condition=IfCondition(LaunchConfiguration("use_rviz")),
                output="log",
            ),
        ]
    )

    for generated_launch in (
        generate_static_virtual_joint_tfs_launch(moveit_config),
        generate_rsp_launch(moveit_config),
        generate_move_group_launch(moveit_config),
    ):
        for action in generated_launch.entities:
            launch_description.add_action(action)

    return launch_description
