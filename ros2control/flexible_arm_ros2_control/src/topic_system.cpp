#include "flexible_arm_ros2_control/topic_system.hpp"

#include <cmath>
#include <utility>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace flexible_arm_ros2_control
{

TopicSystem::CallbackReturn TopicSystem::on_init(
  const hardware_interface::HardwareComponentInterfaceParams & params)
{
  if (hardware_interface::SystemInterface::on_init(params) !=
      CallbackReturn::SUCCESS)
  {
    return CallbackReturn::ERROR;
  }

  const auto & info = get_hardware_info();
  joint_names_.reserve(info.joints.size());
  for (const auto & joint : info.joints)
  {
    if (joint.command_interfaces.size() != 1 ||
        joint.command_interfaces[0].name != hardware_interface::HW_IF_POSITION ||
        joint.state_interfaces.size() != 1 ||
        joint.state_interfaces[0].name != hardware_interface::HW_IF_POSITION)
    {
      RCLCPP_ERROR(
        get_logger(), "Joint '%s' must expose one position command and state interface",
        joint.name.c_str());
      return CallbackReturn::ERROR;
    }
    joint_names_.push_back(joint.name);
  }

  const auto command_topic_it = info.hardware_parameters.find("command_topic");
  const auto state_topic_it = info.hardware_parameters.find("state_topic");
  const std::string command_topic =
    command_topic_it == info.hardware_parameters.end()
      ? "/flexible_arm/commands"
      : command_topic_it->second;
  const std::string state_topic =
    state_topic_it == info.hardware_parameters.end()
      ? "/flexible_arm/states"
      : state_topic_it->second;

  const auto threshold_it = info.hardware_parameters.find("command_threshold");
  if (threshold_it != info.hardware_parameters.end())
  {
    command_threshold_ = std::stod(threshold_it->second);
  }

  auto node = get_node();
  command_publisher_ =
    node->create_publisher<sensor_msgs::msg::JointState>(command_topic, 10);
  state_subscription_ = node->create_subscription<sensor_msgs::msg::JointState>(
    state_topic, rclcpp::SensorDataQoS(),
    std::bind(&TopicSystem::state_callback, this, std::placeholders::_1));
  last_commands_.assign(
    joint_names_.size(), std::numeric_limits<double>::quiet_NaN());

  return CallbackReturn::SUCCESS;
}

TopicSystem::CallbackReturn TopicSystem::on_activate(
  const rclcpp_lifecycle::State &)
{
  active_ = true;
  return CallbackReturn::SUCCESS;
}

TopicSystem::CallbackReturn TopicSystem::on_deactivate(
  const rclcpp_lifecycle::State &)
{
  active_ = false;
  return CallbackReturn::SUCCESS;
}

void TopicSystem::state_callback(
  const sensor_msgs::msg::JointState::SharedPtr message)
{
  std::lock_guard<std::mutex> lock(state_mutex_);
  const auto count = std::min(message->name.size(), message->position.size());
  for (std::size_t index = 0; index < count; ++index)
  {
    received_positions_[message->name[index]] = message->position[index];
  }
  state_ready_ = true;
  for (const auto & joint_name : joint_names_)
  {
    state_ready_ =
      state_ready_ && received_positions_.find(joint_name) != received_positions_.end();
  }
}

hardware_interface::return_type TopicSystem::read(
  const rclcpp::Time &, const rclcpp::Duration &)
{
  std::lock_guard<std::mutex> lock(state_mutex_);
  for (const auto & joint_name : joint_names_)
  {
    const auto state = received_positions_.find(joint_name);
    if (state != received_positions_.end())
    {
      set_state(joint_name + "/" + hardware_interface::HW_IF_POSITION, state->second);
    }
  }
  if (state_ready_ && !interfaces_initialized_)
  {
    for (std::size_t index = 0; index < joint_names_.size(); ++index)
    {
      const double position = received_positions_.at(joint_names_[index]);
      set_command(
        joint_names_[index] + "/" + hardware_interface::HW_IF_POSITION, position);
      last_commands_[index] = position;
    }
    interfaces_initialized_ = true;
  }
  return hardware_interface::return_type::OK;
}

hardware_interface::return_type TopicSystem::write(
  const rclcpp::Time & time, const rclcpp::Duration &)
{
  if (!active_ || !interfaces_initialized_)
  {
    return hardware_interface::return_type::OK;
  }

  sensor_msgs::msg::JointState message;
  message.header.stamp = time;
  message.name = joint_names_;
  message.position.reserve(joint_names_.size());

  bool changed = false;
  bool all_commands_finite = true;
  for (std::size_t index = 0; index < joint_names_.size(); ++index)
  {
    const double command = get_command<double>(
      joint_names_[index] + "/" + hardware_interface::HW_IF_POSITION);
    message.position.push_back(command);
    all_commands_finite = all_commands_finite && std::isfinite(command);
    if (!std::isfinite(last_commands_[index]) ||
        std::abs(command - last_commands_[index]) > command_threshold_)
    {
      changed = true;
    }
  }

  if (changed && all_commands_finite)
  {
    command_publisher_->publish(message);
    last_commands_ = message.position;
  }
  return hardware_interface::return_type::OK;
}

}  // namespace flexible_arm_ros2_control

PLUGINLIB_EXPORT_CLASS(
  flexible_arm_ros2_control::TopicSystem,
  hardware_interface::SystemInterface)
