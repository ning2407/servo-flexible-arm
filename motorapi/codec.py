#!/usr/bin/env python3
"""25-30mm 驱控一体电机 CAN-FD 协议参考编解码器（手册 V20260204）。

用法：
    python tools/motor_codec.py          # 运行自检，验证手册全部示例帧
    python tools/motor_codec.py 010001800080200364000080   # 解码一帧 hex

关键规则：
    - 多字节字段均为小端（低字节在低 data 序号）
    - 有符号字段为偏移二进制：raw - 0x8000 / raw - 0x80000000
"""

from __future__ import annotations

import io
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 常量
POS_COUNTS_PER_TURN = 1 << 21      # 2097152, 21-bit encoder
POS_CODE_MAX = 0x07CFFFFFF         # ≈ ±1000 turns
VEL_CODE_MAX = 30000               # ±3000 rpm
CURRENT_SCALE_A = 11.0 / 4096.0    # A per LSB

MODE_MIT = 0x00
MODE_SPEED = 0x01
MODE_POSITION = 0x02

MOTOR_STATES = {
    0: "初始化", 1: "电流校准", 2: "编码器零点校准",
    3: "停止", 4: "运行", 5: "错误",
}
CALIB_STATES = {0: "空闲", 1: "校准中", 2: "完成", 3: "错误"}
MODE_NAMES = {MODE_MIT: "MIT模式", MODE_SPEED: "速度模式", MODE_POSITION: "位置模式"}
MOTOR_TYPES = {0x01: "30mm", 0x02: "25mm", 0x03: "20mm", 0x04: "16mm"}
FAULT_BITS = {
    0: "驱动芯片故障",
    1: "过压故障(>18V)",
    2: "欠压故障(<8V)",
    3: "过流故障(10s内功率过大)",
    4: "编码器故障",
}


def can_ids(n: int = 1) -> dict:
    """返回节点 n（1..60）的全部 CAN ID。"""
    if not 1 <= n <= 60:
        raise ValueError("N must be 1..60")
    return {
        "mit_send": 0x501 + 4 * n,
        "motor_control": 0x502 + 4 * n,
        "calibration_cmd": 0x503 + 4 * n,
        "mit_reply": 0x701 + 4 * n,
        "motor_status": 0x702 + 4 * n,
        "calibration_result": 0x703 + 4 * n,
    }


# ---------------------------------------------------------------- 低层编码
def _enc_s32(code: int) -> bytes:
    return ((code + 0x80000000) & 0xFFFFFFFF).to_bytes(4, "little")


def _dec_s32(data: bytes) -> int:
    return int.from_bytes(data, "little") - 0x80000000


def _enc_s16(code: int) -> bytes:
    return ((code + 0x8000) & 0xFFFF).to_bytes(2, "little")


def _dec_s16(data: bytes) -> int:
    return int.from_bytes(data, "little") - 0x8000


def _enc_u16(u: int) -> bytes:
    return (u & 0xFFFF).to_bytes(2, "little")


def _dec_u16(data: bytes) -> int:
    return int.from_bytes(data, "little")


# ---------------------------------------------------------------- 单位换算
def deg_to_pos_code(deg: float) -> int:
    return int(round(deg / 360.0 * POS_COUNTS_PER_TURN))


def pos_code_to_deg(code: int) -> float:
    return code / POS_COUNTS_PER_TURN * 360.0


def rpm_to_vel_code(rpm: float) -> int:
    return int(round(rpm * 10))


def vel_code_to_rpm(code: int) -> float:
    return code / 10.0


def amps_to_cur_code(amps: float) -> int:
    return int(round(amps / CURRENT_SCALE_A))


def cur_code_to_amps(code: int) -> float:
    return code * CURRENT_SCALE_A


def volts_to_code(volts: float) -> int:
    return int(round(volts * 10))


def code_to_volts(code: int) -> float:
    return code / 10.0


