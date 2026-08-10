"""Save the arm's current physical pose as its fixed logical zero pose."""

from pathlib import Path

from flexible_arm import FlexibleArm, JointConfig
from flexible_arm.control_tools import save_current_pose_as_zero


PORT = "/dev/ttyUSB0"
CONFIG_FILE = Path(__file__).resolve().parents[1] / "arm_config.json"
JOINTS = [
    JointConfig("base", 1, min_deg=0, max_deg=180),
    JointConfig(
        "shoulder",
        2,
        direction=-1,
        min_deg=0,
        max_deg=180,
    ),
    JointConfig("elbow", 3, min_deg=0, max_deg=180),
]


with FlexibleArm() as arm:
    arm.connect(PORT, 115200)
    joints = save_current_pose_as_zero(arm, JOINTS, CONFIG_FILE)

print(f"零点配置已保存到: {CONFIG_FILE}")
for joint in joints:
    print(f"{joint.name}: {joint.zero_offset_deg}°")
