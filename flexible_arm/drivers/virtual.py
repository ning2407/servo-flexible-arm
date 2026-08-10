"""Deterministic in-memory driver for development and tests."""

from collections.abc import Iterable, Mapping
from threading import RLock

from ..exceptions import ConnectionError, DriverError
from ..models import ServoState
from .base import ServoDriver


class VirtualServoDriver(ServoDriver):
    def __init__(self, servo_ids: Iterable[int] = range(1, 5)):
        self._states = {
            servo_id: ServoState(
                servo_id=servo_id,
                angle_deg=0.0,
                voltage_v=7.4,
                current_a=0.0,
                power_w=0.0,
                temperature=25.0,
                status=0,
            )
            for servo_id in servo_ids
        }
        self._connected = False
        self._lock = RLock()
        self.stopped = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, port: str = "virtual", baudrate: int = 115200) -> None:
        if self._connected:
            raise ConnectionError("virtual driver is already connected")
        self._connected = True
        self.stopped = False

    def close(self) -> None:
        self._connected = False

    def _require_connected(self) -> None:
        if not self.connected:
            raise ConnectionError("virtual driver is not connected")

    def ping(self, servo_id: int) -> bool:
        self._require_connected()
        return servo_id in self._states

    def read_state(self, servo_id: int) -> ServoState:
        self._require_connected()
        try:
            return self._states[servo_id]
        except KeyError as exc:
            raise DriverError(f"virtual servo {servo_id} does not exist") from exc

    def move(
        self,
        servo_id: int,
        angle_deg: float,
        *,
        duration: float | None = None,
        velocity: float | None = None,
    ) -> None:
        self._set_angle(servo_id, angle_deg)

    def move_sync(
        self,
        targets: Mapping[int, float],
        *,
        duration: float,
        acceleration_ms: int = 100,
        deceleration_ms: int = 100,
        power_mw: int = 10000,
    ) -> None:
        with self._lock:
            for servo_id in targets:
                if servo_id not in self._states:
                    raise DriverError(f"virtual servo {servo_id} does not exist")
            for servo_id, angle in targets.items():
                self._set_angle(servo_id, angle)

    def _set_angle(self, servo_id: int, angle: float) -> None:
        self._require_connected()
        with self._lock:
            old = self.read_state(servo_id)
            self._states[servo_id] = ServoState(
                **{**old.__dict__, "angle_deg": float(angle)}
            )
            self.stopped = False

    def damping(self, servo_id: int, power_mw: int) -> None:
        self.read_state(servo_id)

    def stop(self, servo_ids: Iterable[int]) -> None:
        self._require_connected()
        for servo_id in servo_ids:
            self.read_state(servo_id)
        self.stopped = True
