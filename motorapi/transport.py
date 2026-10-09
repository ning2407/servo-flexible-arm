#!/usr/bin/env python3
"""HCanbus 的 Python ctypes 封装 —— 跨平台（Windows / Linux）。

Windows: vendor/hcanbus/x64/HCanbus.dll（WinUSB, __stdcall）
Linux:   /usr/local/lib/libcanbus.so（libusb, cdecl）
         需先 LibCANbus_Init()，所有通道函数多一个 chNum 参数，
         双通道设备 = 1个设备号0 + 通道0/1；CAN_GetDevType 改名 CAN_GetCHType。

厂商：四川禾华盛电子科技有限公司（动态库接口函数使用说明 V1.3）
配套设备：HCANFD Pro-II（VID 0xA8FA PID 0x8598）

用法（两平台一致）：
    from hcanbus import HCanbus
    bus = HCanbus()
    bus.scan()               # 扫描（Linux下自动展开为通道列表）
    bus.open(0)              # 打开 0 号通道（CAN1）
    bus.canfd_init(1_000_000, 4_000_000, sample_point=0.80)
    bus.send_fd(0x505, bytes(12))
    frames = bus.recv_fd(timeout_ms=100)

返回值约定（与官方手册一致）：
    Open/Init/Close 等：0 = 成功，-1 = 失败
    ScanDevice：设备数
    Transmit/Receive：实际帧数，-1 = 失败
"""

from __future__ import annotations

import ctypes
import io
import os
import sys
import threading
from ctypes import (POINTER, byref, c_char, c_int, c_uint, c_ubyte, c_ushort)
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------- 常量
DEV_TYPE_NAMES = {0: "CAN2.0", 1: "CANFD", 2: "LIN"}

CFG_INTREN = 0x01   # 接通内部终端电阻
CFG_OFFWKUP = 0x02  # 离线唤醒
CFG_AUTORTX = 0x04  # 自动重传

MODE_NORMAL = 0x00
MODE_LOOPBACK = 0x01
MODE_SILENT = 0x02
MODE_SILENT_LOOPBACK = 0x03

CANTYPE_CAN = 0x00
CANTYPE_ISO_CANFD = 0x01   # 电机要求：ISO CAN FD
CANTYPE_NONISO_CANFD = 0x02

FMT_DIRTX = 0x01
FMT_CANFD = 0x04
FMT_FDBRS = 0x08
FMT_ECHO = 0x40

BUS_ERRWRN = 0x01
BUS_ERRPAS = 0x02
BUS_BUSOFF = 0x04
BUS_NORM = 0x08

DLC_TO_LEN = {d: l for d, l in enumerate(
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64])}
LEN_TO_DLC = {l: d for d, l in DLC_TO_LEN.items()}


def len_to_dlc(n: int) -> int:
    if n in LEN_TO_DLC:
        return LEN_TO_DLC[n]
    for l in sorted(DLC_TO_LEN.values()):
        if l >= n:
            return LEN_TO_DLC[l]
    return 15


# ---------------------------------------------------------------- 结构体（两平台一致）
class DevInfo(ctypes.Structure):
    _fields_ = [
        ("HW_Type", c_char * 32),
        ("HW_Ser", c_char * 32),
        ("HW_Ver", c_char * 32),
        ("FW_Ver", c_char * 32),
        ("MF_Date", c_char * 32),
    ]


class CanFDConfig(ctypes.Structure):
    _fields_ = [
        ("NomBaud", c_uint),
        ("DatBaud", c_uint),
        ("NomPre", c_ushort),
        ("NomTseg1", c_char),
        ("NomTseg2", c_char),
        ("NomSJW", c_char),
        ("DatPre", c_char),
        ("DatTseg1", c_char),
        ("DatTseg2", c_char),
        ("DatSJW", c_char),
        ("Config", c_char),
        ("Model", c_char),
        ("Cantype", c_char),
    ]


