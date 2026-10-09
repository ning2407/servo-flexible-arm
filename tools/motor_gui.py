#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""25-30mm 驱控一体电机 CAN-FD 调试台 —— 基于 motorapi 的上位机。

本文件只做界面展示与交互，全部业务逻辑由 motorapi.MotorApi 提供
（同事可直接 import motorapi 复用同一套控制能力）。

运行：
    Windows: .venv\\Scripts\\python.exe tools\\motor_gui.py
    Linux:   python3 tools/motor_gui.py
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from motorapi import (MotorApi, MotorConfig, MotorStatus, MODE_MIT, MODE_SPEED,
                      MODE_POSITION, FMT_ECHO)
from motorapi.codec import (deg_to_pos_code, encode_mit_frame,
                            can_ids as motor_can_ids)

NOM_BAUD = 1_000_000
DAT_BAUD = 4_000_000
SAMPLE_POINT = 0.80


# ================================================================ 实时曲线
class StripChart(ttk.Frame):
    """轻量示波器：多条曲线独立归一化，自动缩放。"""

    def __init__(self, master, series_names, colors, window_sec=15.0):
        super().__init__(master)
        self.series_names = series_names
        self.colors = colors
        self.window = window_sec
        self.data = {name: deque() for name in series_names}
        self.canvas = tk.Canvas(self, height=250, bg="#101418", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._job = None

    def append(self, t: float, values: dict) -> None:
        for name, v in values.items():
            if v is None:
                continue
            dq = self.data[name]
            dq.append((t, v))
            cutoff = t - self.window
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 60 or h < 60:
            return
        pad_l, pad_r, pad_t, pad_b = 56, 84, 8, 16
        pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
        now = time.monotonic()
        t0, t1 = now - self.window, now
        for i in range(5):
            x = pad_l + pw * i / 4
            c.create_line(x, pad_t, x, pad_t + ph, fill="#22282f")
        for i in range(5):
            y = pad_t + ph * i / 4
            c.create_line(pad_l, y, pad_l + pw, y, fill="#22282f")
        legend_y = pad_t + 4
        for name in self.series_names:
            dq = self.data[name]
            if len(dq) < 2:
                continue
            vals = [v for _, v in dq]
            vmin, vmax = min(vals), max(vals)
            if vmax - vmin < 1e-9:
                vmax = vmin + 1e-9
            margin = (vmax - vmin) * 0.08
            vmin -= margin
            vmax += margin
            color = self.colors[name]
            step = max(1, len(dq) // int(pw * 2))
            pts = []
            for (t, v) in list(dq)[::step]:
                x = pad_l + (t - t0) / (t1 - t0) * pw
                y = pad_t + ph - (v - vmin) / (vmax - vmin) * ph
                pts.extend((x, y))
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=1)
            if name == self.series_names[0]:
                c.create_text(4, pad_t + 4, anchor="nw", fill="#8b98a5",
                              text=f"{vmax:9.1f}")
                c.create_text(4, pad_t + ph - 4, anchor="sw", fill="#8b98a5",
                              text=f"{vmin:9.1f}")
            c.create_text(w - 6, legend_y, anchor="ne", fill=color,
                          text=f"{name} {vals[-1]:.2f}")
            legend_y += 14

    def start(self, interval_ms=200):
        self.redraw()
        self._job = self.after(interval_ms, lambda: self.start(interval_ms))

    def stop(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None


# ================================================================ 主应用
class MotorGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("25-30mm 驱控一体电机 CAN-FD 调试台  (V20260921 · motorapi)")
        self.geometry("1280x780")
        self.minsize(1080, 660)

        self.api = MotorApi(MotorConfig())
        self.connected = False
        self.node = 1
        self.rx_queue = queue.Queue()
        self.status_times = deque(maxlen=200)
        self.last_status = None
        self._closing = False
        self._ratio_base = None
        self._ratio_job = None
        self._mit_push_job = None
        self._traj_watch_job = None

        self._build_ui()
        self._wire_api()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll_rx)
    # ---------------------------------------------------------- UI 构建
    def _pick_fonts(self):
        """跨平台字体：Windows 用雅黑/Consolas，Linux 自动挑已安装中文字体。"""
        if sys.platform == "win32":
            return "Microsoft YaHei UI", "Consolas"
        fams = set(tkfont.families(self))
        for cand in ("Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC",
                     "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
                     "Droid Sans Fallback", "AR PL UMing CN"):
            if cand in fams:
                fam = cand
                break
        else:
            fam = tkfont.nametofont("TkDefaultFont").cget("family")
        for cand in ("Noto Sans Mono CJK SC", "Noto Sans Mono CJK JP",
                     "DejaVu Sans Mono"):
            if cand in fams:
                mono = cand
                break
        else:
            mono = fam
        if "CJK" not in mono and "WenQuanYi" not in mono:
            mono = fam
        return fam, mono

    def _build_ui(self):
        self._fam, self._mono = self._pick_fonts()
        style = ttk.Style(self)
        for theme in (("vista",) if sys.platform == "win32" else ("clam",)):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue
        style.configure(".", font=(self._fam, 9))
        style.configure("Big.TButton", font=(self._fam, 10, "bold"))
        style.configure("Stop.TButton", foreground="#b00020",
                        font=(self._fam, 10, "bold"))
        style.configure("HL.TLabel", font=(self._fam, 10, "bold"),
                        foreground="#0b6b3a")

        # ============ 顶部连接栏 ============
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text="通道:").pack(side="left")
        self.ch_var = tk.StringVar(value="CAN1 (#0)")
        self.ch_box = ttk.Combobox(top, textvariable=self.ch_var, state="readonly",
                                   width=10, values=["CAN1 (#0)", "CAN2 (#1)"])
        self.ch_box.pack(side="left", padx=(2, 10))
        ttk.Button(top, text="扫描", width=6, command=self.on_scan).pack(side="left")
        self.btn_conn = ttk.Button(top, text="连接", width=8, command=self.on_connect)
        self.btn_conn.pack(side="left", padx=4)
        self.btn_disc = ttk.Button(top, text="断开", width=8, command=self.on_disconnect,
                                   state="disabled")
        self.btn_disc.pack(side="left", padx=(0, 12))
        ttk.Label(top, text="电机编号 N:").pack(side="left")
        self.node_var = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=60, width=4, textvariable=self.node_var,
                    command=self.on_node_changed).pack(side="left")
        ttk.Label(top, text="减速比R(输出:电机):").pack(side="left", padx=(14, 2))
        self.ratio_var = tk.DoubleVar(value=1.0)
        self.ratio_spin = ttk.Spinbox(top, from_=1.0, to=200.0, increment=0.5,
                                      width=6, textvariable=self.ratio_var,
                                      command=self._update_ratio_warn)
        self.ratio_spin.pack(side="left")
        self.ratio_warn = ttk.Label(top, text="", foreground="#b00020",
                                    font=(self._fam, 9, "bold"))
        self.ratio_warn.pack(side="left", padx=(4, 0))
        self.ratio_spin.bind("<KeyRelease>", lambda e: self._update_ratio_warn())
        self.id_hint = ttk.Label(top, text="", foreground="#666")
        self.id_hint.pack(side="left", padx=(6, 0))
        self.dev_var = tk.StringVar(value="未连接")
        ttk.Label(top, textvariable=self.dev_var, foreground="#0b6b3a").pack(side="right")

        # ============ 主体 ============
        body = ttk.Frame(self, padding=(8, 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ---------- 左列：状态 + 曲线 ----------
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        stf = ttk.LabelFrame(left, text=" 电机实时状态 (0x702+4N · 20ms) ", padding=8)
        stf.pack(fill="x")
        self.st_labels = {}
        rows = [
            ("position", "输出位置 (°)"), ("mpos", "电机端位置 (°)"),
            ("turns", "输出圈数"), ("velocity", "输出速度 (rpm)"),
            ("mvel", "电机端转速"), ("current", "电流 (A)"),
            ("voltage", "母线电压 (V)"), ("motor_state", "电机状态"),
            ("mode", "当前模式"), ("calib", "校准状态"),
            ("mtype", "电机类型"), ("fault", "故障"),
            ("rate", "状态帧率"),
        ]
        for i, (key, name) in enumerate(rows):
            r, c = divmod(i, 2)
            ttk.Label(stf, text=name + ":").grid(row=r, column=c * 2, sticky="w",
                                                 padx=(0, 4), pady=2)
            var = tk.StringVar(value="--")
            self.st_labels[key] = var
            ttk.Label(stf, textvariable=var, style="HL.TLabel", width=12).grid(
                row=r, column=c * 2 + 1, sticky="w", pady=2)
        chf = ttk.LabelFrame(left, text=" 实时曲线 (15s 窗口) ", padding=4)
        chf.pack(fill="both", expand=True, pady=(8, 0))
        self.chart = StripChart(chf, ["位置°", "速度rpm", "电流A"],
                                {"位置°": "#4fc3f7", "速度rpm": "#ffb74d", "电流A": "#81c784"})
        self.chart.pack(fill="both", expand=True)
        self.chart.start(150)

        # ---------- 右列：Notebook ----------
        nb = ttk.Notebook(body)
        nb.grid(row=0, column=1, sticky="nsew")
        self.nb = nb

        # ===== Tab1 运行控制 =====
        f1 = ttk.Frame(nb, padding=10)
        nb.add(f1, text=" 运行控制 ")
        runf = ttk.LabelFrame(f1, text=" 使能 / 停止 ", padding=10)
        runf.pack(fill="x")
        ttk.Button(runf, text="▶ 运行使能", style="Big.TButton",
                   command=lambda: self.send_control(run=True)).pack(
            side="left", padx=6, ipady=4)
        ttk.Button(runf, text="■ 停止", style="Stop.TButton",
                   command=lambda: self.send_control(run=False)).pack(
            side="left", padx=6, ipady=4)
        ttk.Button(runf, text="⌂ 当前位置置零\n(停止并回MIT)",
                   command=lambda: self.send_control(set_zero=True)).pack(
            side="left", padx=6, ipady=2)
        ttk.Label(f1, text="注：置零后电机停止并进入 MIT 模式；仅对位置闭环有效。",
                  foreground="#666").pack(anchor="w", pady=(4, 0))
        modef = ttk.LabelFrame(f1, text=" 模式切换（自动先停机再切换） ", padding=10)
        modef.pack(fill="x", pady=(10, 0))
        for text, mode, desc in (
                ("MIT 力位混合", MODE_MIT, "默认模式，全参数生效"),
                ("纯速度模式", MODE_SPEED, "用速度字段，Kp/Kd/前馈忽略"),
                ("纯位置模式", MODE_POSITION, "用位置字段，Kp/Kd/前馈忽略")):
            ttk.Button(modef, text=text, width=12,
                       command=lambda m=mode: self.send_control(mode=m)).pack(
                side="left", padx=6, ipady=4)
            ttk.Label(modef, text=desc, foreground="#666").pack(side="left", padx=2)
        ttk.Label(f1, text="手册规定：切换模式必须电机停止（data0=0x00），以上按钮自动完成。",
                  foreground="#666").pack(anchor="w", pady=(6, 0))
        dbgf = ttk.LabelFrame(f1, text=" 自定义帧发送（调试） ", padding=10)
        dbgf.pack(fill="x", pady=(10, 0))
        ttk.Label(dbgf, text="ID(hex):").grid(row=0, column=0, sticky="w")
        self.tx_id_var = tk.StringVar(value="505")
        ttk.Entry(dbgf, textvariable=self.tx_id_var, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(dbgf, text="数据(hex,空格分隔):").grid(row=0, column=2,
                                                          sticky="w", padx=(10, 0))
        self.tx_data_var = tk.StringVar(value="00 00 00 80 80 00 00 00 00 00 00 80")
        ttk.Entry(dbgf, textvariable=self.tx_data_var, width=42).grid(row=0, column=3, padx=4)
        ttk.Button(dbgf, text="发送", command=self.on_send_custom).grid(row=0, column=4, padx=6)
        # ===== Tab2 MIT 控制 =====
        f2 = ttk.Frame(nb, padding=10)
        nb.add(f2, text=" MIT 力位混合 ")
        paras = [
            ("目标位置·输出端 (°)", "mit_pos", "0.0"),
            ("目标速度·输出端 (rpm)", "mit_vel", "0.0"),
            ("Kp 位置增益 (建议0.008)", "mit_kp", "0.008"),
            ("Kd 速度增益 (建议1.0)", "mit_kd", "1.0"),
            ("前馈电流 (A)", "mit_ff", "0.0"),
        ]
        pf = ttk.LabelFrame(f2, text=" MIT 指令参数 (0x501+4N · 12字节) ", padding=10)
        pf.pack(fill="x")
        self.mit_vars = {}
        for i, (label, key, default) in enumerate(paras):
            r, c = divmod(i, 3)
            ttk.Label(pf, text=label).grid(row=r * 2, column=c, sticky="w",
                                           padx=(0, 4), pady=(6, 0))
            var = tk.StringVar(value=default)
            self.mit_vars[key] = var
            ttk.Entry(pf, textvariable=var, width=12).grid(row=r * 2 + 1, column=c,
                                                           sticky="w", pady=2)
        seqf = ttk.Frame(f2)
        seqf.pack(fill="x", pady=10)
        self.auto_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(seqf, text="发送前自动运行使能",
                        variable=self.auto_run_var).pack(side="left")
        ttk.Button(seqf, text="发送单帧", style="Big.TButton",
                   command=self.on_mit_send_once).pack(side="left", padx=10)
        self.btn_mit_cont = ttk.Button(seqf, text="● 开始连续发送",
                                       command=self.on_mit_continuous)
        self.btn_mit_cont.pack(side="left", padx=4)
        ttk.Label(seqf, text="频率(Hz):").pack(side="left", padx=(14, 2))
        self.mit_hz_var = tk.IntVar(value=100)
        ttk.Spinbox(seqf, from_=10, to=500, increment=10, width=5,
                    textvariable=self.mit_hz_var).pack(side="left")
        self.mit_frame_preview = tk.StringVar(value="")
        ttk.Label(f2, textvariable=self.mit_frame_preview, foreground="#0b6b3a",
                  font=(self._mono, 9)).pack(anchor="w")
        ttk.Label(f2, text="提示：电机执行 cref = Kp·(p_des−p) + Kd·(v_des−v) + c_ff；"
                           "Kp/Kd 从小往大调，调参前先停机。参数运行中可实时修改。",
                  foreground="#666").pack(anchor="w")

        # ===== Tab3 速度模式 =====
        f3 = ttk.Frame(nb, padding=10)
        nb.add(f3, text=" 纯速度模式 ")
        vf = ttk.LabelFrame(f3, text=" 速度模式启动 ", padding=10)
        vf.pack(fill="x")
        ttk.Label(vf, text="目标速度·输出端 (rpm):").grid(row=0, column=0, sticky="w")
        self.spd_var = tk.StringVar(value="60")
        ttk.Entry(vf, textvariable=self.spd_var, width=10).grid(row=0, column=1, padx=6)
        ttk.Button(vf, text="▶ 切速度模式并运行", style="Big.TButton",
                   command=self.on_speed_start).grid(row=0, column=2, padx=10)
        ttk.Button(vf, text="■ 停止", style="Stop.TButton",
                   command=lambda: self.send_control(run=False)).grid(row=0, column=3)
        ttk.Label(f3, text="序列 = 停止+切速度模式 → 运行使能 → 下发速度目标（Kp/Kd/前馈字段被固件忽略）\n"
                           "输出端速度上限 = 3000 ÷ R rpm（超出自动限幅并提示）",
                  foreground="#666", justify="left").pack(anchor="w", pady=6)

        # ===== Tab4 位置模式 + MIT轨迹 =====
        f4 = ttk.Frame(nb, padding=10)
        nb.add(f4, text=" 纯位置模式 ")
        pf4 = ttk.LabelFrame(f4, text=" 位置模式启动 ", padding=10)
        pf4.pack(fill="x")
        ttk.Label(pf4, text="目标位置·输出端 (°):").grid(row=0, column=0, sticky="w")
        self.pos_var = tk.StringVar(value="90.0")
        ttk.Entry(pf4, textvariable=self.pos_var, width=10).grid(row=0, column=1, padx=6)
        ttk.Label(pf4, text="运动速度·输出端 (rpm):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.pos_spd_var = tk.StringVar(value="60")
        ttk.Entry(pf4, textvariable=self.pos_spd_var, width=10).grid(row=0, column=3, padx=6)
        ttk.Button(pf4, text="▶ 切位置模式并运行", style="Big.TButton",
                   command=self.on_position_start).grid(row=0, column=4, padx=10)
        ttk.Button(pf4, text="■ 停止", style="Stop.TButton",
                   command=lambda: self.send_control(run=False)).grid(row=0, column=5)
        ttk.Button(pf4, text="⌂ 当前位置置零",
                   command=lambda: self.send_control(set_zero=True)).grid(row=1, column=4, pady=6)
        ttk.Label(f4, text="序列 = 停止+切位置模式 → 运行使能 → 下发位置目标；多圈绝对定位，建议先置零。\n"
                           "输出端速度上限 = 3000 ÷ R rpm。实测本固件位置模式【忽略速度字段】——控速请用下方 MIT 轨迹模式。",
                  foreground="#666", justify="left").pack(anchor="w", pady=6)

        tf = ttk.LabelFrame(f4, text=" MIT 轨迹模式（速度真正可控 · 推荐） ", padding=10)
        tf.pack(fill="x", pady=(10, 0))
        ttk.Label(tf, wraplength=560, justify="left", foreground="#444",
                  text="梯形速度规划（加速→匀速→减速），100Hz 流式下发 位置+速度；"
                       "短行程自动退化为三角曲线。").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(tf, text="目标位置·输出端(°):").grid(row=1, column=0, sticky="w")
        self.traj_pos_var = tk.StringVar(value="180.0")
        ttk.Entry(tf, textvariable=self.traj_pos_var, width=9).grid(row=1, column=1, padx=4)
        ttk.Label(tf, text="运动速度·输出端(rpm):").grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.traj_spd_var = tk.StringVar(value="30")
        ttk.Entry(tf, textvariable=self.traj_spd_var, width=9).grid(row=1, column=3, padx=4)
        ttk.Label(tf, text="加速度·输出端(rpm/s):").grid(row=1, column=4, sticky="w", padx=(10, 0))
        self.traj_acc_var = tk.StringVar(value="100")
        ttk.Entry(tf, textvariable=self.traj_acc_var, width=9).grid(row=1, column=5, padx=4)
        ttk.Button(tf, text="▶ MIT轨迹运动", style="Big.TButton",
                   command=self.on_traj_start).grid(row=2, column=1, pady=8, sticky="w")
        ttk.Button(tf, text="■ 中止并停机", style="Stop.TButton",
                   command=self.on_traj_abort).grid(row=2, column=2, pady=8)
        self.traj_status_var = tk.StringVar(value="空闲")
        ttk.Label(tf, textvariable=self.traj_status_var, foreground="#0b6b3a").grid(
            row=2, column=3, columnspan=3, sticky="w", padx=10)

        # ===== Tab5 工具 =====
        f5 = ttk.Frame(nb, padding=10)
        nb.add(f5, text=" 工具 ")
        nf = ttk.LabelFrame(f5, text=" 设置电机编号 N（0x4FE 广播 · V20260921 §3.8） ", padding=10)
        nf.pack(fill="x")
        ttk.Label(nf, text="新编号:").grid(row=0, column=0, sticky="w")
        self.new_node_var = tk.IntVar(value=2)
        ttk.Spinbox(nf, from_=1, to=60, width=4,
                    textvariable=self.new_node_var).grid(row=0, column=1, padx=6)
        ttk.Button(nf, text="写入编号", command=self.on_set_node).grid(row=0, column=2, padx=8)
        ttk.Label(nf, foreground="#b00020",
                  text="⚠ 必须总线上只接这一台电机！否则所有电机都会被写入同一编号；"
                       "写入后需断电重启生效。").grid(row=1, column=0, columnspan=3,
                                                     sticky="w", pady=(6, 0))
        gf = ttk.LabelFrame(f5, text=" 减速比测量 ", padding=10)
        gf.pack(fill="x", pady=(10, 0))
        ef = ttk.Frame(gf)
        ef.pack(fill="x")
        ttk.Label(ef, text="方法A·电动校验（推荐，输出轴贴标记）", style="HL.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(ef, wraplength=560, justify="left", foreground="#444",
                  text="1.在输出轴上贴标记  2.选候选R点[测试]  3.置零后走电机端R×360°（输出端应整1圈）"
                       " 4.标记对齐→[是]；不齐→换候选").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 6))
        ttk.Label(ef, text="候选R:").grid(row=2, column=0, sticky="w")
        self.ratio_cand_var = tk.IntVar(value=50)
        ttk.Combobox(ef, textvariable=self.ratio_cand_var, width=5, state="readonly",
                     values=[6, 9, 10, 15, 20, 25, 30, 33, 36, 50, 60, 70, 80, 100]).grid(
            row=2, column=1, padx=4)
        ttk.Button(ef, text="测试（置零→转R整圈）",
                   command=self.on_ratio_electric_test).grid(row=2, column=2, padx=8)
        ttk.Button(ef, text="⌂ 回零",
                   command=self.on_ratio_home).grid(row=2, column=3, padx=4)
        ttk.Label(ef, foreground="#888",
                  text="回零=回到置零点（测试不成功/中断后用回零返回标记起点）").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        mf = ttk.Frame(gf)
        mf.pack(fill="x", pady=(8, 0))
        ttk.Label(mf, text="方法B·手动转轴（电机端可被手反驱时才可用）", style="HL.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Button(mf, text="开始测量", command=self.on_ratio_start).grid(row=1, column=0, padx=4)
        ttk.Button(mf, text="转完1圈", command=self.on_ratio_done).grid(row=1, column=1, padx=4)
        self.ratio_live_var = tk.StringVar(value="")
        ttk.Label(mf, textvariable=self.ratio_live_var).grid(row=1, column=2, padx=10)
        cf = ttk.LabelFrame(f5, text=" 编码器零点校准（新机/换电机必做 · §4.4） ", padding=10)
        cf.pack(fill="x", pady=(10, 0))
        ttk.Button(cf, text="开始校准", command=self.on_calibrate).pack(side="left", padx=6)
        self.calib_var = tk.StringVar(value="校准状态: --")
        ttk.Label(cf, textvariable=self.calib_var).pack(side="left", padx=10)
        ttk.Label(cf, foreground="#b00020",
                  text="⚠ 校准期间电机会旋转、约10秒、全程禁止断电！").pack(side="left")

        # ===== Tab6 报文日志 =====
        f6 = ttk.Frame(nb, padding=6)
        nb.add(f6, text=" 报文日志 ")
        bar = ttk.Frame(f6)
        bar.pack(fill="x")
        self.pause_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="暂停", variable=self.pause_var).pack(side="left")
        ttk.Button(bar, text="清空", command=self._log_clear).pack(side="left", padx=6)
        ttk.Label(bar, text="ID过滤(hex):").pack(side="left", padx=(12, 2))
        self.filter_var = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.filter_var, width=10).pack(side="left")
        self.log_text = tk.Text(f6, height=14, font=(self._mono, 9), state="disabled",
                                bg="#101418", fg="#c8d3dd", wrap="none")
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text.tag_configure("tx", foreground="#4fc3f7")
        self.log_text.tag_configure("rx", foreground="#c8d3dd")
        self.log_text.tag_configure("echo", foreground="#7f8c99")
        self.log_text.tag_configure("err", foreground="#ff8a80")
    # ---------------------------------------------------------- API 接线
    def _wire_api(self):
        """把 MotorApi 的工作线程回调转入 GUI 消息队列（线程安全）。"""
        self.api.on_status(lambda st: self.rx_queue.put(("status", st)))
        self.api.on_reply(lambda d: self.rx_queue.put(("reply", d)))
        self.api.on_calibration(lambda d: self.rx_queue.put(("calib", d)))
        self.api.on_tx(lambda cid, data: self.rx_queue.put(("tx", (cid, bytes(data)))))
        self.api.on_frame(lambda cid, data, ts, ft:
                          self.rx_queue.put(("frame", (cid, bytes(data), ft))))

    # ---------------------------------------------------------- 日志
    def _log(self, direction, can_id, data, note="", tag="rx"):
        pat = self.filter_var.get().strip().lower() if hasattr(self, "filter_var") else ""
        if pat and pat not in f"{can_id:03x}":
            return
        ts = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        line = (f"{ts}  {direction:<3s}  0x{can_id:03X}  [{len(data):02d}]  "
                f"{data.hex(' '):47s}  {note}\n")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line, tag)
        if int(self.log_text.index("end-1c").split(".")[0]) > 800:
            self.log_text.delete("1.0", "200.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_clear(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------------------------------------------------------- 连接管理
    def on_scan(self):
        try:
            devs = self.api.scan()
            names = [f"CAN{d['index'] + 1} (#{d['index']})" for d in devs]
            self.ch_box.configure(values=names or ["CAN1 (#0)"])
            if names:
                self.ch_box.current(0)
            messagebox.showinfo("扫描", "发现 %d 个 CAN/CANFD 通道:\n%s"
                                % (len(devs), "\n".join(names) if names else "无"))
        except Exception as e:
            messagebox.showerror("扫描失败", str(e))

    def on_connect(self):
        if self.connected:
            return
        try:
            ch = int(self.ch_var.get().split("(#")[1].rstrip(")"))
            self.api.cfg.channel = ch
            self.api.cfg.node = self.node
            self.api.cfg.gear_ratio = self._ratio()
            timing = self.api.connect(ch)
            info = self.api.device_info()
            self.dev_var.set(
                f"{info['hw_type']} SN:{info['serial']} 固件{info['fw_ver']} "
                f"{timing['nom_baud'] / 1e6:.0f}M@{timing['nom']['sample_point']:.0%}/"
                f"{timing['dat_baud'] / 1e6:.0f}M@{timing['dat']['sample_point']:.0%} 已连接")
            self.connected = True
            self.btn_conn.configure(state="disabled")
            self.btn_disc.configure(state="normal")
            self.on_node_changed()
            self._update_ratio_warn()
            self._log("SYS", 0, b"", f"通道{ch}已连接 {info['hw_type']}", "tx")
        except Exception as e:
            messagebox.showerror("连接失败", str(e))

    def on_disconnect(self):
        if self._closing:
            return
        try:
            self._stop_mit_continuous()
            self.api.disconnect()
        except Exception:
            pass
        self.connected = False
        self.dev_var.set("未连接")
        self.btn_conn.configure(state="normal")
        self.btn_disc.configure(state="disabled")
        if hasattr(self, "log_text"):
            self._log("SYS", 0, b"", "已断开", "tx")

    # ---------------------------------------------------------- 消息泵
    def _poll_rx(self):
        status_updated = False
        for _ in range(1000):
            try:
                kind, payload = self.rx_queue.get_nowait()
            except queue.Empty:
                break
            now = time.monotonic()
            if kind == "status":
                st = payload
                self.last_status = st
                self.status_times.append(now)
                self._update_status_panel(st)
                self.chart.append(now, {"位置°": st.position_out_deg,
                                        "速度rpm": st.velocity_out_rpm,
                                        "电流A": st.current_a})
                status_updated = True
                # 原始帧与摘要由 frame 分支统一记录
            elif kind == "reply":
                pass  # 摘要由 frame 分支记录
            elif kind == "tx":
                cid, data = payload
                self._log("TX", cid, data, "", "tx")
            elif kind == "frame":
                cid, data, ft = payload
                base = 0x701 + 4 * self.node
                tag = "echo" if ft & FMT_ECHO else "rx"
                note = ""
                if cid == base + 1 and len(data) == 20 and self.last_status:
                    st = self.last_status
                    note = (f"pos={st.position_out_deg:.2f}° v={st.velocity_out_rpm:.1f} "
                            f"i={st.current_a:.2f}A V={st.bus_voltage_v:.1f} "
                            f"{st.motor_state}/{st.mode}")
                elif cid == base and len(data) == 12:
                    d = self.api._latest_reply or {}
                    note = (f"reply pos={d.get('position_deg', 0):.2f}° "
                            f"v={d.get('velocity_rpm', 0):.1f} "
                            f"i={d.get('current_a', 0):.3f}A")
                if not self.pause_var.get():
                    self._log("RX", cid, data, note, tag)
            elif kind == "calib":
                d = payload
                if isinstance(d, dict):
                    ok = d.get("ok", d.get("done"))
                    state = d.get("state", d.get("result", ""))
                    self.calib_var.set(f"校准状态: {state}")
                    if not self._closing:
                        if ok:
                            messagebox.showinfo("校准完成", f"编码器零点校准完成（{state}）")
                        else:
                            messagebox.showwarning("校准", f"校准结果: {state}")
        if status_updated:
            now = time.monotonic()
            while self.status_times and now - self.status_times[0] > 2.0:
                self.status_times.popleft()
            rate = len(self.status_times) / 2.0 if self.status_times else 0
            self.st_labels["rate"].set(f"{rate:.0f} 帧/s")
        if not self._closing:
            self.after(50, self._poll_rx)

    def _update_status_panel(self, st: MotorStatus):
        L = self.st_labels
        L["position"].set(f"{st.position_out_deg:.2f}")
        L["mpos"].set(f"{st.position_deg:.2f}")
        L["turns"].set(f"{st.position_out_turns:.3f}")
        L["velocity"].set(f"{st.velocity_out_rpm:.1f}")
        L["mvel"].set(f"{st.velocity_rpm:.1f}")
        L["current"].set(f"{st.current_a:.3f}")
        L["voltage"].set(f"{st.bus_voltage_v:.1f}")
        L["motor_state"].set(st.motor_state)
        L["mode"].set(st.mode)
        L["calib"].set(st.calib_state)
        L["mtype"].set(st.motor_type)
        L["fault"].set("无" if not st.faults else "、".join(st.faults))

    def on_node_changed(self):
        try:
            self.node = max(1, min(60, int(self.node_var.get())))
            self.api.set_node(self.node)
        except (tk.TclError, ValueError):
            return
        ids = motor_can_ids(self.node)
        self.id_hint.configure(
            text=f"(发送 0x{ids['mit_send']:03X}/0x{ids['motor_control']:03X} "
                 f"回复 0x{ids['mit_reply']:03X}/0x{ids['motor_status']:03X})")

    # ---------------------------------------------------------- 减速比
    def _ratio(self):
        try:
            r = float(self.ratio_var.get())
        except (tk.TclError, ValueError):
            return 1.0
        return r if r > 0 else 1.0

    def _update_ratio_warn(self):
        if not hasattr(self, "ratio_warn"):
            return
        r = self._ratio()
        # 关键：R 变化必须即时同步到 API，否则控制仍按旧 R 换算（显示/控制不一致）
        try:
            self.api.set_gear_ratio(r)
        except Exception:
            pass
        if r == 1.0:
            self.ratio_warn.configure(
                text="⚠ R=1：请到工具页测减速比，否则位置/速度按电机端执行")
        else:
            self.ratio_warn.configure(text="")

    def _motor_rpm_limited(self, rpm_out):
        # 统一走 API 的换算+限幅，避免两份逻辑漂移
        return self.api.clamp_rpm(rpm_out)

    # ---------------------------------------------------------- 基础控制
    def _require_conn(self):
        if not self.connected:
            messagebox.showwarning("未连接", "请先连接 USB-CAN-FD 适配器")
            return False
        return True

    def send_control(self, run=None, set_zero=False, mode=None):
        if not self._require_conn():
            return
        try:
            if set_zero:
                self.api.set_zero()
            elif mode is not None:
                self.api.set_mode(mode)
            elif run:
                self.api.run_enable()
            else:
                self.api.stop_motor()
        except Exception as e:
            if not self._closing:
                messagebox.showerror("发送失败", str(e))

    # ---------------------------------------------------------- MIT
    def _mit_params(self):
        g = lambda k: float(self.mit_vars[k].get())
        return g("mit_pos"), g("mit_vel"), g("mit_kp"), g("mit_kd"), g("mit_ff")

    def on_mit_send_once(self):
        if not self._require_conn():
            return
        try:
            pos, vel, kp, kd, ff = self._mit_params()
            data = self.api.send_mit(pos, vel, kp, kd, ff,
                                     auto_run=self.auto_run_var.get())
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        except Exception as e:
            messagebox.showerror("发送失败", str(e))
            return
        r = self._ratio()
        _, limited = self._motor_rpm_limited(vel)
        warn = "  [速度已限幅:电机端3000rpm]" if limited else ""
        self.mit_frame_preview.set(
            f"帧预览 → 0x{0x501 + 4 * self.node:03X}: {data.hex(' ').upper()}   "
            f"(输出端→电机端: 位置×{r:g} 速度×{r:g}){warn}")

    def on_mit_continuous(self):
        if self._mit_push_job:
            self._stop_mit_continuous()
            return
        if not self._require_conn():
            return
        try:
            pos, vel, kp, kd, ff = self._mit_params()
            hz = max(10, min(500, int(self.mit_hz_var.get())))
            self.api.start_mit_streaming(pos, vel, kp, kd, ff, hz=hz,
                                         auto_run=self.auto_run_var.get())
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return
        self.btn_mit_cont.configure(text="■ 停止连续发送")
        self._log("SYS", 0, b"", f"MIT 连续发送开始（参数可实时修改）", "tx")

        def push():
            try:
                pos, vel, kp, kd, ff = self._mit_params()
                self.api.set_streaming_params(pos, vel, kp, kd, ff)
            except Exception:
                pass
            self._mit_push_job = self.after(200, push)
        self._mit_push_job = self.after(200, push)

    def _stop_mit_continuous(self):
        if self._mit_push_job:
            self.after_cancel(self._mit_push_job)
            self._mit_push_job = None
            try:
                self.api.stop_mit_streaming(stop_motor=False)
            except Exception:
                pass
            if hasattr(self, "btn_mit_cont"):
                self.btn_mit_cont.configure(text="● 开始连续发送")
                self._log("SYS", 0, b"", "MIT 连续发送停止", "tx")

    # ---------------------------------------------------------- 速度/位置模式
    def on_speed_start(self):
        if not self._require_conn():
            return
        try:
            rpm_out = float(self.spd_var.get())
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        _, limited = self._motor_rpm_limited(rpm_out)
        if limited:
            messagebox.showwarning("速度已限幅",
                                   f"输出端 {rpm_out}rpm 超出上限 "
                                   f"{self.api.output_rpm_limit():.1f}rpm，已自动限幅")
        try:
            self.api.run_speed(rpm_out)
        except Exception as e:
            messagebox.showerror("发送失败", str(e))

    def on_position_start(self):
        if not self._require_conn():
            return
        try:
            deg_out = float(self.pos_var.get())
            rpm_out = float(self.pos_spd_var.get())
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        _, limited = self._motor_rpm_limited(rpm_out)
        if limited:
            messagebox.showwarning("速度已限幅",
                                   f"运动速度超出电机端上限，已自动限幅")
        try:
            self.api.run_position(deg_out, rpm_out)
        except Exception as e:
            messagebox.showerror("发送失败", str(e))

    # ---------------------------------------------------------- MIT 轨迹
    def on_traj_start(self):
        if not self._require_conn():
            return
        try:
            deg = float(self.traj_pos_var.get())
            spd = float(self.traj_spd_var.get())
            acc = float(self.traj_acc_var.get())
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        try:
            _, _, kp, kd, _ = self._mit_params()
            self.api.start_trajectory(deg, spd, acc, kp=kp, kd=kd, blocking=False,
                                      on_done=lambda st: self.rx_queue.put(("traj_done", st)))
        except Exception as e:
            messagebox.showerror("轨迹启动失败", str(e))
            return
        self._log("SYS", 0, b"", f"MIT轨迹启动: 输出端{deg}° @ {spd}rpm", "tx")

        def watch():
            ts = self.api.traj_state
            if ts.running:
                self.traj_status_var.set(
                    f"运动中 t={ts.t:.1f}s/{ts.total:.1f}s v_des={ts.v_des_rpm:.0f}rpm(电机端)")
                self._traj_watch_job = self.after(200, watch)
            else:
                self._traj_watch_job = None
        self._traj_watch_job = self.after(200, watch)

    def on_traj_abort(self):
        try:
            self.api.abort_trajectory()
        except Exception:
            pass
        self.traj_status_var.set("已中止并停机")

    # ---------------------------------------------------------- 工具
    def on_send_custom(self):
        if not self._require_conn():
            return
        try:
            can_id = int(self.tx_id_var.get().strip(), 16)
            hexstr = self.tx_data_var.get().strip().replace(" ", "")
            if len(hexstr) % 2:
                raise ValueError("数据长度必须为偶数个hex字符")
            data = bytes.fromhex(hexstr)
        except ValueError as e:
            messagebox.showerror("格式错误", str(e))
            return
        try:
            self.api.send_raw(can_id, data)
        except Exception as e:
            messagebox.showerror("发送失败", str(e))

    def on_set_node(self):
        if not self._require_conn():
            return
        new_n = int(self.new_node_var.get())
        if not messagebox.askyesno(
                "危险操作确认",
                f"即将把总线上所有电机的编号写为 N={new_n}！\n\n"
                "请确认：总线上只接了这一台电机？\n"
                "写入后需断电重新上电生效。\n\n确定继续？"):
            return
        try:
            cid, _ = self.api.set_node_id(new_n)
        except Exception as e:
            messagebox.showerror("发送失败", str(e))
            return
        messagebox.showinfo("编号写入",
                            f"编号指令已发送（0x{cid:03X}）。\n断电重启后，"
                            "顶部 N 改为 %d 即可通信。" % new_n)

    def on_calibrate(self):
        if not self._require_conn():
            return
        if not messagebox.askyesno(
                "校准确认",
                "编码器零点校准将使电机旋转，约10秒，期间禁止断电。\n"
                "确保电机轴可自由旋转。\n\n确定开始？"):
            return
        self.calib_var.set("校准状态: 进行中(约10s)...")
        try:
            self.api.calibrate(blocking=False)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    def on_ratio_electric_test(self):
        if not self._require_conn():
            return
        try:
            cand = int(self.ratio_cand_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("参数错误", "候选R无效")
            return
        if not messagebox.askyesno(
                "减速比电动校验",
                f"候选 R = {cand}：置零 → 位置模式走电机端 {cand * 360}°（{cand} 整圈）。\n"
                "请先在输出轴贴好标记。确定开始？"):
            return
        try:
            self.api.measure_gear_ratio_electric(cand)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return
        self._log("SYS", 0, b"", f"减速比校验运动中(R={cand})...", "tx")
        target_code = deg_to_pos_code(cand * 360.0)
        self._wait_reach_then(target_code, lambda: self._ask_ratio(cand))

    def _ask_ratio(self, cand):
        if messagebox.askyesno("校验结果",
                               f"电机端已走 {cand * 360}°。输出轴标记是否恰好回到起点？"):
            self.ratio_var.set(float(cand))
            self._update_ratio_warn()
            messagebox.showinfo("完成", f"减速比已设为 R = {cand}")
            self.send_control(run=False)

    def on_ratio_home(self):
        if not self._require_conn():
            return
        if not messagebox.askyesno("回零确认", "电机将回到零点位置，注意安全。确定？"):
            return
        try:
            self.api.home(blocking=False)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return
        self._log("SYS", 0, b"", "回零运动中...", "tx")
        self._wait_reach_then(0, lambda: self.send_control(run=False))

    def _wait_reach_then(self, target_code, done_cb, timeout=60.0):
        deadline = time.monotonic() + timeout

        def poll():
            st = self.api.get_status(timeout=0.02) if self.connected else None
            if st is not None:
                code = st.position_code
                if abs(code - target_code) < deg_to_pos_code(0.5):
                    self.after(600, done_cb)
                    return
            if time.monotonic() > deadline:
                done_cb()
                return
            self.after(200, poll)
        self.after(200, poll)

    def on_ratio_start(self):
        if not self._require_conn():
            return
        st = self.api.get_status(timeout=0.3)
        if st is None:
            messagebox.showwarning("提示", "请先等状态面板出现位置数据再测")
            return
        self._ratio_base = st.position_deg
        self._ratio_live()

    def _ratio_live(self):
        st = self.api.get_status(timeout=0.02) if self.connected else None
        if st is None or self._ratio_base is None:
            return
        delta = st.position_deg - self._ratio_base
        self.ratio_live_var.set(f"电机端已转 {delta:+.1f}°")
        self._ratio_job = self.after(150, self._ratio_live)

    def on_ratio_done(self):
        if self._ratio_base is None:
            messagebox.showwarning("提示", "请先点[开始测量]")
            return
        if self._ratio_job:
            self.after_cancel(self._ratio_job)
            self._ratio_job = None
        st = self.api.get_status(timeout=0.3)
        if st is None:
            return
        delta = abs(st.position_deg - self._ratio_base)
        self._ratio_base = None
        if delta < 30:
            messagebox.showwarning("无效", f"电机端仅检测到 {delta:.1f}°，请转满一圈后重测")
            return
        ratio = delta / 360.0
        self.ratio_var.set(round(ratio, 2))
        self._update_ratio_warn()
        self.ratio_live_var.set(f"减速比 ≈ {ratio:.2f}，已填入顶栏")
        messagebox.showinfo("测得减速比", f"输出轴1圈 = 电机端 {delta:.1f}°\nR = {ratio:.2f}")

    # ---------------------------------------------------------- 退出
    def _on_close(self):
        self._closing = True
        for job in ("_mit_push_job", "_traj_watch_job", "_ratio_job"):
            j = getattr(self, job, None)
            if j:
                try:
                    self.after_cancel(j)
                except Exception:
                    pass
                setattr(self, job, None)
        try:
            self.chart.stop()
        except Exception:
            pass
        try:
            self.api.disconnect()
        except Exception:
            pass
        self.destroy()


def main():
    MotorGui().mainloop()


if __name__ == "__main__":
    main()
