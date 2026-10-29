# motorapi —— 25-30mm 驱控一体电机控制库（API 文档）

> 版本：1.1.0 · 协议依据：《25-30mm驱控一体电机使用说明手册》V20260921
> 适配器：HCANFD Pro-II 双通道 USB-CAN-FD（四川禾华盛）
> 平台：Windows 10/11（x64）· Linux x86_64（Ubuntu 20.04 实测）/ arm64（库已提供未实测）
> 依赖：**零第三方依赖**（仅 Python 标准库 ctypes/tkinter 等）

---

## 1. 概述与架构

`motorapi` 是 25-30mm 驱控一体电机的完整控制库，分三层：

单电机使用 `MotorApi`；多电机同通道由 `MotorNetwork` 管理连接和接收，
各节点仍通过 `MotorApi` 操作（见 §3.3）。

```
┌─────────────────────────────────────────────────────┐
│  MotorApi（motor.py）高层控制                         │
│  连接/状态流/使能/模式/MIT/轨迹/校准/回零/改号/测速比   │
│  ↳ 上位机(tools/motor_gui.py)与你的程序都只调这一层    │
├─────────────────────────────────────────────────────┤
│  codec.py 协议编解码                                  │
│  小端/偏移二进制/DLC映射/0x4FE改号/校准密钥/全部帧型     │
├─────────────────────────────────────────────────────┤
│  transport.py 适配器驱动                              │
│  Windows: HCanbus.dll  Linux: libcanbus.so           │
│  自动80%采样点时序计算 · 收发串行锁 · 双通道           │
└─────────────────────────────────────────────────────┘
```

核心约定（**先读这段，避免踩坑**）：

1. **单位**：协议帧里的位置/速度都是**电机端**（减速器前）数值；
   API 对外一律用**输出端**单位，内部按 `gear_ratio`（R）自动换算。
   **输出端角度 = 电机端角度 ÷ R；输出端转速 = 电机端转速 ÷ R。**
2. **速度上限**：电机端 ±3000rpm（协议硬限制），换算后输出端上限 = 3000/R rpm，
   API 自动限幅（`clamp_rpm()`，超限会被钳位）。
3. **位置模式的速度字段被固件忽略**（实测 V20260921 固件）。需要控制运动速度请用
   `start_trajectory()`（MIT 梯形轨迹）或 `start_mit_streaming()`（自定义外环）。
4. **模式切换必须先停机**（手册硬性要求）——API 的 `set_mode/run_speed/run_position/
   start_trajectory` 已自动按 正确序列发送。
5. **MIT 控制前必须运行使能**——`send_mit(auto_run=True)` 与所有一键接口已内置。
6. **编码器为单圈绝对值**：多圈位置断电丢失。上电后建议 `set_zero()` 或机械限位归零。
7. **回调在工作线程触发**（接收线程/轨迹线程）。GUI 等单线程环境请用队列转发到主线程
   （参考 `tools/motor_gui.py` 的 `rx_queue` 模式）。
8. **线程安全**：所有适配器收发在库内已串行化（锁保护），多线程调用 API 是安全的；
   但对同一台电机，建议同一时刻只有"一种运动"在跑（流式 MIT / 轨迹 二选一）。

---

## 2. 安装

### 2.1 获取

项目根目录直接导入（无需 pip 安装）：

```python
import sys
sys.path.insert(0, r"/path/to/servo-flexible-arm")   # 项目根
from motorapi import MotorApi, MotorConfig
```

或设置环境变量 `PYTHONPATH=/path/to/servo-flexible-arm`。

### 2.2 Windows

- SDK DLL 已随仓库：`vendor/hcanbus/x64/HCanbus.dll`（自动加载，WinUSB 免驱）。
- 无需安装任何驱动（设备管理器显示 "CANFD Analyser" 即可）。

### 2.3 Linux（Ubuntu 20.04 实测）

一次性安装（管理员执行）：

