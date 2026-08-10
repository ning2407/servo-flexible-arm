# Fashion Star 总线伺服舵机上位机

## 功能特性

- 🎨 **现代化GUI界面** - 工业风格，精致设计
- 🔍 **自动扫描串口** - 检测所有可用COM口
- 🎯 **舵机设备扫描** - 快速定位总线上的所有舵机
- 📊 **实时状态监控** - 显示角度、电压、电流、功率、温度等
- 📈 **进度可视化** - 扫描过程实时显示

## 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install pyserial
pip install fashionstar-uart-sdk
pip install PyQt6
```

## 使用方法

### 方式一：GUI界面（推荐）

运行图形化界面程序：

```bash
python servo_gui.py
```

## Python SDK

硬件控制已从 GUI 中拆分为独立的 `flexible_arm` SDK。应用程序应通过
`FlexibleArm` 控制机械臂，不需要直接调用 FashionStar 厂商库。

```python
from flexible_arm import FlexibleArm, JointConfig

joints = [
    JointConfig("base", 1, min_deg=-90, max_deg=90),
    JointConfig(
        "shoulder",
        2,
        zero_offset_deg=5,
        direction=-1,
        min_deg=-70,
        max_deg=110,
    ),
]

arm = FlexibleArm(joints)
arm.connect("COM3")
arm.move_joint("base", 30)
arm.move_joints({"base": 0, "shoulder": 20}, duration=1.5)
print(arm.get_state())
arm.disconnect()
```

本地开发安装：

```bash
python3 -m pip install -e ".[gui,test]"
python3 -m pytest
```

SDK 支持关节零偏与方向换算、关节/速度限位、同步运动、状态读取、
后台轨迹执行、暂停、恢复和停止。没有硬件时可以使用
`VirtualServoDriver` 开发和测试，示例见 `examples/`。

**操作步骤：**
1. 从下拉菜单选择串口
2. 点击"连接"按钮
3. 设置扫描ID范围，点击"开始扫描"
4. 查看舵机列表，点击"刷新信息"更新数据

### 方式二：命令行

运行命令行扫描器：

```bash
python servo_scanner.py
```

## 硬件连接

1. 将舵机与转接板连接
2. 连接舵机电源（确保电压与舵机匹配）
3. 通过 USB 将转接板连接到电脑
4. 安装 USB 转 TTL 驱动（如 CH340 驱动）

## 文件说明

| 文件 | 说明 |
|------|------|
| `requirements.txt` | Python 依赖包列表 |
| `servo_gui.py` | 图形化界面上位机（推荐） |
| `servo_scanner.py` | 命令行扫描程序 |
| `SDK_API_Reference.md` | SDK API 参考文档 |

## 界面预览

**设计风格：**
- 深色工业主题
- 蓝色主色调，科技感十足
- 圆角卡片设计
- 实时状态指示器

## 注意事项

- 确保舵机已正确供电
- 确保转接板驱动已安装
- 多个舵机时确保 ID 不冲突
- GUI版本需要 PyQt6 支持