# ---------------------------------------------------------------- 帧编解码
def encode_mit_frame(
    pos_code: int = 0,
    vel_rpm: float = 0.0,
    kp: float = 0.0,
    kd: float = 0.0,
    ff_current_a: float = 0.0,
) -> bytes:
    """组 MIT 发送帧（0x501+4N，12 字节）。

    kp/kd 直接给协议值（MIT 建议从 0.008 / 1.0 起调）；
    如需按物理量(A/rad, A/(rad/s))设置，先用 kact 换算：
        kp = kact * 0.001115 ;  kd = kact * 85.636
    """
    if not -POS_CODE_MAX <= pos_code <= POS_CODE_MAX:
        raise ValueError(f"pos_code out of range ±0x{POS_CODE_MAX:X}")
    vel_code = rpm_to_vel_code(vel_rpm)
    if not -VEL_CODE_MAX <= vel_code <= VEL_CODE_MAX:
        raise ValueError("velocity out of range ±3000 rpm")
    kp_code = int(round(kp / 0.00001))
    kd_code = int(round(kd / 0.01))
    if not 0 <= kp_code <= 0xFFFF or not 0 <= kd_code <= 0xFFFF:
        raise ValueError("kp must be 0..0.65535, kd must be 0..655.35")
    cur_code = amps_to_cur_code(ff_current_a)
    if not -0x8000 <= cur_code <= 0x7FFF:
        raise ValueError("feedforward current code out of s16 range")
    frame = (
        _enc_s32(pos_code)
        + _enc_s16(vel_code)
        + _enc_u16(kp_code)
        + _enc_u16(kd_code)
        + _enc_s16(cur_code)
    )
    assert len(frame) == 12
    return frame


def decode_mit_frame(data: bytes) -> dict:
    """解 MIT 发送帧（调试/回环校验用）。"""
    if len(data) != 12:
        raise ValueError("mit frame must be 12 bytes")
    return {
        "position_code": _dec_s32(data[0:4]),
        "position_deg": pos_code_to_deg(_dec_s32(data[0:4])),
        "velocity_code": _dec_s16(data[4:6]),
        "velocity_rpm": vel_code_to_rpm(_dec_s16(data[4:6])),
        "kp": _dec_u16(data[6:8]) * 0.00001,
        "kd": _dec_u16(data[8:10]) * 0.01,
        "feedforward_current_code": _dec_s16(data[10:12]),
        "feedforward_current_a": cur_code_to_amps(_dec_s16(data[10:12])),
    }


def decode_reply(data: bytes, n: int = 1) -> dict:
    """解 MIT 回复帧（0x701+4N，12 字节）。"""
    if len(data) != 12:
        raise ValueError("reply frame must be 12 bytes")
    return {
        "id_echo": _dec_u16(data[0:2]),
        "expected_id_echo": 0x0500 | (0x01 + 4 * n) & 0xFF,  # data0=0x01+4N, data1=0x05
        "position_code": _dec_s32(data[2:6]),
        "position_deg": pos_code_to_deg(_dec_s32(data[2:6])),
        "velocity_code": _dec_s16(data[6:8]),
        "velocity_rpm": vel_code_to_rpm(_dec_s16(data[6:8])),
        "current_code": _dec_s16(data[8:10]),
        "current_a": cur_code_to_amps(_dec_s16(data[8:10])),
        "tail": data[10:12].hex(),
    }


def decode_status(data: bytes, n: int = 1) -> dict:
    """解电机状态帧（0x702+4N，20 字节，20ms 周期）。"""
    if len(data) != 20:
        raise ValueError("status frame must be 20 bytes")
    fault = int.from_bytes(data[12:16], "little")
    return {
        "id_echo": _dec_u16(data[0:2]),
        "expected_id_echo": 0x0500 | (0x01 + 4 * n) & 0xFF,  # data0=0x01+4N, data1=0x05
        "position_code": _dec_s32(data[2:6]),
        "position_deg": pos_code_to_deg(_dec_s32(data[2:6])),
        "velocity_code": _dec_s16(data[6:8]),
        "velocity_rpm": vel_code_to_rpm(_dec_s16(data[6:8])),
        "current_code": _dec_s16(data[8:10]),
        "current_a": cur_code_to_amps(_dec_s16(data[8:10])),
        "bus_voltage_code": _dec_u16(data[10:12]),  # u16，无符号；手册笔误(data1)按data10修正
        "bus_voltage_v": code_to_volts(_dec_u16(data[10:12])),
        "fault_raw": f"0x{fault:08X}",
        "faults": [name for bit, name in FAULT_BITS.items() if fault & (1 << bit)],
        "motor_state_raw": data[16],
        "motor_state": MOTOR_STATES.get(data[16], f"未知({data[16]})"),
        "calib_state_raw": data[17],
        "calib_state": CALIB_STATES.get(data[17], f"未知({data[17]})"),
        "mode_raw": data[18],
        "mode": MODE_NAMES.get(data[18], f"未知(0x{data[18]:02X})"),
        "motor_type_raw": data[19],
        "motor_type": MOTOR_TYPES.get(data[19], f"未知(0x{data[19]:02X})"),
    }


