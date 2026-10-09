#!/usr/bin/env python3
"""motorapi 使用示例合集（供同事参考）。

用法：
    python examples/api_examples.py 1     # 示例1：连接+状态监控
    python examples/api_examples.py 2     # 示例2：速度模式
    python examples/api_examples.py 3     # 示例3：MIT 轨迹运动（速度可控）
    python examples/api_examples.py 4     # 示例4：自定义轨迹外环（流式参数实时更新）
    python examples/api_examples.py 5     # 示例5：回零/校准/改号
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motorapi import MotorApi, MotorConfig

R = 50.0  # 减速比：先用 GUI 工具页测出，或问厂商


def ex1_status():
    """连接并实时打印状态 5 秒（含电压/故障/模式）。"""
    api = MotorApi(MotorConfig(channel=0, node=1, gear_ratio=R))
    api.connect()
    api.on_status(lambda st: print(
        f"输出 {st.position_out_deg:8.2f}°  {st.velocity_out_rpm:7.1f}rpm  "
        f"{st.current_a:6.2f}A  {st.bus_voltage_v:5.1f}V  "
        f"{st.motor_state}/{st.mode}/{st.motor_type}  "
        f"故障:{st.faults or '无'}"))
    api.on_frame(lambda cid, data, ts: None)   # 需要原始帧时挂这里
    time.sleep(5)
    api.disconnect()


def ex2_speed():
    """速度模式：输出端 30rpm 转 3 秒后停止。"""
    api = MotorApi(MotorConfig(channel=0, gear_ratio=R))
    api.connect()
    api.run_speed(30)          # 一键：切模式→使能→下发（输出端单位）
    time.sleep(3)
    api.stop_motor()
    api.disconnect()


def ex3_trajectory():
    """MIT 轨迹运动：转到输出端 180°，速度 30rpm、加速度 100rpm/s（真正可控）。"""
    api = MotorApi(MotorConfig(channel=0, gear_ratio=R))
    api.connect()
    state = api.start_trajectory(
        target_out_deg=180.0, speed_out_rpm=30.0, accel_out_rpms=100.0,
        blocking=True)
    print("完成" if state.done else "中止", f"理论耗时≈{state.total:.1f}s")
    api.disconnect()


def ex4_custom_stream():
    """自定义轨迹外环：正弦摆动 5 秒（流式参数实时更新）。"""
    import math
    api = MotorApi(MotorConfig(channel=0, gear_ratio=R))
    api.connect()
    api.start_mit_streaming(position_out_deg=0, velocity_out_rpm=0,
                            kp=0.008, kd=1.0, hz=100)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5.0:
        t = time.monotonic() - t0
        w = 2 * math.pi * 0.5                      # 0.5Hz
        pos = 30.0 * math.sin(w * t)               # ±30°
        vel = 30.0 * w * math.cos(w * t) / 6.0     # 对应 rpm（deg/s→rpm）
        api.set_streaming_params(position_out_deg=pos, velocity_out_rpm=vel)
        time.sleep(0.005)
    api.stop_mit_streaming()
    api.disconnect()


def ex5_tools():
    """工具类操作：回零 / 校准 / 改号（危险）。"""
    api = MotorApi(MotorConfig(channel=0, gear_ratio=R))
    api.connect()
    ok = api.home(speed_out_rpm=60, blocking=True)      # 回零
    print("回零:", "OK" if ok else "超时")
    # ok = api.calibrate(blocking=True)                 # 校准（电机会转，慎用）
    # api.set_node_id(2)                                # 改号（单台在线+断电重启，慎用）
    api.disconnect()


if __name__ == "__main__":
    n = sys.argv[1] if len(sys.argv) > 1 else "1"
    {"1": ex1_status, "2": ex2_speed, "3": ex3_trajectory,
     "4": ex4_custom_stream, "5": ex5_tools}[n]()