```bash
# 1) 解压厂商库（按发行版选择，Ubuntu20.04 用 ubuntu20 包）
sudo tar -xf "can资料/02 二次开发资料/Linux驱动和测试源码/libcanbus(ubuntu20).tar" -C /usr/local/lib/
sudo ldconfig

# 2) udev 规则（非 root 用户可访问 USB 设备）
sudo cp hcanbus.rules /etc/udev/rules.d/99-hcanbus.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

依赖：系统需有 `libusb-1.0`（上条 tar 已自带；若冲突可 `apt install libusb-1.0-0-dev`）。

### 2.4 验证安装

```bash
python tools/test_can_path.py --node 3 --listen 3 --send-test
# 四级验证：设备级 → 回环级 → 总线级(电机状态帧) → 指令级(MIT回复)
```

---

## 3. 快速上手

### 3.1 最小示例

```python
from motorapi import MotorApi, MotorConfig

api = MotorApi(MotorConfig(channel=0, node=3, gear_ratio=50))
api.connect()                    # ISO CAN FD 1M/4M@80% 自动配置
st = api.wait_status()           # 等第一帧状态（电机须上电）
print(st.position_out_deg, st.bus_voltage_v, st.motor_type)

api.run_speed(30)                # 输出端 30rpm（自动: 停机→切速度→使能→下发）
import time; time.sleep(3)
api.stop_motor()
api.disconnect()
```

### 3.2 上下文管理器

```python
with MotorApi(MotorConfig(node=3, gear_ratio=50)) as api:
    api.connect()
    api.run_position(90)         # 输出端 90°（注意: 固件忽略速度字段）
    api.stop_motor()
```

---

### 3.3 多电机共享通道：MotorNetwork

三台电机共用一个 HCANFD 通道时，用 `MotorNetwork` 注册三个 `MotorApi`。
网络只打开一次通道，以一个接收线程按节点分发反馈；每个电机仍使用上文
的高层方法，不需要应用程序编码 CAN 帧。

```python
from motorapi import MotorNetwork, MotorConfig

network = MotorNetwork(channel=0)
# 编号、减速比仅为示例，须替换成实测值。
motors = [network.motor(MotorConfig(channel=0, node=n, gear_ratio=50))
          for n in (1, 2, 3)]
try:
    network.connect()
    for motor in motors:
        st = motor.wait_status()
        print(motor.node, st.position_out_deg, st.fault_code)
finally:
    network.disconnect()  # 尝试停止每台电机，再关闭唯一通道
