#!/usr/bin/env python3
"""25-30mm 驱控一体电机 高层控制 API（协议 V20260921）。

设计目标：
    - UI 无关：可在脚本/服务/GUI 中使用；所有回调在工作线程触发
    - 线程安全：内置接收线程与全局锁
    - 输出端单位：位置/速度默认按减速比换算为输出端（电机端值同时提供）
    - 完整封装：连接/状态/使能/模式/MIT/轨迹/校准/改号/回零/测速比

快速上手：
    from motorapi import MotorApi, MotorConfig

    api = MotorApi(MotorConfig(gear_ratio=50))
    api.connect(channel=0)
    api.on_status(lambda st: print(st.position_out_deg, st.velocity_out_rpm))
    api.start_status_stream()
    api.run_speed(60)                  # 输出端 60 rpm
    api.stop_motor()
    api.disconnect()

轨迹运动（速度真正可控；固件位置模式忽略速度字段，已实测）：
    api.start_trajectory(target_out_deg=180, speed_out_rpm=30, accel_out_rpms=100)
    ...
    api.abort_trajectory()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .codec import (MODE_MIT, MODE_POSITION, MODE_SPEED, POS_CODE_MAX,
                    VEL_CODE_MAX, decode_calibration_result, decode_mit_frame,
                    decode_reply, decode_status, deg_to_pos_code,
                    encode_calibration_cmd, encode_control, encode_mit_frame,
                    encode_set_node_id, can_ids)
from .transport import (BUS_NORM, MODE_LOOPBACK, MODE_NORMAL, CanFDMsg,
                        HCanbus, calc_bit_timing)


class MotorApiError(RuntimeError):
    pass


@dataclass
class MotorConfig:
    channel: int = 0            # 0=CAN1, 1=CAN2
    node: int = 1               # 电机编号 N
    gear_ratio: float = 1.0     # 减速比 R（输出端:电机端，输出角=电机角/R）
    nom_baud: int = 1_000_000
    dat_baud: int = 4_000_000
    sample_point: float = 0.80
    kp: float = 0.008           # MIT 默认位置增益（手册建议值）
    kd: float = 1.0             # MIT 默认速度增益


@dataclass
class MotorStatus:
    """一次状态帧快照（同时含电机端与输出端数值）。"""
    timestamp: float = 0.0          # host monotonic
    position_deg: float = 0.0       # 电机端
    position_out_deg: float = 0.0   # 输出端
    position_code: int = 0
    position_out_turns: float = 0.0  # 输出端圈数
    velocity_rpm: float = 0.0       # 电机端
    velocity_out_rpm: float = 0.0   # 输出端
    current_a: float = 0.0
    bus_voltage_v: float = 0.0
    faults: List[str] = field(default_factory=list)
    motor_state: str = ""
    calib_state: str = ""
    mode: str = ""
    motor_type: str = ""
    fault_code: int = 0
    motor_state_raw: int = 0
    mode_raw: int = 0


@dataclass
class TrajectoryState:
    running: bool = False
    t: float = 0.0
    total: float = 0.0
    target_out_deg: float = 0.0
    p_des: float = 0.0
    v_des_rpm: float = 0.0
    done: bool = False
    aborted: bool = False


class MotorApi:
    """一台电机的高层控制接口（底层 USB-CAN-FD 通道由本类管理）。"""

    MOTOR_RPM_MAX = 3000.0   # 协议电机端速度上限

    def __init__(self, config: Optional[MotorConfig] = None, *, network=None):
        self.cfg = config or MotorConfig()
        self._network = network
        self.bus = network.bus if network is not None else HCanbus()
        self._receive_error = None
        self._last_calib = None
        self._connected = False
        self._rx_thread: Optional[threading.Thread] = None
        self._rx_stop = threading.Event()
        self._lock = threading.RLock()
        self._latest_status: Optional[MotorStatus] = None
        self._latest_reply: Optional[dict] = None
        self._on_status: Optional[Callable[[MotorStatus], None]] = None
        self._on_frame: Optional[Callable[[int, bytes, float, int], None]] = None
        self._on_reply: Optional[Callable[[dict], None]] = None
        self._on_calib: Optional[Callable[[dict], None]] = None
        self._on_tx: Optional[Callable[[int, bytes], None]] = None
        # MIT 连续发送
        self._stream_thread = None
        self._stream_stop = threading.Event()
        self._stream_params: Optional[dict] = None
        self._stream_hz = 100
        # 轨迹
        self._traj_thread = None
        self._traj_abort = threading.Event()
        self.traj_state = TrajectoryState()

    # ------------------------------------------------------------ 属性
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def node(self) -> int:
        return self.cfg.node

    @property
    def gear_ratio(self) -> float:
        return self.cfg.gear_ratio

    @property
    def output_position_limit_deg(self) -> float:
        """Symmetric protocol position limit, in output-end degrees."""
        return POS_CODE_MAX * 360.0 / 2097152.0 / self.cfg.gear_ratio

    def set_gear_ratio(self, r: float) -> None:
        if r <= 0:
            raise ValueError("gear_ratio must be > 0")
        self.cfg.gear_ratio = float(r)

    def set_node(self, n: int) -> None:
        """切换目标电机编号 N（1..60），ID 立即按新 N 计算。"""
        if not 1 <= n <= 60:
            raise ValueError("node must be 1..60")
        if self._network is not None:
            raise MotorApiError("shared-network node is fixed; create a new network for node changes")
        self.cfg.node = int(n)

    # ------------------------------------------------------------ 回调
    def on_status(self, cb: Optional[Callable[[MotorStatus], None]]) -> None:
        """状态帧回调（50Hz，工作线程调用）。"""
        self._on_status = cb

    def on_frame(self, cb: Optional[Callable[[int, bytes, float, int], None]]) -> None:
        """任意 CAN 帧回调 (can_id, data, timestamp_us)（工作线程调用）。"""
        self._on_frame = cb

    def on_reply(self, cb: Optional[Callable[[dict], None]]) -> None:
        """MIT 回复帧回调（一问一答）。"""
        self._on_reply = cb

    def on_calibration(self, cb: Optional[Callable[[dict], None]]) -> None:
        """校准结果回调（0x703+4N 或状态帧 data17 变化）。"""
        self._on_calib = cb

    def on_tx(self, cb: Optional[Callable[[int, bytes], None]]) -> None:
        """本 API 发出的每一帧回调 (can_id, data)（在调用线程触发）。"""
        self._on_tx = cb

    # ------------------------------------------------------------ 连接
    def scan(self) -> List[dict]:
        return self.bus.scan()

    def device_info(self) -> dict:
        """适配器设备信息（型号/序列号/版本）。"""
        return self.bus.dev_info()

    def dev_clock(self) -> int:
        """适配器 CAN 主频（Hz）。"""
        return self.bus.dev_clock()

    def connect(self, channel: Optional[int] = None) -> dict:
        """打开通道并按电机要求初始化（ISO CAN FD 1M/4M@80%）。返回实际时序。"""
        if self._connected:
            raise MotorApiError("already connected")
        if self._network is not None:
            if channel is not None and channel != self._network.channel:
                raise MotorApiError("shared network owns the channel")
            timing = self._network.connect()
            if not self._connected:
                self._latest_status = None
                self._connected = True
            return timing
        self._receive_error = None
        ch = self.cfg.channel if channel is None else channel
        self.bus.open(ch)
        cfg = self.bus.canfd_init(self.cfg.nom_baud, self.cfg.dat_baud,
                                  self.cfg.sample_point, MODE_NORMAL)
        self.cfg.channel = ch
        self._connected = True
        self._rx_stop.clear()
        self._rx_thread = threading.Thread(target=self._rx_loop,
                                           name="motorapi-rx", daemon=True)
        self._rx_thread.start()
        return cfg

    def disconnect(self) -> None:
        self.abort_trajectory()
        self.stop_mit_streaming()
        if self._network is not None:
            self._connected = False
            return
        self._rx_stop.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=2.0)
            self._rx_thread = None
        try:
            self.bus.close()
        except Exception:
            pass
        self._connected = False

    def _rx_loop(self) -> None:
        while not self._rx_stop.is_set():
            try:
                # RX and TX share the SDK lock: keep blocking reads short.
                frames = self.bus.recv_fd(max_items=200, timeout_ms=1)
            except Exception as exc:
                self._receive_error = str(exc)
                return
            for frame in frames:
                self._handle_frame(frame)
            # Yield outside the transport lock so pending TX can proceed.
            self._rx_stop.wait(0.001)

    def _handle_frame(self, f) -> None:
        """Shared dispatch used by both single-motor and network receivers."""
        base = 0x701 + 4 * self.cfg.node
        def callback(cb, *args):
            if cb:
                try:
                    cb(*args)
                except Exception:
                    pass
        callback(self._on_frame, f.id, f.data, f.timestamp_us, f.frame_type)
        if f.id == base + 1 and len(f.data) == 20:
            decoded = decode_status(f.data, n=self.cfg.node)
            if decoded["id_echo"] != decoded["expected_id_echo"]:
                return
            st = self._decode_status(f.data)
            with self._lock:
                self._latest_status = st
            callback(self._on_status, st)
            if st.calib_state != self._last_calib:
                self._last_calib = st.calib_state
                if st.calib_state in ("完成", "错误"):
                    callback(self._on_calib, {"state": st.calib_state,
                                             "ok": st.calib_state == "完成"})
        elif f.id == base and len(f.data) == 12:
            d = decode_reply(f.data, n=self.cfg.node)
            with self._lock:
                self._latest_reply = d
            callback(self._on_reply, d)
        elif f.id == base + 2 and len(f.data) == 8:
            callback(self._on_calib, decode_calibration_result(f.data))

    def _decode_status(self, data: bytes) -> MotorStatus:
        d = decode_status(data, n=self.cfg.node)
        r = self.cfg.gear_ratio
        return MotorStatus(
            timestamp=time.monotonic(),
            position_deg=d["position_deg"],
            position_out_deg=d["position_deg"] / r,
            position_code=d["position_code"],
            position_out_turns=d["position_code"] / 2097152.0 / r,
            velocity_rpm=d["velocity_rpm"],
            velocity_out_rpm=d["velocity_rpm"] / r,
            current_a=d["current_a"],
            bus_voltage_v=d["bus_voltage_v"],
            faults=list(d["faults"]),
            motor_state=d["motor_state"], calib_state=d["calib_state"],
            mode=d["mode"], motor_type=d["motor_type"],
            fault_code=int(d["fault_raw"], 16),
            motor_state_raw=d["motor_state_raw"], mode_raw=d["mode_raw"])

    # ------------------------------------------------------------ 状态
    def get_status(self, timeout: float = 0.3,
                   max_age: Optional[float] = None) -> Optional[MotorStatus]:
        """获取最近一帧状态（可选等待新鲜数据）。无数据返回 None。"""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if self._receive_error:
                    raise MotorApiError("CAN receive failed: " + self._receive_error)
                st = self._latest_status
            if st is not None:
                if max_age is None or time.monotonic() - st.timestamp <= max_age:
                    return st
            if time.monotonic() >= deadline:
                return st
            time.sleep(0.02)

    def wait_status(self, timeout: float = 2.0) -> MotorStatus:
        st = self.get_status(timeout=timeout, max_age=0.5)
        if st is None or time.monotonic() - st.timestamp > 0.5:
            raise MotorApiError("timeout waiting motor status (check power/bus)")
        return st

    # ------------------------------------------------------------ 基础控制
    def _ids(self) -> dict:
        return can_ids(self.cfg.node)

    def _tx(self, can_id: int, data: bytes, note: str = "") -> None:
        if not self._connected:
            raise MotorApiError("not connected")
        if self.bus.send_fd(can_id, data) != 1:
            raise MotorApiError("CAN transmit did not send one frame")
        if self._on_tx:
            try:
                self._on_tx(can_id, data)
            except Exception:
                pass

    def run_enable(self) -> None:
        """运行使能（MIT 控制前必须）。"""
        self._tx(self._ids()["motor_control"], encode_control(run=True))

    def stop_motor(self) -> None:
        """停止电机。"""
        self._tx(self._ids()["motor_control"], encode_control(run=False))

    def set_zero(self) -> None:
        """当前位置置零（电机停止并回 MIT 模式）。"""
        self._tx(self._ids()["motor_control"],
                 encode_control(run=False, set_zero=True, mode=MODE_MIT))

    def set_mode(self, mode: int) -> None:
        """切模式（自动先停机，手册要求）。mode: codec.MODE_MIT/SPEED/POSITION。"""
        self._tx(self._ids()["motor_control"],
                 encode_control(run=False, mode=mode))

    # ------------------------------------------------------------ MIT 控制
    def clamp_rpm(self, rpm_out: float):
        """输出端rpm → (电机端rpm, 是否被限幅)。输出端上限 = 3000/R。"""
        v = rpm_out * self.cfg.gear_ratio
        if v > self.MOTOR_RPM_MAX:
            return self.MOTOR_RPM_MAX, True
        if v < -self.MOTOR_RPM_MAX:
            return -self.MOTOR_RPM_MAX, True
        return v, False

    def output_rpm_limit(self) -> float:
        """输出端速度上限（rpm）= 3000 / R。"""
        return self.MOTOR_RPM_MAX / self.cfg.gear_ratio

    def _clamp_motor_rpm(self, rpm_out: float) -> float:
        return self.clamp_rpm(rpm_out)[0]

    def send_mit(self, position_out_deg: Optional[float] = None,
                 velocity_out_rpm: Optional[float] = None,
                 kp: Optional[float] = None, kd: Optional[float] = None,
                 ff_current_a: float = 0.0, auto_run: bool = False) -> bytes:
        """发送一帧 MIT 指令（位置/速度为输出端单位，内部换算+限幅）。

        None 表示沿用默认/零值；返回发送的原始帧。
        """
        pos_out = position_out_deg if position_out_deg is not None else 0.0
        vel_out = velocity_out_rpm if velocity_out_rpm is not None else 0.0
        data = encode_mit_frame(
            pos_code=deg_to_pos_code(pos_out * self.cfg.gear_ratio),
            vel_rpm=self._clamp_motor_rpm(vel_out),
            kp=self.cfg.kp if kp is None else kp,
            kd=self.cfg.kd if kd is None else kd,
            ff_current_a=ff_current_a)
        if auto_run:
            self.run_enable()
        self._tx(self._ids()["mit_send"], data)
        return data

    def start_mit_streaming(self, position_out_deg: float = 0.0,
                            velocity_out_rpm: float = 0.0,
                            kp: Optional[float] = None,
                            kd: Optional[float] = None,
                            ff_current_a: float = 0.0,
                            hz: float = 100.0,
                            auto_run: bool = True) -> None:
        """按固定参数连续发送 MIT 帧（供柔顺控制/自定义轨迹外环使用）。"""
        if self._stream_thread:
            raise MotorApiError("streaming already running")
        self._stream_params = dict(pos=position_out_deg, vel=velocity_out_rpm,
                                   kp=kp, kd=kd, ff=ff_current_a)
        self._stream_hz = hz
        self._stream_stop.clear()
        if auto_run:
            self.run_enable()
        self._stream_thread = threading.Thread(target=self._stream_loop,
                                               name="motorapi-mit-stream",
                                               daemon=True)
        self._stream_thread.start()

    def set_streaming_params(self, position_out_deg: Optional[float] = None,
                             velocity_out_rpm: Optional[float] = None,
                             kp: Optional[float] = None,
                             kd: Optional[float] = None,
                             ff_current_a: Optional[float] = None) -> None:
        """运行中实时更新连续发送参数（可实现自定义轨迹外环）。"""
        with self._lock:
            if not self._stream_params:
                raise MotorApiError("streaming not running")
            p = self._stream_params
            if position_out_deg is not None: p["pos"] = position_out_deg
            if velocity_out_rpm is not None: p["vel"] = velocity_out_rpm
            if kp is not None: p["kp"] = kp
            if kd is not None: p["kd"] = kd
            if ff_current_a is not None: p["ff"] = ff_current_a

    def stop_mit_streaming(self, stop_motor: bool = True) -> None:
        if self._stream_thread:
            self._stream_stop.set()
            self._stream_thread.join(timeout=2.0)
            self._stream_thread = None
        if stop_motor and self._connected:
            try:
                self.stop_motor()
            except Exception:
                pass

    def _stream_loop(self) -> None:
        period = 1.0 / max(10.0, min(500.0, self._stream_hz))
        deadline = time.monotonic()
        while not self._stream_stop.is_set():
            with self._lock:
                p = dict(self._stream_params) if self._stream_params else None
            if p:
                try:
                    self.send_mit(p["pos"], p["vel"], p["kp"], p["kd"], p["ff"])
                except Exception:
                    return
            deadline = self._next_send_deadline(deadline, period, time.monotonic())
            self._stream_stop.wait(max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _next_send_deadline(deadline: float, period: float, now: float) -> float:
        """Keep the original cadence, skipping missed slots instead of bursting."""
        deadline += period
        if deadline < now:
            deadline += (int((now - deadline) / period) + 1) * period
        return deadline

    # ------------------------------------------------------------ 速度/位置模式
    def run_speed(self, rpm_out: float) -> None:
        """纯速度模式一键启动：停机+切速度 → 使能 → 下发目标（输出端 rpm）。"""
        data = encode_mit_frame(vel_rpm=self._clamp_motor_rpm(rpm_out))
        self.set_mode(MODE_SPEED)
        time.sleep(0.02)
        self.run_enable()
        time.sleep(0.02)
        self._tx(self._ids()["mit_send"], data)

    def run_position(self, deg_out: float, rpm_out: float = 60.0) -> None:
        """纯位置模式一键启动（注意：固件忽略速度字段，控速请用轨迹模式）。"""
        data = encode_mit_frame(
            pos_code=deg_to_pos_code(deg_out * self.cfg.gear_ratio),
            vel_rpm=self._clamp_motor_rpm(rpm_out))
        self.set_mode(MODE_POSITION)
        time.sleep(0.02)
        self.run_enable()
        time.sleep(0.02)
        self._tx(self._ids()["mit_send"], data)

    # ------------------------------------------------------------ MIT 轨迹
    @staticmethod
    def _plan_traj(p0: float, p1: float, v: float, a: float) -> dict:
        d = p1 - p0
        if abs(d) > v * v / a:
            ta = v / a
            tc = abs(d) / v - v / a
            total = 2 * ta + tc
        else:
            v = (abs(d) * a) ** 0.5
            ta = v / a
            tc = 0.0
            total = 2 * ta
        return {"p0": p0, "p1": p1, "v": v, "a": a, "ta": ta, "tc": tc, "total": total}

    @staticmethod
    def _traj_setpoint(tr: dict, t: float):
        p0, p1, v, a, ta, tc = (tr["p0"], tr["p1"], tr["v"], tr["a"],
                                tr["ta"], tr["tc"])
        d = p1 - p0
        sgn = 1.0 if d >= 0 else -1.0
        if t <= ta:
            s = 0.5 * a * t * t
            vel = a * t
        elif t <= ta + tc:
            s = 0.5 * v * ta + v * (t - ta)
            vel = v
        else:
            t2 = min(t, tr["total"])
            s = abs(d) - 0.5 * a * (tr["total"] - t2) ** 2
            vel = a * (tr["total"] - t2)
        return p0 + sgn * s, sgn * vel

    def start_trajectory(self, target_out_deg: float, speed_out_rpm: float,
                         accel_out_rpms: float, kp: Optional[float] = None,
                         kd: Optional[float] = None, blocking: bool = False,
                         on_done: Optional[Callable[[TrajectoryState], None]] = None,
                         stop_on_done: bool = False) -> TrajectoryState:
        """MIT 梯形轨迹运动（速度真正可控）。100Hz 流式下发 p_des+v_des。

        blocking=True 时阻塞到轨迹完成/中止。
        """
        if self._traj_thread:
            raise MotorApiError("trajectory already running (abort first)")
        st = self.wait_status()
        r = self.cfg.gear_ratio
        p0 = st.position_deg
        p1 = target_out_deg * r
        motor_v = self._clamp_motor_rpm(abs(speed_out_rpm)) * 6.0   # deg/s
        motor_a = abs(accel_out_rpms) * r * 6.0
        if motor_v <= 0 or motor_a <= 0:
            raise MotorApiError("speed/accel must be > 0")
        plan = self._plan_traj(p0, p1, motor_v, motor_a)
        self._traj_abort.clear()
        self.traj_state = TrajectoryState(total=plan["total"],
                                          target_out_deg=target_out_deg)
        kp_use = self.cfg.kp if kp is None else kp
        kd_use = self.cfg.kd if kd is None else kd

        def worker():
            self.set_mode(MODE_MIT)
            time.sleep(0.03)
            self.run_enable()
            time.sleep(0.03)
            t0 = time.monotonic()
            deadline = t0
            while not self._traj_abort.is_set():
                t = time.monotonic() - t0
                if t >= plan["total"]:
                    p_des, v_des = plan["p1"], 0.0
                else:
                    p_des, v_des = self._traj_setpoint(plan, t)
                try:
                    data = encode_mit_frame(
                        pos_code=deg_to_pos_code(p_des),
                        vel_rpm=v_des / 6.0, kp=kp_use, kd=kd_use)
                    self._tx(self._ids()["mit_send"], data)
                except Exception:
                    self.traj_state.aborted = True
                    break
                ts = self.traj_state
                ts.running, ts.t, ts.p_des, ts.v_des_rpm = True, t, p_des, v_des / 6.0
                if t >= plan["total"]:
                    ts.running, ts.done = False, True
                    break
                deadline = self._next_send_deadline(deadline, 0.01, time.monotonic())
                self._traj_abort.wait(max(0.0, deadline - time.monotonic()))
            else:
                self.traj_state.aborted = True
            self.traj_state.running = False
            if stop_on_done or self.traj_state.aborted:
                try:
                    self.stop_motor()
                except Exception:
                    pass
            if on_done:
                on_done(self.traj_state)

        self._traj_thread = threading.Thread(target=worker,
                                             name="motorapi-traj", daemon=True)
        self._traj_thread.start()
        if blocking:
            self._traj_thread.join()
        return self.traj_state

    def abort_trajectory(self, stop_motor: bool = True) -> None:
        self._traj_abort.set()
        if self._traj_thread:
            self._traj_thread.join(timeout=2.0)
            self._traj_thread = None
        if stop_motor and self._connected:
            try:
                self.stop_motor()
            except Exception:
                pass

    # ------------------------------------------------------------ 工具
    def home(self, speed_out_rpm: float = 60.0, blocking: bool = True,
             timeout: float = 60.0) -> bool:
        """回零（位置模式回到电机端 0 码值 = 置零点/上电位置）。"""
        data = encode_mit_frame(
            pos_code=0, vel_rpm=self._clamp_motor_rpm(speed_out_rpm))
        self.set_mode(MODE_POSITION)
        time.sleep(0.03)
        self.run_enable()
        time.sleep(0.03)
        self._tx(self._ids()["mit_send"], data)
        if not blocking:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.get_status()
            if st and abs(st.position_code) < deg_to_pos_code(0.5):
                self.stop_motor()
                return True
            time.sleep(0.05)
        self.stop_motor()
        return False

    def calibrate(self, blocking: bool = True, timeout: float = 20.0) -> Optional[bool]:
        """编码器零点校准（0005→0006）。⚠ 电机旋转约10秒，禁止断电。

        blocking: 等待并返回 True/False；非阻塞返回 None（用 on_calibration 回调取结果）。
        """
        result = {"done": threading.Event(), "ok": False}

        def cb(d):
            if d.get("done") or d.get("ok") or d.get("state") == "完成":
                result["ok"] = d.get("done", d.get("ok", True))
                result["done"].set()

        old = self._on_calib
        self._on_calib = cb
        self.set_mode(MODE_MIT)
        time.sleep(0.03)
        self._tx(self._ids()["calibration_cmd"], encode_calibration_cmd())
        if not blocking:
            return None
        ok = result["done"].wait(timeout)
        self._on_calib = old
        return ok and result["ok"]

    def set_node_id(self, new_n: int) -> tuple:
        """写电机编号（0x4FE 广播）。⚠ 必须单台在线；断电重启生效。
        返回 (can_id, data)。"""
        if self._network is not None:
            raise MotorApiError("node ID broadcast is not allowed on a shared network")
        can_id, data = encode_set_node_id(new_n)
        self._tx(can_id, data)
        return can_id, data

    def measure_gear_ratio_electric(self, candidate: int,
                                    speed_out_rpm: float = 1000.0) -> float:
        """减速比电动校验运动：置零后走电机端 candidate×360°。

        调用后请人工观察输出轴是否恰好整 1 圈；是→R=candidate。
        本方法只负责运动，返回运动前电机端位置（便于上层判断）。
        """
        self.set_zero()
        time.sleep(0.05)
        data = encode_mit_frame(
            pos_code=deg_to_pos_code(candidate * 360.0),
            vel_rpm=self._clamp_motor_rpm(speed_out_rpm))
        self.set_mode(MODE_POSITION)
        time.sleep(0.03)
        self.run_enable()
        time.sleep(0.03)
        self._tx(self._ids()["mit_send"], data)
        return candidate * 360.0

    def send_raw(self, can_id: int, data: bytes) -> None:
        """发送任意 CAN FD 帧（调试）。"""
        self._tx(can_id, bytes(data))

    def close(self) -> None:
        self.disconnect()

    def __enter__(self) -> "MotorApi":
        return self

    def __exit__(self, *exc):
        self.disconnect()
