#!/bin/bash
# Linux 环境搭建（Ubuntu 20.04 实测；需系统已装 python3-tk / libusb）
set -e
sudo apt-get install -y python3-venv python3-tk libusb-1.0-0 || true
python3 -m venv .venv --system-site-packages     # tkinter 来自系统包
./.venv/bin/pip install -r requirements.txt

# 安装 CAN 适配器驱动库（libcanbus）+ udev 规则
sudo tar -xf "vendor/hcanbus/linux/libcanbus(ubuntu20).tar" -C /usr/local/lib/
sudo cp vendor/hcanbus/linux/hcanbus.rules /etc/udev/rules.d/99-hcanbus.rules
sudo ldconfig
sudo udevadm control --reload-rules && sudo udevadm trigger

echo ""
echo "环境就绪。验证："
echo "  ./.venv/bin/python tools/test_can_path.py --node 3 --send-test"
echo "  ./.venv/bin/python tools/motor_gui.py    # 上位机"