def encode_control(run: bool = False, set_zero: bool = False, mode: int = MODE_MIT) -> bytes:
    """组电机控制帧（0x502+4N，8 字节）。切模式时 run 必须为 False。"""
    if mode not in MODE_NAMES:
        raise ValueError("mode must be MODE_MIT / MODE_SPEED / MODE_POSITION")
    return bytes([0x01 if run else 0x00, 0x01 if set_zero else 0x00, mode, 0, 0, 0, 0, 0])


def encode_calibration_cmd() -> bytes:
    """组编码器零点校准指令帧（0x503+4N，8 字节，V20260921 手册 3.7.1）。

    固定密钥 55 AA CC 33 77 11 FF 00；发送后电机自校准约 10 秒，
    期间禁止断电；结果通过状态帧 data17 或 0x703+4N 校准结果帧查看。
    """
    return bytes([0x55, 0xAA, 0xCC, 0x33, 0x77, 0x11, 0xFF, 0x00])


def decode_calibration_result(data: bytes) -> dict:
    """解码校准结果帧（0x703+4N，8 字节，V20260921 手册 3.7.2）。"""
    if len(data) != 8:
        raise ValueError("calibration result frame must be 8 bytes")
    results = {0x02: "校准完成", 0x03: "校准错误"}
    return {
        "result_raw": data[0],
        "result": results.get(data[0], f"未知({data[0]:#04x})"),
        "done": data[0] == 0x02,
        "error": data[0] == 0x03,
    }


def encode_set_node_id(n: int) -> tuple:
    """组设置控制器编号指令（V20260921 手册 3.8）。

    ID 为全局广播 0x4FE（不受旧 N 影响），8 字节 [N,20,26,05,20,10,58,00]。
    ⚠ 必须单台电机在线时操作，否则总线上所有电机会被写入同一编号；
    下发后需断电重启生效。手册 3.8 写范围 1~64，与 3.1 的 1~60 冲突，
    实际组网请按 1~60 使用。
    返回 (can_id, data)。
    """
    if not 1 <= n <= 64:
        raise ValueError("N must be 1..64 (protocol networking limit is 60)")
    return 0x4FE, bytes([n, 0x20, 0x26, 0x05, 0x20, 0x10, 0x58, 0x00])


def decode_control(data: bytes) -> dict:
    if len(data) != 8:
        raise ValueError("control frame must be 8 bytes")
    return {
        "run": data[0] == 0x01,
        "set_zero": data[1] == 0x01,
        "mode_raw": data[2],
        "mode": MODE_NAMES.get(data[2], f"未知(0x{data[2]:02X})"),
    }