```

需要运动时，对返回的电机调用 `set_mode(MODE_MIT)`、`send_mit(...)`、
`run_enable()`、`stop_motor()` 等方法。`send_mit` 输入仍为输出端角度/转速，
减速比换算在 API 内完成。ROS 控制器可以在自己的轨迹循环中调用它，
无需同时启动 API 的 `start_trajectory` 或 `start_mit_streaming`。

节点必须唯一，通道参数必须一致；连接前完成注册。网络连接/断开由同一
管理线程负责。单个电机 `disconnect()` 只停止并停用自身，不关闭其他电机
的通道；`connect()` 可重新接入现有网络。最终由 `network.disconnect()` 关闭通道。
只读监控程序可用 `network.disconnect(stop_motors=False)` 退出，不向电机发送停止帧。
回调共用接收线程，必须快速返回，耗时工作应转交队列。共享网络禁止
`set_node` 和广播 `set_node_id`；改号请退出共享控制并单台接线后使用独立 API。

新增状态字段 `fault_code`、`motor_state_raw`、`mode_raw` 保留完整故障与枚举值。
`get_status()` 遇到接收错误会抛出 `MotorApiError`；反馈新鲜度仍应通过
`timestamp` 检查，`wait_status()` 不接受超过 0.5 秒的旧反馈。
`output_position_limit_deg` 返回输出端协议位置上限。
发送未成功发出一帧时抛出 `MotorApiError`，接收异常后仍允许尝试停止电机。
独立单电机 `MotorApi(MotorConfig(...))` 的用法保持兼容。

## 4. 配置参考：MotorConfig

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `channel` | int | 0 | 适配器通道：0=CAN1，1=CAN2 |
| `node` | int | 1 | **电机编号 N**（1..60）。CAN ID = 0x501+4N 等；出厂 1，可用 0x4FE 改（见 §8.6） |
| `gear_ratio` | float | 1.0 | **减速比 R**（输出端:电机端）。⚠ 未设置时所有输出端数值=电机端数值 |
| `nom_baud` | int | 1000000 | 仲裁段波特率（电机要求 1M） |
| `dat_baud` | int | 4000000 | 数据段波特率（电机固定 4M） |
| `sample_point` | float | 0.80 | 采样点（电机要求 80%） |
| `kp` | float | 0.008 | MIT 位置增益默认值（手册建议，过大易震荡） |
| `kd` | float | 1.0 | MIT 速度增益默认值（手册建议） |

运行期修改（立即生效，无需重连）：

```python
api.set_gear_ratio(50)   # 或 api.cfg.gear_ratio = 50
api.set_node(3)
```

> ⚠ 教训（已修复）：确保通过上述方法修改，而不是只改自己程序里的本地变量——
> 上位机曾出现"显示用新 R、控制用旧 R"的不一致事故。

---

## 5. 状态监控

### 5.1 MotorStatus 字段

| 字段 | 单位 | 说明 |
|---|---|---|
| `timestamp` | s | host 单调时钟 |
| `position_deg` / `position_out_deg` | ° | 电机端 / **输出端**位置 |
| `position_code` | count | 原始 21bit 码值（多圈，2097152/圈） |
| `position_out_turns` | 圈 | **输出端**圈数 |
| `velocity_rpm` / `velocity_out_rpm` | rpm | 电机端 / **输出端**速度 |
| `current_a` | A | 相电流 |
| `bus_voltage_v` | V | 母线电压（10~18V 正常，<8 或 >18 会报故障） |
| `faults` | list[str] | 故障名列表（空=无故障），见 §10.2 |
| `fault_code` | int | 完整故障位图，包含尚未命名的位 |
| `motor_state_raw` / `mode_raw` | int | 原始电机状态 / 模式枚举 |
| `motor_state` | str | 初始化/电流校准/编码器零点校准/停止/运行/错误 |
| `calib_state` | str | 空闲/校准/完成/错误 |
| `mode` | str | MIT模式/速度模式/位置模式 |
| `motor_type` | str | 30mm/25mm/20mm/16mm |

### 5.2 回调注册

```python
api.on_status(cb)      # cb(st: MotorStatus)          50Hz 状态帧
api.on_reply(cb)       # cb(d: dict)                  MIT 一问一答回复
api.on_frame(cb)       # cb(can_id, data, ts_us, ft)  任意原始帧（ft 位含回显/方向标志）
api.on_tx(cb)          # cb(can_id, data)             本 API 发出的每一帧（记录发送日志用）
api.on_calibration(cb) # cb({"state":..., "ok":bool}) 校准完成/错误
```

### 5.3 主动读取

```python
st = api.get_status()              # 最近一帧缓存，无数据返回 None
st = api.get_status(timeout=0.3, max_age=0.2)   # 可选等待新鲜数据
st = api.wait_status(timeout=2.0)  # 阻塞直到新鲜状态；超时抛 MotorApiError
```

---

## 6. 基础控制

| 方法 | 说明 | 帧序列 |
|---|---|---|
| `run_enable()` | 运行使能 | 0x502+4N: `01 00 00 …` |
| `stop_motor()` | 停止 | 0x502+4N: `00 00 00 …` |
| `set_zero()` | 当前位置置零（电机停止并回MIT模式） | `00 01 00 …` |
| `set_mode(mode)` | 切模式（自动先停机）。`mode`: `MODE_MIT/MODE_SPEED/MODE_POSITION` | `00 00 <mode> …` |
| `send_raw(can_id, data)` | 发送任意 CAN FD 帧（调试） | — |

---

## 7. 运动控制

### 7.1 MIT 单帧：send_mit()

```python
data: bytes = api.send_mit(
    position_out_deg=180.0,     # 目标位置（输出端°）；None→0
    velocity_out_rpm=0.0,       # 目标速度（输出端rpm）
    kp=None, kd=None,           # None→用 MotorConfig.kp/kd
    ff_current_a=0.0,           # 前馈电流（力矩补偿）
    auto_run=False,             # True=发送前自动运行使能（MIT 必须先使能）
)
# 返回实际发送的 12 字节帧（hex 查看用）；速度超限自动钳位至 3000/R
```

MIT 原理（手册）：电机执行 `cref = Kp·(p_des − p) + Kd·(v_des − v) + c_ff`。
- Kp=Kd=0 → 纯电流（力矩）模式
- Kp=0, Kd≠0 → 阻尼
- Kp≠0, Kd=0 → 会震荡，勿用

### 7.2 MIT 连续发送 + 自定义轨迹外环（推荐做柔顺控制）

```python
api.start_mit_streaming(position_out_deg=0, velocity_out_rpm=0,
                        kp=0.008, kd=1.0, hz=100, auto_run=True)

