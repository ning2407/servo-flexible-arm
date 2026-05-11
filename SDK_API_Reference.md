# Fashion Star 总线伺服舵机 Python SDK — API 协议总览

**版本**: v1.2026.0214 | **安装**: `pip install fashionstar-uart-sdk`

---

## 初始化方式

```python
import time
import serial
import fashionstar_uart_sdk as uservo

uart = serial.Serial(port='COM7', baudrate=115200,
                     parity=serial.PARITY_NONE, stopbits=1,
                     bytesize=8, timeout=0)
uservo = UartServoManager(uart)
```

---

## 完整 API 清单（按功能分类）

| 序号 | API | 功能 | 关键参数 | 返回值 |
|------|-----|------|----------|--------|
| 4 | `ping(servo_id)` | 舵机通信检测 | servo_id | is_online (bool) |
| 5 | `set_damping(servo_id, power)` | 设置阻尼模式 | servo_id, power(mW) | 无 |
| 6 | `query_servo_angle(servo_id)` | 查询舵机角度 | servo_id | angle (单圈/多圈) |
| 7 | `set_servo_angle(servo_id, angle, is_mturn, interval, velocity, t_acc, t_dec, power, mean_dps)` | 设置舵机角度（含6种控制模式） | 见下方详述 | 无 |
| 7 | `wait(timeout)` | 等待舵机到达目标角度 | timeout(ms) | 无 |
| 8 | `reset_multi_turn_angle(servo_id)` | 清除多圈圈数（需失锁状态） | servo_id | 无 |
| 9 | `reset_user_data(servo_id)` | 重置用户数据表 | servo_id | 无 |
| 9 | `read_data(servo_id, address)` | 读取内存表数据 | servo_id, address | bytes 字节流 |
| 9 | `write_data(servo_id, address, content)` | 写入内存表数据 | servo_id, address, content(bytes) | 无 |
| 10 | `query_voltage(servo_id)` | 查询电压 | servo_id | voltage (V) |
| 10 | `query_current(servo_id)` | 查询电流 | servo_id | current (A) |
| 10 | `query_power(servo_id)` | 查询功率 | servo_id | power (W) |
| 10 | `query_temperature(servo_id)` | 查询温度 | servo_id | temperature (ADC值) |
| 10 | `query_status(servo_id)` | 查询工作状态 | servo_id | 8位状态标志位 |
| 11 | `disable_torque(servo_id)` | 舵机失锁 | servo_id | 无 |
| 12 | `set_origin_point(servo_id)` | 原点设置（-M型号专用，需失锁） | servo_id | 无 |
| 13 | `send_sync_angle(command_id, servo_num, command_data_list)` | 同步角度控制 | 见下方 | 无 |
| 13 | `send_sync_anglebyinterval(...)` | 同步角度(基于加减速时间) | 同上 | 无 |
| 13 | `send_sync_anglebyvelocity(...)` | 同步角度(基于目标速度) | 同上 | 无 |
| 13 | `send_sync_multiturnangle(...)` | 同步多圈角度 | 同上 | 无 |
| 13 | `send_sync_multiturnanglebyinterval(...)` | 同步多圈(基于加减速时间) | 同上 | 无 |
| 13 | `send_sync_multiturnanglebyvelocity(...)` | 同步多圈(基于目标速度) | 同上 | 无 |
| 13 | `send_sync_servo_monitor(servo_ids)` | 同步舵机数据监控 | servo_ids | 无 |
| 14 | `begin_async()` | 开始异步指令缓存 | 无 | 无 |
| 14 | `end_async(cancel)` | 结束异步/执行/取消 | cancel (0执行/1取消) | 无 |
| 15 | `query_servo_monitor(servo_id)` | 获取舵机全部数据 | servo_id | dict(voltage, current, power, temp, status, angle, turn) |
| 16 | `stop_on_control_mode(servo_id, method, power)` | 停止后保持状态 | method: 0x10卸力/0x11锁力/0x12阻尼 | 无 |

---

## `set_servo_angle` 参数详解

```
set_servo_angle(servo_id, angle, is_mturn=False, interval=None,
                velocity=None, t_acc=20, t_dec=20, power=0, mean_dps=100.0)
```

- **angle**: 单圈[-180°, 180°]，多圈[-368640.0°, 368640.0°]
- **is_mturn**: 多圈模式开关
- **interval**: 运动周期(ms)
- **velocity**: 目标转速(dps)
- **t_acc/t_dec**: 加速/减速时间(ms)
- **power**: 功率限制(mW)

---

## `query_status` 状态标志位

| BIT | 含义 |
|-----|------|
| 0 | 执行指令中 |
| 1 | 执行指令错误 |
| 2 | 堵转错误 |
| 3 | 电压过高 |
| 4 | 电压过低 |
| 5 | 电流错误 |
| 6 | 功率错误 |
| 7 | 温度错误 |

---

## 同步命令编号（适用于 V316+ 无刷磁编码舵机）

| 编号 | 命令名 | 功能 | 数据格式 (struct) |
|------|--------|------|-------------------|
| 8 | MoveOnAngleMode | 角度模式 | `<BhHH` (ID, angle, interval, power) |
| 11 | MoveOnAngleModeExByInterval | 角度模式(加减速) | `<BhHHHH` (ID, angle, interval, t_acc, t_dec, power) |
| 12 | MoveOnAngleModeExByVelocity | 角度模式(速度) | `<BhHHHH` (ID, angle, velocity, t_acc, t_dec, power) |
| 13 | MoveOnMultiTurnAngleMode | 多圈角度 | `<BlLH` (ID, angle, interval, power) |
| 14 | MoveOnMultiTurnAngleModeExByInterval | 多圈(加减速) | `<BlLHHH` (ID, angle, interval, t_acc, t_dec, power) |
| 15 | MoveOnMultiTurnAngleModeExByVelocity | 多圈(速度) | `<BlHHHH` (ID, angle, velocity, t_acc, t_dec, power) |
| 22 | ServoMonitor | 舵机数据监控 | - |

---

## `query_servo_monitor` 返回值

返回一个字典，包含：`voltage`(mV), `current`(mA), `power`(mW), `temp`(ADC), `status`, `angle`, `turn`

---

## 注意事项

- **同步命令/异步命令/数据监控/控制模式停止** 仅适用于 **无刷磁编码舵机 V316 及以上版本**
- **原点设置** 仅适用于绝对值编码器舵机（型号尾缀 **-M**），需在失锁状态下使用
- **清除多圈圈数** 须在失锁状态下使用
- 温度返回的是 **ADC值**，可通过文档附表中的对照表转换为摄氏度（50°C=1191, 79°C=598，线性关系）

---

## 温度 ADC 值转换表（附表1）

| 温度(℃) | ADC | 温度(℃) | ADC | 温度(℃) | ADC |
|---------|-----|---------|-----|---------|-----|
| 50 | 1191 | 60 | 941 | 70 | 741 |
| 51 | 1164 | 61 | 918 | 71 | 723 |
| 52 | 1137 | 62 | 897 | 72 | 706 |
| 53 | 1110 | 63 | 876 | 73 | 689 |
| 54 | 1085 | 64 | 855 | 74 | 673 |
| 55 | 1059 | 65 | 835 | 75 | 657 |
| 56 | 1034 | 66 | 815 | 76 | 642 |
| 57 | 1010 | 67 | 796 | 77 | 627 |
| 58 | 986 | 68 | 777 | 78 | 612 |
| 59 | 963 | 69 | 759 | 79 | 598 |

