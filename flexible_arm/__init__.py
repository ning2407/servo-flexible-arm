"""Python SDK for the custom FashionStar flexible arm."""

from .arm import FlexibleArm
from .drivers import FashionStarDriver, ServoDriver, VirtualServoDriver
from .exceptions import (
    ArmError,
    ConnectionError,
    DriverError,
    JointLimitError,
    JointNotFoundError,
    TrajectoryError,
)
from .models import ArmState, JointConfig, JointState, ServoState, TrajectoryPoint

__all__ = [
    "ArmError",
    "ArmState",
    "ConnectionError",
    "DriverError",
    "FashionStarDriver",
    "FlexibleArm",
    "JointConfig",
    "JointLimitError",
    "JointNotFoundError",
    "JointState",
    "ServoDriver",
    "ServoState",
    "TrajectoryError",
    "TrajectoryPoint",
    "VirtualServoDriver",
]