class CanFDMsg(ctypes.Structure):
    _fields_ = [
        ("ID", c_uint),
        ("TimeStamp", c_uint),
        ("FrameType", c_char),
        ("DLC", c_char),
        ("ExternFlag", c_char),
        ("RemoteFlag", c_char),
        ("BusSatus", c_char),
        ("ErrSatus", c_char),
        ("TECounter", c_char),
        ("RECounter", c_char),
        ("Data", c_ubyte * 64),
    ]


class CanStatus(ctypes.Structure):
    _fields_ = [
        ("BusSatus", c_char),
        ("ErrSatus", c_char),
        ("TECounter", c_char),
        ("RECounter", c_char),
        ("TimeStamp", c_uint),
    ]


# ---------------------------------------------------------------- 高层封装
@dataclass
class FDFrame:
    id: int
    data: bytes
    timestamp_us: int = 0
    frame_type: int = 0
    extended: bool = False
    remote: bool = False
    bus_status: int = 0
    err_status: int = 0

    @property
    def is_fd(self) -> bool:
        return bool(self.frame_type & FMT_CANFD)

    @property
    def is_brs(self) -> bool:
        return bool(self.frame_type & FMT_FDBRS)

    @property
    def is_echo(self) -> bool:
        return bool(self.frame_type & FMT_ECHO)

    def __str__(self) -> str:
        flags = ("FD " if self.is_fd else "") + ("BRS " if self.is_brs else "") + \
                ("EXT " if self.extended else "") + ("ECHO" if self.is_echo else "")
        return f"0x{self.id:03X} [{len(self.data):02d}] {self.data.hex(' ')}  {flags.strip()}"


def calc_bit_timing(plck: int, baud: int, sample_point: float = 0.80):
    best = None
    for pres in range(1, 65):
        total = plck / (pres * baud)
        n = round(total)
        if n < 3 or n > 256:
            continue
        err = abs(n - total) / total
        tq1 = round(n * sample_point) - 1
        tq2 = n - 1 - tq1
        if tq1 < 1 or tq2 < 1 or tq1 > 255 or tq2 > 127:
            continue
        sjw = min(tq2, 4 if tq2 >= 4 else tq2)
        cand = (err, pres, tq1, tq2, sjw)
        if best is None or cand < best:
            best = cand
    if best is None:
        raise ValueError(f"无法为 plck={plck} baud={baud} 计算位时序")
    err, pres, tq1, tq2, sjw = best
    return {"pres": pres, "tseg1": tq1, "tseg2": tq2, "sjw": sjw,
            "total_tq": 1 + tq1 + tq2, "baud_error": err}


# Linux 库生命周期（模块级引用计数）：
# LibCANbus_Init 必须在所有操作前调用一次；LibCANbus_Exit 必须在所有通道关闭后
# 调用一次。多实例共享：首个 open 时 Init，最后一个 close 时 Exit。
# （曾用 atexit+新建CDLL 调 Exit，触发 libusb pthread_mutex_destroy 断言崩溃）
_lib_users = 0
_lib_lock = threading.Lock()
_lib_inited = False