# ---------------------------------------------------------------- 自检
def _self_test() -> None:
    ok = "\u2713"

    # 手册第2页示例：位置码值65537, 速度0, Kp=0.008, Kd=1, 电流0
    f = encode_mit_frame(pos_code=65537, vel_rpm=0, kp=0.008, kd=1.0, ff_current_a=0.0)
    assert f.hex() == "010001800080200364000080", f.hex()
    d = decode_mit_frame(f)
    assert d["position_code"] == 65537 and d["velocity_rpm"] == 0
    assert abs(d["kp"] - 0.008) < 1e-9 and abs(d["kd"] - 1.0) < 1e-9
    assert d["feedforward_current_a"] == 0.0
    print(f"{ok} 第2页示例 010001800080200364000080：位置=65537, 速度=0, Kp=0.008, Kd=1, 前馈=0A")

    # 手册第3页示例：电流模式，前馈电流码值100
    f2 = encode_mit_frame(pos_code=65537, vel_rpm=0, kp=0.0, kd=0.0, ff_current_a=100 * CURRENT_SCALE_A)
    assert f2.hex() == "010001800080000000006480", f2.hex()
    d2 = decode_mit_frame(f2)
    assert d2["feedforward_current_code"] == 100
    assert abs(d2["feedforward_current_a"] - 0.2685546875) < 1e-9
    print(f"{ok} 第3页示例 010001800080000000006480：前馈电流码值=100 → {d2['feedforward_current_a']:.4f}A")

    # 手册第6页指令0001示例
    f3 = bytes.fromhex("010000900080200364000080")
    d3 = decode_mit_frame(f3)
    assert d3["position_code"] == 0x10000001 == 268435457
    assert abs(d3["position_deg"] / 360.0 - 128.0) < 1e-6   # ≈128圈
    assert abs(d3["kp"] - 0.008) < 1e-9 and abs(d3["kd"] - 1.0) < 1e-9
    print(f"{ok} 第6页示例 010000900080200364000080：位置码值=0x10000001 (≈{d3['position_deg']/360:.1f}圈), Kp=0.008, Kd=1")

    # 指令0009推算：速度2000rpm，位置0x20000001
    f4 = encode_mit_frame(pos_code=0x20000001, vel_rpm=2000.0, kp=0.0, kd=0.0, ff_current_a=0.0)
    assert f4[:6].hex() == "010000a020ce", f4.hex()
    d4 = decode_mit_frame(f4)
    assert d4["position_code"] == 0x20000001 and d4["velocity_rpm"] == 2000.0
    print(f"{ok} 指令0009推算 位置=0x20000001 速度=2000rpm → 前缀 {f4[:6].hex()}")

    # 负数往返：-90° / -123.4rpm / -1A
    f5 = encode_mit_frame(pos_code=deg_to_pos_code(-90.0), vel_rpm=-123.4, kp=0.008, kd=1.0, ff_current_a=-1.0)
    d5 = decode_mit_frame(f5)
    assert abs(d5["position_deg"] + 90.0) < 1e-4
    assert abs(d5["velocity_rpm"] + 123.4) < 1e-9
    assert abs(d5["feedforward_current_a"] + 1.0) < 1e-3
    print(f"{ok} 负值往返：-90° / -123.4rpm / -1A → {f5.hex()}")

    # 控制帧
    assert encode_control(run=True).hex() == "0100000000000000"
    assert encode_control(run=False, mode=MODE_SPEED).hex() == "0000010000000000"
    assert encode_control(run=False, mode=MODE_POSITION).hex() == "0000020000000000"
    assert encode_control(run=False, set_zero=True).hex() == "0001000000000000"
    print(f"{ok} 控制帧：运行/停止+速度模式/停止+位置模式/置零")

    # V20260921 新增：校准指令与编号设置
    assert encode_calibration_cmd().hex() == "55aacc337711ff00"
    assert decode_calibration_result(bytes([0x02]) + bytes(7))["done"] is True
    assert decode_calibration_result(bytes([0x03]) + bytes(7))["error"] is True
    cid, cdata = encode_set_node_id(2)
    assert cid == 0x4FE and cdata.hex() == "0220260520105800"
    print(f"{ok} V20260921 新增指令：校准密钥 55AACC337711FF00 / 编号设置 0x4FE: {cdata.hex()}")

    # 状态帧解码（构造一个样例：12V，无故障，运行，MIT，25mm）
    st = (
        _enc_u16(0x505)                       # id echo
        + _enc_s32(deg_to_pos_code(11.25))    # 位置
        + _enc_s16(rpm_to_vel_code(-12.3))    # 速度
        + _enc_s16(amps_to_cur_code(0.5))     # 电流
        + _enc_u16(volts_to_code(12.0))       # 母线电压(u16)
        + (0).to_bytes(4, "little")           # 故障
        + bytes([4, 0, MODE_MIT, 0x02])       # 状态/校准/模式/机型
    )
    ds = decode_status(st)
    assert len(st) == 20 and ds["faults"] == []
    assert ds["motor_state"] == "运行" and ds["mode"] == "MIT模式" and ds["motor_type"] == "25mm"
    assert abs(ds["bus_voltage_v"] - 12.0) < 1e-9
    print(f"{ok} 状态帧构造+解码：20字节, 12.0V, 无故障, 运行, MIT, 25mm")

    # ID 表
    ids = can_ids(1)
    assert ids["mit_send"] == 0x505 and ids["motor_control"] == 0x506
    assert ids["mit_reply"] == 0x705 and ids["motor_status"] == 0x706
    assert can_ids(60)["mit_send"] == 0x5F1
    print(f"{ok} ID 计算：N=1 → 0x505/0x506/0x507/0x705/0x706/0x707；N=60 → 0x5F1...")

    print("\n全部自检通过：手册 3 个示例帧、0009 推算、负值往返、控制帧、状态帧、ID 表。")


def main() -> None:
    if len(sys.argv) > 1:
        for hexstr in sys.argv[1:]:
            data = bytes.fromhex(hexstr)
            if len(data) == 12:
                for k, v in decode_mit_frame(data).items():
                    print(f"  {k}: {v}")
            elif len(data) == 20:
                for k, v in decode_status(data).items():
                    print(f"  {k}: {v}")
            elif len(data) == 8:
                for k, v in decode_control(data).items():
                    print(f"  {k}: {v}")
            else:
                print(f"  {hexstr}: 未知长度 {len(data)}")
    else:
        _self_test()


if __name__ == "__main__":
    main()
