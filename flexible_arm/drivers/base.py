"""Driver contract. Drivers operate in physical servo angles."""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping

from ..models import ServoState


class ServoDriver(ABC):
    @property
    @abstractmethod
    def connected(self) -> bool:
        ...

    @abstractmethod
    def connect(self, port: str, baudrate: int = 115200) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def ping(self, servo_id: int) -> bool:
        ...

    @abstractmethod
    def read_state(self, servo_id: int) -> ServoState:
        ...

    def read_states(self, servo_ids: Iterable[int]) -> dict[int, ServoState]:
        return {servo_id: self.read_state(servo_id) for servo_id in servo_ids}

    @abstractmethod
    def move(
        self,
        servo_id: int,
        angle_deg: float,
        *,
        duration: float | None = None,
        velocity: float | None = None,
    ) -> None:
        ...

    @abstractmethod
    def move_sync(
        self,
        targets: Mapping[int, float],
        *,
        duration: float,
        acceleration_ms: int = 100,
        deceleration_ms: int = 100,
        power_mw: int = 10000,
    ) -> None:
        ...

    @abstractmethod
    def damping(self, servo_id: int, power_mw: int) -> None:
        ...

    @abstractmethod
    def stop(self, servo_ids: Iterable[int]) -> None:
        ...
