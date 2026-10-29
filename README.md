# servo-flexible-arm

伺服柔性臂项目。当前阶段：电机驱动协议知识库 + Python 调试 GUI（已实机联调）。

## 电机

- 25-30mm 驱控一体伺服电机（手册版本 V20260921，苏州指尖智擎）
- CAN-FD 通信（ISO CAN FD，仲裁 1 Mbps / 数据 4 Mbps，采样点 80%）
- 单网络最多 60 节点，出厂节点号 N=1，可通过 0x4FE 广播帧改号（V20260921 新增）
- 三种控制模式：MIT（上电默认）/ 速度 / 位置

## USB-CAN-FD 适配器（已验证）

- HCANFD Pro-II 双通道（四川禾华盛，WinUSB 免驱，SDK: HCanbus.dll）
- 官方二次开发库已内置：`vendor/hcanbus/x64/`
- 通路验证：设备级 / 环回级 / 总线级 / 指令级 四级全通过（2026-10-08 实测）

## 环境搭建（虚拟环境）

```powershell
# Windows（一键脚本，使用官方 Python 3.11，含 tkinter）
powershell -ExecutionPolicy Bypass -File setup_env.ps1

# Linux / Ubuntu 20.04（一键脚本：venv + libcanbus 驱动库 + udev 规则）
bash setup_env.sh
```

> ⚠ Windows 必须用官方 Python（含 tkinter）；Espressif/定制版 Python 无 tkinter。
> 核心运行库零第三方依赖；requirements.txt 中仅为可选辅助工具（pypdf/paramiko）。

## 快速开始

```powershell
# 1) 创建虚拟环境（已建好；如需重建）
#    官方 Python 3.11（含 tkinter）: python -m venv .venv

# 2) GUI 调试台（主入口）
.venv\Scripts\python.exe tools\motor_gui.py

# 3) 通路自检（四级验证）
.venv\Scripts\python.exe tools\test_can_path.py --send-test

# 4) 协议编解码自检（手册全部示例帧）
.venv\Scripts\python.exe tools\motor_codec.py

# 解码一帧 hex（自动按 8/12/20 字节识别帧类型）
.venv\Scripts\python.exe tools\motor_codec.py 010001800080200364000080
```

## Python API（供二次开发）

```python
from motorapi import MotorApi, MotorConfig
api = MotorApi(MotorConfig(channel=0, node=1, gear_ratio=50))
api.connect(); api.run_speed(30); api.stop_motor(); api.disconnect()
```
**交付同事：`docs/api.md`（详细 API 文档）+ `motorapi/` + `examples/`。**
多电机同通道控制使用 `MotorNetwork`（API 1.1.0）：一个通道、一个接收线程，
为各节点提供高层 `MotorApi`。用法见 `docs/api.md` §3.3；独立单电机用法兼容。
协议背景与全部实测结论见 `docs/motor-canfd-knowledge-base.md`（§14-17：适配器SDK差异/实测汇总/架构/台架状态）。

## 目录结构

| 文件 | 说明 |
|---|---|
| `25-30mm驱控一体电机使用说明手册_20260921.pdf` | 原始手册（现行版本） |
| `docs/motor-canfd-knowledge-base.md` | 协议知识库（主文档，含 V20260921 变更） |
| `docs/motor-protocol.json` | 协议机器可读规格 |
| `docs/hcanbus-api-manual.pdf` | 适配器 SDK API 手册（禾华盛 V1.3） |
| `motorapi/` | **Python 控制库**（transport 驱动 + codec 协议 + motor 高层API） |
| `docs/api.md` | API 文档（给同事的二次开发入口） |
| `examples/api_examples.py` | API 示例（监控/速度/轨迹/正弦外环/工具） |
| `tools/motor_gui.py` | **GUI 调试台**（纯 motorapi 调用，无业务逻辑） |
| `tools/test_can_path.py` | 通路四级验证脚本 |
| `tools/hcanbus.py` | HCanbus.dll ctypes 封装（80% 采样点时序自动计算） |
| `tools/motor_codec.py` | 电机协议编解码器 + 手册示例帧自检 |
| `vendor/hcanbus/` | 适配器官方 SDK（x64 DLL/头文件） |
| `vendor/hcanbus/linux/` | Linux 驱动库（ubuntu20/22/arm/arm64 的 libcanbus + udev 规则） |
| `setup_env.ps1 / setup_env.sh` | 一键环境搭建（venv + 驱动库） |
| `requirements.txt` | 可选辅助依赖 |
> `can资料/`（440MB 厂商原始资料）不入库，本地保留

## GUI 功能

- 双通道扫描连接，ISO CAN FD 1M/4M@80% 自动配置
- 电机状态实时显示（50Hz）+ 位置/速度/电流示波曲线
- 运行控制：使能/停止/置零/模式切换（自动遵守"先停机后切模式"）
- MIT 力位混合：位置/速度/Kp/Kd/前馈，单帧或 10-500Hz 连续发送
- 纯速度/纯位置模式：一键 切模式→使能→下发目标
- 编码器零点校准（密钥指令 + 结果监控）、电机编号 N 写入（0x4FE）
- 原始报文日志（收/发/回显、ID 过滤）与自定义帧发送

## 注意事项

- 电机供电 10-18V（红=V+，黑=V-），CAN 口不供电
- 改号（0x4FE）与校准操作前务必阅读 GUI 内警示
- 编码器多圈位置断电丢失，上电后建议先置零或以机械限位为参考
