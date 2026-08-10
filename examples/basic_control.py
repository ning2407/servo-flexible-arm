"""Minimal program for running the configured three-joint arm."""

from pathlib import Path

from flexible_arm import FlexibleArm
from flexible_arm.config import load_joint_config
from flexible_arm.control_tools import keyboard_control


PORT = "/dev/ttyUSB0"
CONFIG_FILE = Path(__file__).resolve().parents[1] / "arm_config.json"

with FlexibleArm(load_joint_config(CONFIG_FILE)) as arm:
    arm.connect(PORT, 115200)
    keyboard_control(arm)
