"""motorapi —— 25-30mm 驱控一体电机 Python 控制库。

分层：
    transport  USB-CAN-FD 适配器跨平台驱动（HCanbus.dll / libcanbus.so）
    codec      电机 CAN-FD 协议帧编解码（手册 V20260921）
    motor      高层控制 API（MotorApi：连接/状态/MIT/轨迹/校准/改号）

典型用法见 examples/api_examples.py 或 docs/api.md。
"""

from .codec import (MODE_MIT, MODE_POSITION, MODE_SPEED, MOTOR_STATES,
                    MODE_NAMES, MOTOR_TYPES, FAULT_BITS, can_ids,
                    decode_mit_frame, decode_reply, decode_status,
                    decode_calibration_result, decode_control,
                    deg_to_pos_code, pos_code_to_deg, encode_mit_frame,
                    encode_control, encode_calibration_cmd,
                    encode_set_node_id, rpm_to_vel_code, vel_code_to_rpm)
from .transport import (HCanbus, FDFrame, calc_bit_timing,
                        MODE_NORMAL, MODE_LOOPBACK, MODE_SILENT,
                        FMT_CANFD, FMT_FDBRS, FMT_ECHO)
from .motor import (MotorApi, MotorApiError, MotorConfig, MotorStatus,
                    TrajectoryState)

__version__ = "1.0.0"

__all__ = [
    "MotorApi", "MotorApiError", "MotorConfig", "MotorStatus",
    "TrajectoryState", "HCanbus", "FDFrame", "calc_bit_timing",
    "MODE_NORMAL", "MODE_LOOPBACK", "MODE_SILENT",
    "FMT_CANFD", "FMT_FDBRS", "FMT_ECHO",
    "MODE_MIT", "MODE_SPEED", "MODE_POSITION", "MODE_NAMES",
    "MOTOR_STATES", "MOTOR_TYPES", "FAULT_BITS", "can_ids",
    "decode_mit_frame", "decode_reply", "decode_status",
    "decode_calibration_result", "decode_control",
    "deg_to_pos_code", "pos_code_to_deg", "encode_mit_frame",
    "encode_control", "encode_calibration_cmd", "encode_set_node_id",
    "rpm_to_vel_code", "vel_code_to_rpm", "__version__",
]
