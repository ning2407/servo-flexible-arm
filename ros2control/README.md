# Flexible Arm ros2_control（ROS 2 Jazzy）

这个目录包含一个 ROS 2 Jazzy `ros2_control` 接入包：

- `TopicSystem`：标准 `hardware_interface::SystemInterface` 插件
- `flexible_arm_bridge`：将 ROS 弧度命令转换为现有 Python SDK 的角度命令
- 三关节 URDF/Xacro
- `joint_state_broadcaster`
- `joint_trajectory_controller`
- 一键启动文件

## 依赖

```bash
sudo apt install \
  ros-jazzy-ros2-control \
  ros-jazzy-ros2-controllers \
  ros-jazzy-xacro \
  ros-jazzy-robot-state-publisher
```

确保当前 Python 环境可以导入项目 SDK：

```bash
python3 -m pip install -e .
```

## 构建

在仓库根目录执行：

```bash
source /opt/ros/jazzy/setup.bash
colcon build \
  --base-paths ros2control \
  --symlink-install
source install/setup.bash
```

## 启动

```bash
ros2 launch flexible_arm_ros2_control bringup.launch.py \
  port:=/dev/ttyUSB0 \
  config_file:=$(pwd)/arm_config.json
```

启动后可检查：

```bash
ros2 control list_controllers
ros2 control list_hardware_interfaces
```

发送一个三关节目标（ROS 使用弧度）：

```bash
ros2 action send_goal \
  /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [base, shoulder, elbow], points: [{positions: [0.2, 0.1, -0.1], time_from_start: {sec: 2}}]}}"
```

## 数据路径

```text
joint_trajectory_controller
        ↓ position（rad）
TopicSystem C++ hardware plugin
        ↓ /flexible_arm/commands
Python bridge
        ↓ FlexibleArm SDK（deg）
FashionStar serial bus
```

`arm_config.json` 仍是零偏、方向和角度限位的唯一配置来源。