# 运行中实时改参数（例如自己实现 S 曲线/正弦/导纳外环）：
api.set_streaming_params(position_out_deg=30.0, velocity_out_rpm=5.0,
                         ff_current_a=0.1)          # 未给的参数保持不变

api.stop_mit_streaming(stop_motor=True)   # 停止发送；stop_motor=False 则保持当前状态
```

### 7.3 纯速度模式：run_speed()

```python
api.run_speed(rpm_out)     # 输出端 rpm；自动 停机→切速度→使能→下发；超限自动钳位
```

### 7.4 纯位置模式：run_position()

```python
api.run_position(deg_out, rpm_out=60.0)
# ⚠ 实测固件忽略速度字段 rpm_out（仅写进帧内，不影响运动速度）。
#    需要控速请用 7.5 轨迹模式。
```

### 7.5 MIT 梯形轨迹：start_trajectory()（速度真正可控，推荐）

```python
state = api.start_trajectory(
    target_out_deg=180.0,     # 输出端目标位置
    speed_out_rpm=30.0,       # 输出端巡航速度
    accel_out_rpms=100.0,     # 输出端加速度（rpm/s）
    kp=None, kd=None,         # MIT 增益
    blocking=False,           # True=阻塞到完成
    on_done=cb,               # cb(state: TrajectoryState)
    stop_on_done=False,       # True=完成后停机（默认保持位置锁止）
)
```

- 内部：梯形规划（行程不足自动退化为三角曲线），100Hz 流式下发 `p_des(t)+v_des(t)`
- `api.traj_state` 随时读进度：`running/t/total/p_des/v_des_rpm/done/aborted`
- `api.abort_trajectory()` 立即中止并停机
- 线程内自动完成 停机→切MIT→使能→轨迹流

### 7.6 回零：home()

```python
ok = api.home(speed_out_rpm=60.0, blocking=True, timeout=60.0)
# 位置模式回到 电机端码值0 = 上次置零点（若从未置零则为上电位置）
# blocking=True 返回是否到位（超时自动停机）
```

---

## 8. 工具类接口

### 8.1 查询适配器

```python
api.scan()          # -> [{'index':0,'type':1,'type_name':'CANFD'}, ...]
api.device_info()   # -> {'hw_type':'HCANFD Pro-II','serial':'…','fw_ver':'…',...}
api.dev_clock()     # -> 80000000 (Hz)
```

### 8.2 编码器零点校准：calibrate()

```python
ok = api.calibrate(blocking=True, timeout=20.0)
# 序列: 停机+MIT → 0x503+4N 校准密钥 55AACC337711FF00 → 等 0x703+4N/状态帧 data17
# ⚠ 电机会旋转约10秒，全程禁止断电；确保电机轴无阻碍
# blocking=False 时用 on_calibration 回调取结果
```

### 8.3 修改电机编号：set_node_id()

```python
cid, data = api.set_node_id(new_n)     # 0x4FE 广播帧
# ⚠ 总线上必须只有这一台电机（否则全体被改成同一编号）
# ⚠ 写入后需断电重新上电生效；此后 API 用 set_node(new_n) 通信
```

### 8.4 减速比测量辅助

```python
# 电动校验法（输出轴贴标记）：
api.measure_gear_ratio_electric(candidate=50)
# 电机自动: 置零 → 位置模式走 candidate×360°（输出端应恰好整1圈回到标记处）
# 人眼确认标记对齐 → R=candidate → api.set_gear_ratio(candidate)
```

### 8.5 协议编解码直用（codec 层）

```python
from motorapi import encode_mit_frame, deg_to_pos_code, decode_status, can_ids
frame = encode_mit_frame(pos_code=deg_to_pos_code(180), vel_rpm=0,
                         kp=0.008, kd=1.0, ff_current_a=0)
