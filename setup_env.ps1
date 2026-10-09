# Windows 环境搭建（PowerShell）
# 注意：必须使用官方 Python 3.11+（含 tkinter）；Espressif 等定制版 Python 无 tkinter
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host ""
Write-Host "环境就绪。验证："
Write-Host "  .\.venv\Scripts\python.exe tools\motor_codec.py        # 协议自检"
Write-Host "  .\.venv\Scripts\python.exe tools\test_can_path.py --node 3 --send-test"
Write-Host "  .\.venv\Scripts\python.exe tools\motor_gui.py           # 上位机"
