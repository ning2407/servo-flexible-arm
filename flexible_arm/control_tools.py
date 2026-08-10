"""Optional command-line tools built on top of the core arm SDK."""

import sys
import termios
import time
import tty
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from .arm import FlexibleArm
from .config import save_joint_config
from .models import JointConfig


def save_current_pose_as_zero(
    arm: FlexibleArm,
    joint_templates: Sequence[JointConfig],
    path: str | Path,
) -> list[JointConfig]:
    """Read the current motor pose and save it as a fixed joint zero pose."""
    states = arm.read_servo_states(
        joint.servo_id for joint in joint_templates
    )
    joints = []
    for template in joint_templates:
        angle = states[template.servo_id].angle_deg
        if angle is None:
            raise RuntimeError(
                f"无法读取舵机 {template.servo_id} 的角度，不能保存零点"
            )
        joints.append(replace(template, zero_offset_deg=angle))
    save_joint_config(path, joints)
    return joints


def keyboard_control(
    arm: FlexibleArm,
    *,
    keymap: Mapping[str, tuple[str, float]] | None = None,
    return_order: Sequence[str] = ("elbow", "shoulder", "base"),
    move_duration: float = 0.15,
    return_duration: float = 1.0,
    acceleration_ms: int = 50,
    deceleration_ms: int = 50,
) -> None:
    """Control configured joints with single key presses in a Linux terminal."""
    keymap = keymap or {
        "q": ("base", 1.0),
        "a": ("base", -1.0),
        "w": ("shoulder", 1.0),
        "s": ("shoulder", -1.0),
        "e": ("elbow", 1.0),
        "d": ("elbow", -1.0),
    }
    positions = {
        joint.name: joint.position_deg
        for joint in arm.get_state().joints
        if joint.position_deg is not None
    }
    if not sys.stdin.isatty():
        raise RuntimeError("按键控制需要在交互式终端中运行")

    print(
        "\nQ/A：base 正/反向    W/S：shoulder 正/反向\n"
        "E/D：elbow 正/反向   R：依次归零   X：退出"
    )
    terminal_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            key = sys.stdin.read(1).lower()
            if key == "x":
                break
            if key == "r":
                for joint in return_order:
                    print(f"\r正在归零：{joint:<10}", end="", flush=True)
                    arm.move_joints(
                        {joint: 0.0},
                        duration=return_duration,
                        acceleration_ms=acceleration_ms,
                        deceleration_ms=deceleration_ms,
                    )
                    time.sleep(return_duration)
                    positions[joint] = 0.0
                print("\r三个关节已依次回到固定零点                  ")
                continue
            if key not in keymap:
                continue

            joint, delta = keymap[key]
            config = arm.get_joint_config(joint)
            target = positions[joint] + delta
            target = max(config.min_deg, min(config.max_deg, target))
            arm.move_joints(
                {joint: target},
                duration=move_duration,
                acceleration_ms=acceleration_ms,
                deceleration_ms=deceleration_ms,
            )
            positions[joint] = target
            print(
                "\r"
                + "  ".join(
                    f"{name}={angle:6.1f}°"
                    for name, angle in positions.items()
                ),
                end="",
                flush=True,
            )
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, terminal_settings)
        arm.stop()
        print("\n按键控制已退出")