class HCanbus:
    """单通道 USB-CAN-FD 的高层封装（跨平台）。"""

    def __init__(self, dll_path: Optional[str] = None):
        global _linux_exit_registered
        if IS_WINDOWS:
            if dll_path is None:
                root = Path(__file__).resolve().parent.parent
                dll_path = str(root / "vendor" / "hcanbus" / "x64" / "HCanbus.dll")
            self._dll = ctypes.WinDLL(dll_path)
            self._linux = False
        else:
            # 先全局加载 libusb（厂商要求），优先用自带版本
            try:
                ctypes.CDLL("libusb-1.0.so", mode=ctypes.RTLD_GLOBAL)
            except OSError:
                ctypes.CDLL("/usr/local/lib/libusb-1.0.so", mode=ctypes.RTLD_GLOBAL)
            if dll_path is None:
                dll_path = os.environ.get("HCANBUS_LIB", "/usr/local/lib/libcanbus.so")
            self._dll = ctypes.CDLL(dll_path)
            self._linux = True   # Init/Exit 由 open/close 按引用计数管理
        # HCanbus.dll 线程安全性未知：所有 DLL 调用一律串行化，避免死锁。
        self._lock = threading.RLock()
        self._bind()
        self.dev: Optional[int] = None   # 逻辑通道号（对上层即 CAN1/CAN2）

    # ---------------------------------------------------------- 库函数绑定
    def _bind(self) -> None:
        d = self._dll
        li = self._linux
        self._scan = d.CAN_ScanDevice
        self._scan.restype = c_int
        # 通道级函数：Linux 多一个 chNum 参数
        # open/close
        self._open = d.CAN_OpenDevice
        self._open.restype = c_int
        self._open.argtypes = [c_uint] + ([c_uint] if li else [])
        self._close = d.CAN_CloseDevice
        self._close.restype = c_int
        self._close.argtypes = [c_uint] + ([c_uint] if li else [])
        # 设备类型（Linux: CAN_GetCHType(dev, ch)）
        gt = d.CAN_GetCHType if li else d.CAN_GetDevType
        self._gettype = gt
        self._gettype.restype = c_int
        self._gettype.argtypes = [c_uint] + ([c_uint] if li else [])
        # 主频/信息（设备级，两平台一致）
        self._getplck = d.CAN_GetDevPlck
        self._getplck.restype = c_int
        self._getplck.argtypes = [c_uint]
        self._readinfo = d.CAN_ReadDevInfo
        self._readinfo.restype = c_int
        self._readinfo.argtypes = [c_uint, POINTER(DevInfo)]
        # 状态
        self._getstatus = d.CAN_GetStatus
        self._getstatus.restype = c_int
        self._getstatus.argtypes = [c_uint] + ([c_uint] if li else []) + [POINTER(CanStatus)]
        # CANFD
        self._fd_init = d.CANFD_Init
        self._fd_init.restype = c_int
        self._fd_init.argtypes = [c_uint] + ([c_uint] if li else []) + [POINTER(CanFDConfig)]
        self._fd_tx = d.CANFD_Transmit
        self._fd_tx.restype = c_int
        self._fd_tx.argtypes = [c_uint] + ([c_uint] if li else []) + \
            [POINTER(CanFDMsg), c_uint, c_int]
        self._fd_rxnum = d.CANFD_GetReceiveNum
        self._fd_rxnum.restype = c_int
        self._fd_rxnum.argtypes = [c_uint] + ([c_uint] if li else [])
        self._fd_rx = d.CANFD_Receive
        self._fd_rx.restype = c_int
        self._fd_rx.argtypes = [c_uint] + ([c_uint] if li else []) + \
            [POINTER(CanFDMsg), c_int, c_int]
        self._reset = d.CAN_Reset
        self._reset.restype = c_int
        self._reset.argtypes = [c_uint] + ([c_uint] if li else [])

    # 平台参数展开：Linux 全部 (dev=0, ch)，Windows (ch)
    def _a(self):
        """返回通道级函数的地址参数元组。"""
        return (0, self.dev) if self._linux else (self.dev,)

    # ---------------------------------------------------------- 设备管理
    def scan(self) -> List[dict]:
        """扫描通道，返回 [{'index','type','type_name'}]。Linux 下自动展开双通道。"""
        with self._lock:
            n = self._scan()
        if n < 0:
            raise RuntimeError("CAN_ScanDevice 失败")
        devs = []
        if not self._linux:
            for i in range(n):
                t = self._gettype(i)
                if t < 2:
                    devs.append({"index": i, "type": t,
                                 "type_name": DEV_TYPE_NAMES.get(t, str(t))})
        else:
            # Linux：设备数 n，每个设备展开其通道（本产品为双通道 CANFD）
            for dev in range(n):
                for ch in range(2):
                    t = self._gettype(dev, ch)
                    if t < 2:
                        devs.append({"index": ch, "type": t, "dev": dev,
                                     "type_name": DEV_TYPE_NAMES.get(t, str(t))})
        return devs

    def open(self, dev: int = 0) -> None:
        """打开逻辑通道（0=CAN1, 1=CAN2）。Windows: devNum=ch；Linux: dev=0, ch=ch。"""
        args = (0, dev) if self._linux else (dev,)
        with self._lock:
            if self._linux:
                global _lib_users, _lib_inited
                with _lib_lock:
                    if not _lib_inited:
                        if self._dll.LibCANbus_Init() != 0:
                            raise RuntimeError("LibCANbus_Init 失败")
                        _lib_inited = True
                    _lib_users += 1
                # Linux 库要求先 ScanDevice 刷新设备列表（USB 重枚举后设备号会变，
                # 否则 OpenDevice 报"通道不存在/被占用"；厂商示例同样是先 Scan 后 Open）
                self._scan()
            ret = self._open(*args)
        if ret != 0:
            if self._linux:
                with _lib_lock:
                    _lib_users = max(0, _lib_users - 1)
            raise RuntimeError(f"CAN_OpenDevice({args}) 失败（通道被占用或不存在）")
        self.dev = dev

    def close(self) -> None:
        if self.dev is None:
            return
        with self._lock:
            if self._linux:
                self._close(0, self.dev)
            else:
                self._close(self.dev)
            self.dev = None
            if self._linux:
                global _lib_users, _lib_inited
                with _lib_lock:
                    _lib_users = max(0, _lib_users - 1)
                    if _lib_users == 0 and _lib_inited:
                        try:
                            self._dll.LibCANbus_Exit()
                        finally:
                            _lib_inited = False

    def dev_type(self) -> int:
        self._require_open()
        with self._lock:
            return self._gettype(*self._a())

    def dev_clock(self) -> int:
        """设备主频（Hz）。设备级。"""
        self._require_open()
        with self._lock:
            return self._getplck(0 if self._linux else self.dev)

    def dev_info(self) -> dict:
        self._require_open()
        info = DevInfo()
        with self._lock:
            ret = self._readinfo(0 if self._linux else self.dev, byref(info))
        if ret != 0:
            raise RuntimeError("CAN_ReadDevInfo 失败")
        get = lambda s: s.decode("gbk", "replace").strip("\x00 \r\n")
        return {"hw_type": get(info.HW_Type), "serial": get(info.HW_Ser),
                "hw_ver": get(info.HW_Ver), "fw_ver": get(info.FW_Ver),
                "mfg_date": get(info.MF_Date)}

    def status(self) -> dict:
        self._require_open()
        st = CanStatus()
        with self._lock:
            ret = self._getstatus(*self._a(), byref(st))
        if ret != 0:
            raise RuntimeError("CAN_GetStatus 失败")
        return {"bus": st.BusSatus[0], "err": st.ErrSatus[0],
                "te": st.TECounter[0], "re": st.RECounter[0],
                "timestamp_us": st.TimeStamp}

    def reset(self) -> None:
        self._require_open()
        with self._lock:
            self._reset(*self._a())

    # ---------------------------------------------------------- 初始化
    def canfd_init(
        self,
        nom_baud: int = 1_000_000,
        dat_baud: int = 4_000_000,
        sample_point: float = 0.80,
        model: int = MODE_NORMAL,
        cantype: int = CANTYPE_ISO_CANFD,
        config: int = CFG_INTREN | CFG_AUTORTX,
        explicit_timing: bool = True,
    ) -> dict:
        self._require_open()
        cfg = CanFDConfig()
        cfg.NomBaud, cfg.DatBaud = nom_baud, dat_baud
        if explicit_timing:
            plck = self.dev_clock()
            nom = calc_bit_timing(plck, nom_baud, sample_point)
            dat = calc_bit_timing(plck, dat_baud, sample_point)
            cfg.NomPre, cfg.NomTseg1, cfg.NomTseg2, cfg.NomSJW = (
                nom["pres"], nom["tseg1"], nom["tseg2"], nom["sjw"])
            cfg.DatPre, cfg.DatTseg1, cfg.DatTseg2, cfg.DatSJW = (
                dat["pres"], dat["tseg1"], dat["tseg2"], dat["sjw"])
        else:
            cfg.NomPre = cfg.NomTseg1 = cfg.NomTseg2 = cfg.NomSJW = 0
            cfg.DatPre = cfg.DatTseg1 = cfg.DatTseg2 = cfg.DatSJW = 0
        cfg.Config, cfg.Model, cfg.Cantype = config, model, cantype
        with self._lock:
            ret = self._fd_init(*self._a(), byref(cfg))
        if ret != 0:
            raise RuntimeError("CANFD_Init 失败")
        actual = {
            "nom_baud": cfg.NomBaud, "dat_baud": cfg.DatBaud,
            "nom": {"pres": cfg.NomPre, "tseg1": cfg.NomTseg1[0],
                    "tseg2": cfg.NomTseg2[0], "sjw": cfg.NomSJW[0]},
            "dat": {"pres": cfg.DatPre[0], "tseg1": cfg.DatTseg1[0],
                    "tseg2": cfg.DatTseg2[0], "sjw": cfg.DatSJW[0]},
        }
        for key in ("nom", "dat"):
            t = actual[key]
            total = 1 + t["tseg1"] + t["tseg2"]
            t["total_tq"] = total
            t["sample_point"] = round((1 + t["tseg1"]) / total, 4)
        return actual

    # ---------------------------------------------------------- 收发
    def send_fd(self, can_id: int, data: bytes, brs: bool = True,
                extended: bool = False, timeout_ms: int = 100) -> int:
        self._require_open()
        data = bytes(data)
        if len(data) > 64:
            raise ValueError("data 最长 64 字节")
        msg = CanFDMsg()
        msg.ID = can_id
        msg.FrameType = FMT_CANFD | FMT_FDBRS if brs else FMT_CANFD
        msg.DLC = len_to_dlc(len(data))
        msg.ExternFlag = 1 if extended else 0
        msg.RemoteFlag = 0
        mv = memoryview(msg.Data).cast("B")
        mv[:len(data)] = data
        with self._lock:
            n = self._fd_tx(*self._a(), byref(msg), 1, timeout_ms)
        if n < 0:
            raise RuntimeError("CANFD_Transmit 失败")
        return n

    def recv_fd(self, max_items: int = 100, timeout_ms: int = 100) -> List[FDFrame]:
        self._require_open()
        buf = (CanFDMsg * max_items)()
        with self._lock:
            n = self._fd_rx(*self._a(), buf, max_items, timeout_ms)
        if n < 0:
            raise RuntimeError("CANFD_Receive 失败")
        frames = []
        for i in range(n):
            m = buf[i]
            length = DLC_TO_LEN.get(m.DLC[0], 64)
            frames.append(FDFrame(
                id=m.ID, data=bytes(memoryview(m.Data).cast("B")[:length]),
                timestamp_us=m.TimeStamp, frame_type=m.FrameType[0],
                extended=bool(m.ExternFlag[0]), remote=bool(m.RemoteFlag[0]),
                bus_status=m.BusSatus[0], err_status=m.ErrSatus[0]))
        return frames

    def rx_pending(self) -> int:
        self._require_open()
        with self._lock:
            return self._fd_rxnum(*self._a())

    def _require_open(self) -> None:
        if self.dev is None:
            raise RuntimeError("设备未打开，请先调用 open()")

    def __enter__(self) -> "HCanbus":
        return self

    def __exit__(self, *exc):
        self.close()


if __name__ == "__main__":
    bus = HCanbus()
    devs = bus.scan()
    print(f"扫描到 {len(devs)} 个 CAN/CANFD 通道:", devs)
    if devs:
        bus.open(devs[0]["index"])
        print("设备信息:", bus.dev_info())
        print("主频:", bus.dev_clock(), "Hz")
        print("状态:", bus.status())
        bus.close()
