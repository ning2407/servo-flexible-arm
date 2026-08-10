from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(
        get_package_share_directory("flexible_arm_ros2_control")
    )
    default_config = str(Path.cwd() / "arm_config.json")
    config_file = LaunchConfiguration("config_file")
    port = LaunchConfiguration("port")
    robot_description = {
        "robot_description": Command(
            ["xacro ", str(package_share / "urdf/flexible_arm.urdf.xacro")]
        )
    }

    return LaunchDescription(
        [
            DeclareLaunchArgument("port", default_value="/dev/ttyUSB0"),
            DeclareLaunchArgument("config_file", default_value=default_config),
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                parameters=[robot_description],
            ),
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[
                    robot_description,
                    str(package_share / "config/controllers.yaml"),
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
                    }
                ],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "joint_state_broadcaster",
                    "--controller-manager",
                    "/controller_manager",
                ],
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=[
                    "arm_controller",
                    "--controller-manager",
                    "/controller_manager",
                ],
            ),
        ]
    )