print(can_ids(3))          # {'mit_send':0x50D, 'motor_control':0x50E, ...}
print(decode_status(raw20))# 全字段解析
```

### 8.6 适配器底层直用（transport 层）

```python
from motorapi import HCanbus, MODE_LOOPBACK
bus = HCanbus(); bus.open(0)
bus.canfd_init(1_000_000, 4_000_000, 0.80, MODE_LOOPBACK)  # 回环自检
bus.send_fd(0x123, bytes(range(12)))
frames = bus.recv_fd(timeout_ms=100)     # [FDFrame...]
bus.close()
```

---

## 9. 完整示例程序

见 `examples/api_examples.py`：

| 示例 | 内容 |
|---|---|
| 1 | 状态监控（50Hz 回调打印） |
| 2 | 速度模式启停 |
| 3 | MIT 轨迹运动（速度可控） |
| 4 | 自定义轨迹外环（正弦摆动，运行中实时改参数） |
| 5 | 回零/校准/改号 |

上位机 `tools/motor_gui.py`（1000 行）是最大的"示例"：全部功能都只通过 MotorApi 实现。

---

## 10. 故障排查与已知问题

### 10.1 常见故障

| 现象 | 原因/处理 |
|---|---|
| `wait_status` 超时 | 电机未上电(10~18V)/CAN 线接反/N 不对/波特率不符。先跑 `tools/test_can_path.py` |
| 发送后 TE 计数涨到 128 | 总线无 ACK：电机断电或 CANH/L 断线 |
| 电机不动但无故障 | 未运行使能（用 auto_run=True 一键接口）；或 N 不匹配（指令发给了不存在的 ID） |
| 位置只走一点 | R 未设置（默认 1.0）→ 按电机端执行；设置 gear_ratio |
| 位置模式速度无效 | **固件行为（实测）**，改用 start_trajectory |
| Linux 权限错误 | udev 规则未装/未触发（§2.3） |
| 打不开通道 | 另一进程占用（关掉其他上位机/GUI 实例） |

### 10.2 故障字（状态帧 faults）

驱动芯片故障 / 过压(>18V) / 欠压(<8V) / 过流(10s功率过大) / 编码器故障。
故障恢复：手册未定义，实测断电重启可清除。

### 10.3 已知差异/注意事项

1. Linux 库数据段采样点回填 75%（请求 80%）——实测 1M/4M 通信正常，如遇误码再排查。
2. Linux 下双通道设备=1 个设备号 + 通道 0/1（transport 层已屏蔽差异，API 层无感）。
3. 适配器 DLL/so 非线程安全声明——transport 已用锁串行化全部调用。
4. 状态帧 data0-1 为标识段 `0x01+4N, 0x05`（N=1 时 `05 05`），可校验电机编号。
5. 协议无"读参数"类指令；扭矩常数、额定电流等手册未提供。
6. Linux 库要求 Open 前先 Scan（USB 重枚举后设备号变化）；`LibCANbus_Init/Exit`
   由 transport 层按引用计数严格管理——**这些已在库内处理，直接用即可**；
   若绕过 MotorApi 直用 HCanbus，请遵循 open/close 配对。
7. 适配器同一时刻只能被一个进程打开（GUI 与脚本不能同时连同一通道）。

---

## 11. 版本

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0.0 | 2026-10-09 | 首版：全 API、跨平台、实测验证（Windows/Linux 台架） |
| 1.1.0 | 2026-10-09 | MotorNetwork 多节点共享通道；完整故障码及状态枚举；发送失败和接收错误上报。共享网络已通过模拟测试，尚未实机联调 |

---

## 12. 交付物清单

| 文件 | 说明 |
|---|---|
| `motorapi/` | 库源码（transport.py / codec.py / motor.py / network.py / __init__.py） |
| `docs/api.md` | 本文档 |
| `docs/motor-canfd-knowledge-base.md` | 协议知识库（背景与实测结论） |
| `docs/motor-protocol.json` | 协议机器可读规格 |
| `examples/api_examples.py` | 5 个示例 |
| `tools/motor_gui.py` | 上位机（API 用法参考实现） |
| `tools/test_can_path.py` | 通路四级自检 |
| `vendor/hcanbus/` | Windows SDK |
| `can资料/02 二次开发资料/` | 厂商原始 SDK（含 Linux 库 tar、API 手册 PDF） |
