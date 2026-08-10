"""High-level, thread-safe flexible arm API."""

import threading
import time
from collections.abc import Iterable, Mapping, Sequence

from .drivers import FashionStarDriver, ServoDriver
from .exceptions import (
    ConnectionError,
    JointLimitError,
    JointNotFoundError,
    TrajectoryError,
)
from .models import ArmState, JointConfig, JointState, ServoState, TrajectoryPoint


class FlexibleArm:
    def __init__(
        self,
        joints: Iterable[JointConfig] = (),
        *,
        driver: ServoDriver | None = None,
    ):
        self.driver = driver or FashionStarDriver()
        self._joints_by_id: dict[int, JointConfig] = {}
        self._joints_by_name: dict[str, JointConfig] = {}
        self._lock = threading.RLock()
        self._trajectory_thread: threading.Thread | None = None
        self._trajectory_stop = threading.Event()
        self._trajectory_pause = threading.Event()
        self._trajectory_done = threading.Event()
        self._trajectory_error: Exception | None = None
        for joint in joints:
            self.configure_joint(joint)

    @property
    def connected(self) -> bool:
        return self.driver.connected

    @property
    def trajectory_running(self) -> bool:
        thread = self._trajectory_thread
        return bool(thread and thread.is_alive())

    @property
    def trajectory_paused(self) -> bool:
        return self.trajectory_running and self._trajectory_pause.is_set()

    def connect(self, port: str, baudrate: int = 115200) -> None:
        self.driver.connect(port, baudrate)

    def disconnect(self) -> None:
        if self.trajectory_running:
            self.stop()
        self.driver.close()

    close = disconnect

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.disconnect()

    def configure_joint(self, joint: JointConfig) -> None:
        previous = self._joints_by_id.get(joint.servo_id)
        if previous:
            self._joints_by_name.pop(previous.name, None)
        same_name = self._joints_by_name.get(joint.name)
        if same_name and same_name.servo_id != joint.servo_id:
            raise ValueError(f"duplicate joint name: {joint.name}")
        self._joints_by_id[joint.servo_id] = joint
        self._joints_by_name[joint.name] = joint

    def configure_discovered_joint(
        self,
        servo_id: int,
        *,
        zero_offset_deg: float = 0.0,
        direction: int = 1,
        min_deg: float = -175.0,
        max_deg: float = 175.0,
    ) -> JointConfig:
        joint = JointConfig(
            name=f"joint_{servo_id}",
            servo_id=servo_id,
            zero_offset_deg=zero_offset_deg,
            direction=direction,
            min_deg=min_deg,
            max_deg=max_deg,
        )
        self.configure_joint(joint)
        return joint

    def get_joint_config(self, joint: int | str) -> JointConfig:
        try:
            if isinstance(joint, int):
                return self._joints_by_id[joint]
            return self._joints_by_name[joint]
        except KeyError as exc:
            raise JointNotFoundError(f"joint is not configured: {joint}") from exc

    def scan(
        self,
        start_id: int = 0,
        end_id: int = 30,
        *,
        configure: bool = True,
    ) -> list[int]:
        self._require_connected()
        if start_id < 0 or end_id < start_id or end_id > 255:
            raise ValueError("servo ID range must satisfy 0 <= start <= end <= 255")
        found = []
        for servo_id in range(start_id, end_id + 1):
            try:
                if self.driver.ping(servo_id):
                    found.append(servo_id)
                    if configure and servo_id not in self._joints_by_id:
                        self.configure_discovered_joint(servo_id)
            except Exception:
                continue
        return found

    def ping(self, servo_id: int) -> bool:
        self._require_connected()
        return self.driver.ping(servo_id)

    def move_joint(
        self,
        joint: int | str,
        angle_deg: float,
        *,
        duration: float | None = None,
        velocity: float | None = None,
    ) -> None:
        config = self._validated_target(joint, angle_deg, velocity)
        with self._lock:
            self.driver.move(
                config.servo_id,
                config.to_servo_angle(angle_deg),
                duration=duration,
                velocity=velocity,
            )

    def move_joints(
        self,
        targets: Mapping[int | str, float] | Sequence[float],
        *,
        duration: float = 1.0,
        acceleration_ms: int = 100,
        deceleration_ms: int = 100,
        power_mw: int = 10000,
    ) -> None:
        self._require_connected()
        if duration <= 0:
            raise ValueError("duration must be positive")
        if isinstance(targets, Mapping):
            items = targets.items()
        else:
            configs = list(self._joints_by_id.values())
            if len(targets) != len(configs):
                raise ValueError("position count does not match configured joints")
            items = zip((joint.servo_id for joint in configs), targets)

        physical_targets = {}
        for joint_ref, angle in items:
            config = self._validated_target(joint_ref, angle)
            physical_targets[config.servo_id] = config.to_servo_angle(angle)
        with self._lock:
            self.driver.move_sync(
                physical_targets,
                duration=duration,
                acceleration_ms=acceleration_ms,
                deceleration_ms=deceleration_ms,
                power_mw=power_mw,
            )

    def read_servo_state(self, servo_id: int) -> ServoState:
        self._require_connected()
        return self.driver.read_state(servo_id)

    def read_servo_states(self, servo_ids: Iterable[int]) -> dict[int, ServoState]:
        self._require_connected()
        return self.driver.read_states(servo_ids)

    def get_state(self, joints: Iterable[int | str] | None = None) -> ArmState:
        self._require_connected()
        configs = (
            list(self._joints_by_id.values())
            if joints is None
            else [self.get_joint_config(joint) for joint in joints]
        )
        states = self.driver.read_states(config.servo_id for config in configs)
        joint_states = []
        for config in configs:
            state = states[config.servo_id]
            joint_states.append(
                JointState(
                    name=config.name,
                    servo_id=config.servo_id,
                    position_deg=(
                        config.to_joint_angle(state.angle_deg)
                        if state.angle_deg is not None
                        else None
                    ),
                    voltage_v=state.voltage_v,
                    current_a=state.current_a,
                    power_w=state.power_w,
                    temperature=state.temperature,
                    status=state.status,
                    turn=state.turn,
                    online=state.online,
                )
            )
        return ArmState(True, tuple(joint_states))

    def set_damping(self, joint: int | str, power_mw: int) -> None:
        if power_mw < 0:
            raise ValueError("damping power cannot be negative")
        config = self.get_joint_config(joint)
        self.driver.damping(config.servo_id, power_mw)

    def execute_trajectory(
        self,
        points: Iterable[TrajectoryPoint],
        *,
        loop: bool = False,
        blocking: bool = False,
    ) -> None:
        trajectory = tuple(points)
        if not trajectory:
            raise TrajectoryError("trajectory cannot be empty")
        if self.trajectory_running:
            raise TrajectoryError("a trajectory is already running")
        # Validate the entire trajectory before moving any hardware.
        for point in trajectory:
            for joint, angle in point.positions.items():
                self._validated_target(joint, angle)

        self._trajectory_stop.clear()
        self._trajectory_pause.clear()
        self._trajectory_done.clear()
        self._trajectory_error = None
        self._trajectory_thread = threading.Thread(
            target=self._trajectory_worker,
            args=(trajectory, loop),
            name="flexible-arm-trajectory",
            daemon=True,
        )
        self._trajectory_thread.start()
        if blocking:
            self.wait_trajectory()

    def _trajectory_worker(
        self, trajectory: tuple[TrajectoryPoint, ...], loop: bool
    ) -> None:
        try:
            while not self._trajectory_stop.is_set():
                for point in trajectory:
                    if not self._wait_while_paused():
                        return
                    self.move_joints(point.positions, duration=point.duration)
                    if not self._interruptible_wait(point.duration + point.wait_after):
                        return
                if not loop:
                    return
        except Exception as exc:
            self._trajectory_error = exc
            self._trajectory_stop.set()
        finally:
            self._trajectory_done.set()

    def pause_trajectory(self) -> None:
        if not self.trajectory_running:
            raise TrajectoryError("no trajectory is running")
        self._trajectory_pause.set()
        self.driver.stop(self._joints_by_id)

    def resume_trajectory(self) -> None:
        if not self.trajectory_running:
            raise TrajectoryError("no trajectory is running")
        self._trajectory_pause.clear()

    def wait_trajectory(self, timeout: float | None = None) -> bool:
        completed = self._trajectory_done.wait(timeout)
        if completed and self._trajectory_error:
            raise TrajectoryError("trajectory execution failed") from self._trajectory_error
        return completed

    def stop(self) -> None:
        self._trajectory_stop.set()
        self._trajectory_pause.clear()
        thread = self._trajectory_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if self.connected:
            self.driver.stop(self._joints_by_id)

    def _wait_while_paused(self) -> bool:
        while self._trajectory_pause.is_set():
            if self._trajectory_stop.wait(0.02):
                return False
        return not self._trajectory_stop.is_set()

    def _interruptible_wait(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._trajectory_stop.wait(min(0.02, deadline - time.monotonic())):
                return False
            if not self._wait_while_paused():
                return False
        return True

    def _validated_target(
        self,
        joint: int | str,
        angle: float,
        velocity: float | None = None,
    ) -> JointConfig:
        self._require_connected()
        config = self.get_joint_config(joint)
        if not config.min_deg <= angle <= config.max_deg:
            raise JointLimitError(
                f"{config.name}: {angle}° is outside "
                f"[{config.min_deg}, {config.max_deg}]"
            )
        if velocity is not None:
            if velocity <= 0:
                raise ValueError("velocity must be positive")
            if velocity > config.max_speed_dps:
                raise JointLimitError(
                    f"{config.name}: velocity {velocity}°/s exceeds "
                    f"{config.max_speed_dps}°/s"
                )
        return config

    def _require_connected(self) -> None:
        if not self.connected:
            raise ConnectionError("arm is not connected")
