"""Public data models used by the flexible arm SDK."""

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class JointConfig:
    """Mapping and safety limits for one arm joint."""

    name: str
    servo_id: int
    zero_offset_deg: float = 0.0
    direction: int = 1
    min_deg: float = -175.0
    max_deg: float = 175.0
    max_speed_dps: float = 500.0

    def __post_init__(self) -> None:
        if self.direction not in (-1, 1):
            raise ValueError("joint direction must be either -1 or 1")
        if self.min_deg >= self.max_deg:
            raise ValueError("joint min_deg must be less than max_deg")
        if self.max_speed_dps <= 0:
            raise ValueError("joint max_speed_dps must be positive")

    def to_servo_angle(self, joint_angle_deg: float) -> float:
        return self.zero_offset_deg + self.direction * joint_angle_deg

    def to_joint_angle(self, servo_angle_deg: float) -> float:
        return self.direction * (servo_angle_deg - self.zero_offset_deg)


@dataclass(frozen=True)
class ServoState:
    servo_id: int
    angle_deg: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    power_w: float | None = None
    temperature: float | None = None
    status: int | None = None
    turn: int | None = None
    online: bool = True


@dataclass(frozen=True)
class JointState:
    name: str
    servo_id: int
    position_deg: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    power_w: float | None = None
    temperature: float | None = None
    status: int | None = None
    turn: int | None = None
    online: bool = True


@dataclass(frozen=True)
class ArmState:
    connected: bool
    joints: tuple[JointState, ...] = ()


@dataclass(frozen=True)
class TrajectoryPoint:
    """One synchronized waypoint expressed in logical joint angles."""

    positions: Mapping[int | str, float]
    duration: float = 1.0
    wait_after: float = 0.0

    def __post_init__(self) -> None:
        if not self.positions:
            raise ValueError("trajectory point positions cannot be empty")
        if self.duration <= 0:
            raise ValueError("trajectory duration must be positive")
        if self.wait_after < 0:
            raise ValueError("trajectory wait_after cannot be negative")
