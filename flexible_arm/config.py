"""JSON configuration helpers."""

import json
from pathlib import Path

from .models import JointConfig


def load_joint_config(path: str | Path) -> list[JointConfig]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joints = data["joints"] if isinstance(data, dict) else data
    return [JointConfig(**item) for item in joints]


def save_joint_config(path: str | Path, joints: list[JointConfig]) -> None:
    payload = {"joints": [joint.__dict__ for joint in joints]}
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
