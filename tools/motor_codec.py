#!/usr/bin/env python3
"""兼容壳：协议编解码已迁移至 motorapi.codec（本文件保留旧导入路径）。

用法不变：
    python tools/motor_codec.py            # 自检
    python tools/motor_codec.py <hex帧>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motorapi.codec import *          # noqa: F401,F403
from motorapi.codec import main

if __name__ == "__main__":
    main()
