#!/usr/bin/env python3
"""兼容壳：适配器驱动已迁移至 motorapi.transport（本文件保留旧导入路径）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motorapi.transport import *      # noqa: F401,F403
from motorapi.transport import (HCanbus, FDFrame, calc_bit_timing, CanFDConfig,
                                CanFDMsg, DevInfo, CanStatus, DLC_TO_LEN,
                                LEN_TO_DLC, len_to_dlc)

if __name__ == "__main__":
    bus = HCanbus()
    devs = bus.scan()
    print(f"扫描到 {len(devs)} 个 CAN/CANFD 通道:", devs)
    if devs:
        bus.open(devs[0]["index"])
        print("设备信息:", bus.dev_info())
        print("主频:", bus.dev_clock(), "Hz")
        bus.close()
