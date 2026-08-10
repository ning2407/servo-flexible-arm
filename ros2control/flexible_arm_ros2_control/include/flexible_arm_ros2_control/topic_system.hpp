#ifndef FLEXIBLE_ARM_ROS2_CONTROL__TOPIC_SYSTEM_HPP_
#define FLEXIBLE_ARM_ROS2_CONTROL__TOPIC_SYSTEM_HPP_

#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "hardware_interface/system_interface.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"

namespace flexible_arm_ros2_control
{

class TopicSystem : public hardware_interface::SystemInterface
{
public:
  using CallbackReturn =
    rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn;

  CallbackReturn on_init(
    const hardware_interface::HardwareComponentInterfaceParams & params) override;

  CallbackReturn on_activate(
    const rclcpp_lifecycle::State & previous_state) override;

  CallbackReturn on_deactivate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::return_type read(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

  hardware_interface::return_type write(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

private:
  void state_callback(const sensor_msgs::msg::JointState::SharedPtr message);

  std::vector<std::string> joint_names_;
  std::unordered_map<std::string, double> received_positions_;
  std::vector<double> last_commands_;
  std::mutex state_mutex_;
  bool active_{false};
  bool state_ready_{false};
  bool interfaces_initialized_{false};
  double command_threshold_{1.0e-5};

  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr command_publisher_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr state_subscription_;
};

}  // namespace flexible_arm_ros2_control

#endif  // FLEXIBLE_ARM_ROS2_CONTROL__TOPIC_SYSTEM_HPP_
