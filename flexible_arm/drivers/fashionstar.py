"""FashionStar UART implementation of :class:`ServoDriver`."""

from collections.abc import Iterable, Mapping

from ..exceptions import ConnectionError, DriverError
from ..models import ServoState
from .base import ServoDriver


class FashionStarDriver(ServoDriver):
    def __init__(self, *, debug: bool = False, serial_timeout: float = 0.1):
        self.debug = debug
        self.serial_timeout = serial_timeout
        self._uart = None
        self._manager = None

    @property
    def connected(self) -> bool:
        return bool(self._uart is not None and self._uart.is_open)

    def connect(self, port: str, baudrate: int = 115200) -> None:
        if self.connected:
            raise ConnectionError("driver is already connected")
        try:
            import serial
            import fashionstar_uart_sdk as uservo

            self._uart = serial.Serial(
                port=port,
                baudrate=baudrate,
                parity=serial.PARITY_NONE,
                stopbits=1,
                bytesize=8,
                timeout=self.serial_timeout,
            )
            self._manager = uservo.UartServoManager(
                self._uart, is_debug=self.debug
            )
        except Exception as exc:
            self.close()
            raise ConnectionError(f"failed to connect to {port}: {exc}") from exc

    def close(self) -> None:
        uart, self._uart, self._manager = self._uart, None, None
        if uart is not None:
            try:
                if uart.is_open:
                    uart.close()
            except Exception:
                pass

    def _require_manager(self):
        if not self.connected or self._manager is None:
            raise ConnectionError("servo driver is not connected")
        return self._manager

    def ping(self, servo_id: int) -> bool:
        try:
            return bool(self._require_manager().ping(servo_id))
        except ConnectionError:
            raise
        except Exception as exc:
            raise DriverError(f"failed to ping servo {servo_id}: {exc}") from exc

    def read_state(self, servo_id: int) -> ServoState:
        manager = self._require_manager()
        try:
            data = manager.query_servo_monitor(servo_id)
            return self._monitor_state(servo_id, data)
        except AttributeError:
            pass
        except Exception:
            # Older servo firmware may not support the monitor command.
            pass

        def query(name):
            try:
                return getattr(manager, name)(servo_id)
            except Exception:
                return None

        angle = query("query_servo_angle")
        if angle is None:
            raise DriverError(f"failed to read servo {servo_id}")
        return ServoState(
            servo_id=servo_id,
            angle_deg=angle,
            voltage_v=query("query_voltage"),
            current_a=query("query_current"),
            power_w=query("query_power"),
            temperature=query("query_temperature"),
            status=query("query_status"),
        )

    def read_states(self, servo_ids: Iterable[int]) -> dict[int, ServoState]:
        ids = list(servo_ids)
        manager = self._require_manager()
        if not ids:
            return {}
        try:
            result = manager.send_sync_servo_monitor(ids)
            if isinstance(result, dict):
                return {
                    servo_id: self._monitor_state(
                        servo_id, result.get(servo_id, result.get(str(servo_id), {}))
                    )
                    for servo_id in ids
                }
        except Exception:
            pass
        return super().read_states(ids)

    @staticmethod
    def _monitor_state(servo_id: int, data) -> ServoState:
        data = data or {}
        if not isinstance(data, dict):
            power = getattr(data, "power", None)
            return ServoState(
                servo_id=servo_id,
                angle_deg=getattr(
                    data, "angle_monitor", getattr(data, "angle", None)
                ),
                voltage_v=getattr(data, "voltage", None),
                current_a=getattr(data, "current", None),
                power_w=power / 1000.0 if power is not None else None,
                temperature=getattr(data, "temp", None),
                status=getattr(data, "status", None),
                turn=getattr(data, "turn", None),
            )
        return ServoState(
            servo_id=servo_id,
            angle_deg=data.get("angle"),
            voltage_v=(
                data.get("voltage") / 1000.0
                if data.get("voltage") is not None
                else None
            ),
            current_a=(
                data.get("current") / 1000.0
                if data.get("current") is not None
                else None
            ),
            power_w=(
                data.get("power") / 1000.0
                if data.get("power") is not None
                else None
            ),
            temperature=data.get("temp"),
            status=data.get("status"),
            turn=data.get("turn"),
        )

    def move(
        self,
        servo_id: int,
        angle_deg: float,
        *,
        duration: float | None = None,
        velocity: float | None = None,
    ) -> None:
        kwargs = {"is_mturn": True}
        if duration is not None:
            kwargs["interval"] = max(1, int(duration * 1000))
        if velocity is not None:
            kwargs["velocity"] = velocity
        try:
            self._require_manager().set_servo_angle(servo_id, angle_deg, **kwargs)
        except Exception as exc:
            raise DriverError(f"failed to move servo {servo_id}: {exc}") from exc

    def move_sync(
        self,
        targets: Mapping[int, float],
        *,
        duration: float,
        acceleration_ms: int = 100,
        deceleration_ms: int = 100,
        power_mw: int = 10000,
    ) -> None:
        if not targets:
            return
        interval_ms = max(1, int(duration * 1000))
        try:
            manager = self._require_manager()
            # Some FashionStar servo firmware can report state correctly but
            # silently ignores the newer CODE_SYNC_COMMAND (25) broadcast.
            # The regular multi-turn position command is supported across
            # firmware versions. Sending three commands sequentially adds only
            # a few milliseconds of skew and keeps the requested duration the
            # same for every joint.
            for servo_id, angle in targets.items():
                manager.set_servo_angle(
                    servo_id=servo_id,
                    angle=angle,
                    is_mturn=True,
                    interval=interval_ms,
                    t_acc=acceleration_ms,
                    t_dec=deceleration_ms,
                    power=power_mw,
                )
        except Exception as exc:
            raise DriverError(f"failed to move servos synchronously: {exc}") from exc

    def damping(self, servo_id: int, power_mw: int) -> None:
        try:
            self._require_manager().set_damping(servo_id, power_mw)
        except Exception as exc:
            raise DriverError(f"failed to damp servo {servo_id}: {exc}") from exc

    def stop(self, servo_ids: Iterable[int]) -> None:
        manager = self._require_manager()
        errors = []
        for servo_id in servo_ids:
            try:
                if hasattr(manager, "stop_on_control_mode"):
                    manager.stop_on_control_mode(servo_id, method=0x11, power=0)
                else:
                    angle = manager.query_servo_angle(servo_id)
                    manager.set_servo_angle(servo_id, angle, is_mturn=True)
            except Exception as exc:
                errors.append(f"{servo_id}: {exc}")
        if errors:
            raise DriverError("failed to stop servos: " + "; ".join(errors))
