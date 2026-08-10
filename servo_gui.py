#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fashion Star 总线伺服舵机 - iOS风格现代化GUI界面
清新、简洁、精致的设计
"""

import time
import sys
import os
import json
import serial
import serial.tools.list_ports
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QSplitter,
    QStatusBar,
    QProgressBar,
    QFrame,
    QScrollArea,
    QTabWidget,
    QDoubleSpinBox,
    QSpinBox,
    QSlider,
    QTextEdit,
    QFileDialog,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QMimeData
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QBrush, QPen, QDrag

from flexible_arm import FlexibleArm, JointConfig

# 快捷键配置文件
SHORTCUT_FILE = "servo_shortcuts.json"

# 默认快捷键配置
DEFAULT_SHORTCUTS = {
    "servo_1_plus": "Key_Q",
    "servo_1_minus": "Key_A",
    "servo_2_plus": "Key_W",
    "servo_2_minus": "Key_S",
    "servo_3_plus": "Key_E",
    "servo_3_minus": "Key_D",
    "servo_4_plus": "Key_R",
    "servo_4_minus": "Key_F",
    "servo_5_plus": "Key_T",
    "servo_5_minus": "Key_G",
    "servo_6_plus": "Key_Y",
    "servo_6_minus": "Key_H",
    "servo_7_plus": "Key_U",
    "servo_7_minus": "Key_J",
    "servo_8_plus": "Key_I",
    "servo_8_minus": "Key_K",
}


class KeyboardMonitorThread(QThread):
    """键盘监控线程"""

    key_pressed = pyqtSignal(str)
    key_released = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.keys_down = set()
        self.keys_pressed = set()  # 记录已发送过第一次按键事件的键

    def run(self):
        self.running = True
        import keyboard

        while self.running:
            for key in list(keyboard.all_modifiers) + list(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            ):
                if keyboard.is_pressed(key):
                    key_name = f"Key_{key.upper()}" if len(key) == 1 else key
                    if key_name not in self.keys_down:
                        self.keys_down.add(key_name)
                        self.keys_pressed.add(key_name)
                        self.key_pressed.emit(key_name)
                else:
                    key_name_upper = f"Key_{key.upper()}"
                    if key_name_upper in self.keys_down:
                        self.keys_down.remove(key_name_upper)
                        self.keys_pressed.discard(key_name_upper)
                        self.key_released.emit(key_name_upper)
                    elif key in self.keys_down:
                        self.keys_down.remove(key)
                        self.keys_pressed.discard(key)
                        self.key_released.emit(key)
            time.sleep(0.05)  # 50ms扫描一次

    def stop(self):
        self.running = False

    def is_key_down(self, key_name):
        """检查按键是否正在按下"""
        return key_name in self.keys_down


class DragDropListWidget(QListWidget):
    """支持拖拽重新排序的列表控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.parent_gui = None

    def set_parent_gui(self, gui):
        self.parent_gui = gui

    def dropEvent(self, event):
        """拖放完成后更新行号"""
        super().dropEvent(event)
        current_row = self.currentRow()
        if current_row >= 0 and self.parent_gui:
            self.parent_gui.status_bar.showMessage(
                f"已重新排序，当前第 {current_row + 1} 行"
            )


class ServoScannerThread(QThread):
    """舵机扫描线程"""

    progress = pyqtSignal(int, int)
    found = pyqtSignal(int)
    finished = pyqtSignal(list)
    serial_error = pyqtSignal()

    def __init__(self, arm, start_id=0, end_id=30):
        super().__init__()
        self.arm = arm
        self.start_id = start_id
        self.end_id = end_id
        self.error_count = 0
        self.max_errors = 5

    def run(self):
        found = []
        total = self.end_id - self.start_id + 1
        for i, servo_id in enumerate(range(self.start_id, self.end_id + 1)):
            if self.error_count >= self.max_errors:
                self.serial_error.emit()
                break
            try:
                is_online = self.arm.ping(servo_id)
                if is_online:
                    found.append(servo_id)
                    self.found.emit(servo_id)
            except:
                self.error_count += 1
            self.progress.emit(i + 1, total)
        self.finished.emit(found)


class ServoInfoThread(QThread):
    """获取舵机详细信息线程（传统方式）"""

    info_ready = pyqtSignal(dict)
    finished = pyqtSignal()
    serial_error = pyqtSignal()

    def __init__(self, arm, servo_ids):
        super().__init__()
        self.arm = arm
        self.servo_ids = servo_ids
        self.error_count = 0
        self.max_errors = 3

    def run(self):
        for servo_id in self.servo_ids:
            if self.error_count >= self.max_errors:
                self.serial_error.emit()
                break
            info = self.get_servo_info(servo_id)
            self.info_ready.emit(info)
            time.sleep(0.05)
        self.finished.emit()

    def get_servo_info(self, servo_id):
        try:
            state = self.arm.read_servo_state(servo_id)
            angle = state.angle_deg
            voltage = state.voltage_v
            current = state.current_a
            power = state.power_w
            temp = state.temperature
            status = state.status
        except Exception:
            angle = voltage = current = power = temp = status = None
            self.error_count += 1

        return {
            "id": servo_id,
            "angle": angle,
            "voltage": voltage,
            "current": current,
            "power": power,
            "temp": temp,
            "status": status,
        }


class SyncMonitorThread(QThread):
    """同步监控线程（高效方式）"""

    all_info_ready = pyqtSignal(dict)  # 发送所有舵机的信息
    finished = pyqtSignal()
    serial_error = pyqtSignal()

    def __init__(self, arm, servo_ids):
        super().__init__()
        self.arm = arm
        self.servo_ids = servo_ids
        self.error_count = 0
        self.max_errors = 3

    def run(self):
        try:
            servo_monitor_data = self.arm.read_servo_states(self.servo_ids)
            result_dict = {}
            for servo_id, info in servo_monitor_data.items():
                if info:
                    result_dict[servo_id] = {
                        "id": servo_id,
                        "angle": info.angle_deg,
                        "turn": info.turn,
                        "power": info.power_w,
                        "temp": info.temperature,
                    }

            self.all_info_ready.emit(result_dict)
            self.finished.emit()
        except:
            self.error_count += 1
            if self.error_count >= self.max_errors:
                self.serial_error.emit()
            else:
                self.finished.emit()


class StatusIndicator(QWidget):
    """状态指示器 - iOS风格圆点"""

    def __init__(self, color=QColor(200, 200, 200)):
        super().__init__()
        self.color = color
        self.setFixedSize(16, 16)

    def set_color(self, color):
        self.color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 外发光效果
            painter.setBrush(
                QBrush(
                    QColor(self.color.red(), self.color.green(), self.color.blue(), 30)
                )
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(2, 2, 12, 12)

            # 主圆点
            painter.setBrush(QBrush(self.color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, 8, 8)
        finally:
            painter.end()


class ServoControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.arm = FlexibleArm()
        self.connected = False
        self.found_servos = []
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_servo_info)
        self.monitoring = False
        self.scanner_thread = None
        self.info_thread = None
        self.servo_sliders = {}  # 存储舵机ID到滑块的映射
        self.servo_offsets = {}  # 存储舵机ID到零偏的映射
        self.offset_file = "servo_offsets.json"  # 零偏文件路径
        self.last_servo_data = {}  # 保存最近一次刷新的舵机数据
        self.slider_data = {}  # 存储每个舵机的拖动状态和定时器
        self.servo_speed = 1000  # 默认速度

        # 顺序执行相关
        self.sequence_commands = []
        self.sequence_running = False
        self.current_command_index = 0
        self.waiting_timer = None
        self.loop_count = 0

        # 快捷键相关
        self.shortcuts = {}  # 存储快捷键配置
        self.keyboard_thread = None
        self.shortcut_step = 5  # 每次按键调整的角度步长
        self.shortcut_enabled = False  # 快捷键是否启用
        self.shortcut_period = 200  # 快捷键发送周期(ms)，同时用于命令总时间
        self.long_press_timers = {}  # 存储长按定时器 {key_name: timer}

        self.init_ui()
        self.refresh_ports()
        self.load_shortcuts()

    def init_ui(self):
        self.setWindowTitle("Fashion Star 舵机控制")
        self.setMinimumSize(1200, 700)

        self.setup_theme()

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧面板 - 串口和扫描
        left_panel = self.create_left_panel()
        left_panel.setFixedWidth(340)
        main_layout.addWidget(left_panel)

        # 右侧标签页
        self.right_tab_widget = QTabWidget()

        # 标签页1: 舵机列表
        monitor_tab = self.create_monitor_tab()
        self.right_tab_widget.addTab(monitor_tab, "舵机列表")

        # 标签页2: 控制
        control_tab = self.create_control_tab()
        self.right_tab_widget.addTab(control_tab, "控制")

        # 标签页3: 同步控制
        sync_control_tab = self.create_sync_control_tab()
        self.right_tab_widget.addTab(sync_control_tab, "同步控制")

        main_layout.addWidget(self.right_tab_widget)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def setup_theme(self):
        app = QApplication.instance()

        palette = QPalette()

        # iOS风格配色 - 清新浅色主题
        bg_color = QColor(242, 242, 247)
        card_color = QColor(255, 255, 255)
        text_color = QColor(28, 28, 30)
        secondary_text = QColor(134, 134, 139)
        accent_color = QColor(0, 122, 255)
        success_color = QColor(52, 199, 89)
        danger_color = QColor(255, 59, 48)

        palette.setColor(QPalette.ColorRole.Window, bg_color)
        palette.setColor(QPalette.ColorRole.WindowText, text_color)
        palette.setColor(QPalette.ColorRole.Base, card_color)
        palette.setColor(QPalette.ColorRole.AlternateBase, bg_color)
        palette.setColor(QPalette.ColorRole.ToolTipBase, card_color)
        palette.setColor(QPalette.ColorRole.ToolTipText, text_color)
        palette.setColor(QPalette.ColorRole.Text, text_color)
        palette.setColor(QPalette.ColorRole.Button, card_color)
        palette.setColor(QPalette.ColorRole.ButtonText, text_color)
        palette.setColor(QPalette.ColorRole.BrightText, accent_color)
        palette.setColor(QPalette.ColorRole.Link, accent_color)
        palette.setColor(QPalette.ColorRole.Highlight, accent_color)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

        app.setPalette(palette)

        # iOS风格样式表
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg_color.name()};
            }}
            
            QWidget {{
                color: {text_color.name()};
            }}
            
            QLabel {{
                color: {text_color.name()};
            }}
            
            QGroupBox {{
                color: {text_color.name()};
                border: none;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 25px;
                font-weight: 600;
                font-size: 15px;
                background-color: {card_color.name()};
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                top: 0px;
                padding: 0px;
            }}
            
            QComboBox {{
                background-color: {bg_color.name()};
                color: {text_color.name()};
                border: 2px solid transparent;
                border-radius: 10px;
                padding: 10px 16px;
                padding-right: 32px;
                font-size: 14px;
                font-weight: 500;
            }}
            
            QComboBox:hover {{
                border: 2px solid rgba(0, 122, 255, 0.3);
            }}
            
            QComboBox:focus {{
                border: 2px solid {accent_color.name()};
            }}
            
            QComboBox::drop-down {{
                border: none;
                width: 30px;
            }}
            
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {secondary_text.name()};
            }}
            
            QComboBox QAbstractItemView {{
                background-color: white;
                border: 1px solid rgba(0, 0, 0, 0.1);
                border-radius: 12px;
                padding: 8px;
                selection-background-color: {accent_color.name()};
                selection-color: white;
            }}
            
            QDoubleSpinBox, QSpinBox {{
                background-color: {bg_color.name()};
                color: {text_color.name()};
                border: 2px solid transparent;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 14px;
                font-weight: 500;
            }}
            
            QDoubleSpinBox:hover, QSpinBox:hover {{
                border: 2px solid rgba(0, 122, 255, 0.3);
            }}
            
            QDoubleSpinBox:focus, QSpinBox:focus {{
                border: 2px solid {accent_color.name()};
            }}
            
            QTableWidget {{
                background-color: {card_color.name()};
                color: {text_color.name()};
                border: none;
                border-radius: 16px;
                gridline-color: rgba(0, 0, 0, 0.05);
                font-size: 14px;
            }}
            
            QTableWidget::item {{
                padding: 12px;
                border: none;
            }}
            
            QTableWidget::item:selected {{
                background-color: rgba(0, 122, 255, 0.1);
                color: {text_color.name()};
            }}
            
            QHeaderView::section {{
                background-color: rgba(242, 242, 247, 0.8);
                color: {secondary_text.name()};
                padding: 14px 12px;
                border: none;
                border-bottom: 1px solid rgba(0, 0, 0, 0.05);
                font-weight: 600;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            
            QHeaderView::section:first {{
                border-top-left-radius: 16px;
            }}
            
            QHeaderView::section:last {{
                border-top-right-radius: 16px;
            }}
            
            QProgressBar {{
                background-color: rgba(0, 122, 255, 0.1);
                border-radius: 6px;
                height: 8px;
                text-align: center;
                color: transparent;
            }}
            
            QProgressBar::chunk {{
                background-color: {accent_color.name()};
                border-radius: 6px;
            }}
        """)

        # 设置标题字体
        for widget in self.findChildren(QLabel):
            if widget.text() == "舵机控制系统":
                title_font = QFont("SF Pro Display", 28, QFont.Weight.Bold)
                widget.setFont(title_font)
                widget.setStyleSheet(f"""
                    color: {text_color.name()};
                    padding: 10px;
                    letter-spacing: -0.5px;
                """)

    def create_left_panel(self):
        """创建左侧面板 - 串口和扫描"""
        panel = QWidget()
        panel.setStyleSheet(
            "background-color: rgb(255, 255, 255); border-right: 1px solid rgba(0, 0, 0, 0.08);"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 串口设置卡片
        port_card = QGroupBox("串口设置")
        port_layout = QVBoxLayout(port_card)
        port_layout.setSpacing(12)

        # 串口选择
        port_sub_layout = QVBoxLayout()
        port_sub_layout.setSpacing(6)
        port_label = QLabel("串口号")
        port_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 12px; font-weight: 600;"
        )
        port_sub_layout.addWidget(port_label)

        self.port_combo = QComboBox()
        port_sub_layout.addWidget(self.port_combo)
        port_layout.addLayout(port_sub_layout)

        # 波特率选择
        baud_sub_layout = QVBoxLayout()
        baud_sub_layout.setSpacing(6)
        baud_label = QLabel("波特率")
        baud_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 12px; font-weight: 600;"
        )
        baud_sub_layout.addWidget(baud_label)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(
            [
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
                "230400",
                "460800",
                "500000",
                "576000",
                "921600",
                "1000000",
            ]
        )
        self.baud_combo.setCurrentText("115200")
        baud_sub_layout.addWidget(self.baud_combo)
        port_layout.addLayout(baud_sub_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(40)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 122, 255, 0.1);
                color: #007AFF;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(0, 122, 255, 0.18);
            }
            QPushButton:disabled {
                background-color: rgba(0, 0, 0, 0.1);
                color: rgba(0, 0, 0, 0.3);
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        btn_layout.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setFixedHeight(40)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4CD964;
            }
            QPushButton:disabled {
                background-color: #A8A8A8;
                color: white;
            }
        """)
        self.connect_btn.clicked.connect(self.toggle_connection)
        btn_layout.addWidget(self.connect_btn)

        self.connection_indicator = StatusIndicator(QColor(200, 200, 200))
        btn_layout.addWidget(self.connection_indicator)

        port_layout.addLayout(btn_layout)
        layout.addWidget(port_card)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(0, 0, 0, 0.06); margin: 8px 0px;")
        layout.addWidget(line)

        # 设备扫描
        scan_title = QLabel("设备扫描")
        scan_title.setStyleSheet(
            "color: rgb(28, 28, 30); font-size: 16px; font-weight: 700; padding-bottom: 4px;"
        )
        layout.addWidget(scan_title)

        # 扫描按钮
        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.setFixedHeight(44)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setEnabled(False)
        layout.addWidget(self.scan_btn)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # 状态信息
        self.scan_info = QLabel("就绪")
        self.scan_info.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px;")
        layout.addWidget(self.scan_info)

        layout.addStretch()

        return panel

    def create_monitor_tab(self):
        """创建舵机列表标签页"""
        tab = QWidget()

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 标题行
        header_layout = QHBoxLayout()

        table_title = QLabel("舵机列表")
        table_title.setStyleSheet(
            "color: rgb(28, 28, 30); font-size: 18px; font-weight: 700;"
        )
        header_layout.addWidget(table_title)

        header_layout.addStretch()

        self.monitoring_label = QLabel("监控状态: 等待扫描")
        self.monitoring_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;"
        )
        header_layout.addWidget(self.monitoring_label)

        layout.addLayout(header_layout)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "角度", "多圈角度", "功率", "温度"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout.addWidget(self.table)

        return tab

    def create_control_tab(self):
        """创建控制标签页"""
        tab = QWidget()

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 舵机选择卡片
        select_card = QGroupBox("舵机选择")
        select_layout = QVBoxLayout(select_card)
        select_layout.setSpacing(12)

        select_label = QLabel("选择舵机:")
        select_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;"
        )
        select_layout.addWidget(select_label)

        self.servo_select_combo = QComboBox()
        self.servo_select_combo.setEnabled(False)
        select_layout.addWidget(self.servo_select_combo)

        layout.addWidget(select_card)

        # 位置控制卡片
        pos_card = QGroupBox("位置控制")
        pos_layout = QVBoxLayout(pos_card)
        pos_layout.setSpacing(12)

        # 角度设置
        angle_label = QLabel("目标角度:")
        angle_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;"
        )
        pos_layout.addWidget(angle_label)

        self.target_angle_spin = QDoubleSpinBox()
        self.target_angle_spin.setRange(-368640, 368640)
        self.target_angle_spin.setDecimals(1)
        self.target_angle_spin.setSuffix(" °")
        self.target_angle_spin.setEnabled(False)
        pos_layout.addWidget(self.target_angle_spin)

        # 控制按钮
        self.set_angle_btn = QPushButton("设置角度")
        self.set_angle_btn.setFixedHeight(44)
        self.set_angle_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.set_angle_btn.clicked.connect(self.set_servo_angle)
        self.set_angle_btn.setEnabled(False)
        pos_layout.addWidget(self.set_angle_btn)

        layout.addWidget(pos_card)

        layout.addStretch()

        return tab

    def create_sync_control_tab(self):
        """创建同步控制标签页（左右布局）"""
        tab = QWidget()

        main_layout = QHBoxLayout(tab)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # ================== 左边：同步控制 ==================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(20)

        # 速度设置
        speed_layout = QHBoxLayout()
        speed_label = QLabel("速度:")
        speed_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 14px; font-weight: 600;"
        )
        speed_layout.addWidget(speed_label)

        self.servo_speed_spin = QSpinBox()
        self.servo_speed_spin.setRange(1, 10000)
        self.servo_speed_spin.setValue(1000)
        self.servo_speed_spin.setSuffix(" dps")
        self.servo_speed_spin.setStyleSheet("""
            QSpinBox {
                background-color: rgba(0, 122, 255, 0.1);
                color: rgb(28, 28, 30);
                border: 2px solid transparent;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 14px;
                font-weight: 500;
                min-width: 120px;
            }
            QSpinBox:hover {
                border: 2px solid rgba(0, 122, 255, 0.3);
            }
            QSpinBox:focus {
                border: 2px solid #007AFF;
            }
        """)
        self.servo_speed_spin.valueChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(self.servo_speed_spin)
        speed_layout.addStretch()

        # 快捷键控制区域
        shortcut_layout = QHBoxLayout()
        shortcut_layout.setSpacing(12)

        # 快捷键启用开关
        self.shortcut_checkbox = QCheckBox("启用快捷键")
        self.shortcut_checkbox.setStyleSheet("""
            QCheckBox {
                color: rgb(28, 28, 30);
                font-size: 13px;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid rgba(0, 122, 255, 0.3);
                border-radius: 4px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #007AFF;
                border: 2px solid #007AFF;
            }
        """)
        self.shortcut_checkbox.stateChanged.connect(self.on_shortcut_toggled)
        shortcut_layout.addWidget(self.shortcut_checkbox)

        # 步长设置
        step_label = QLabel("步长:")
        step_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;"
        )
        shortcut_layout.addWidget(step_label)

        self.shortcut_step_spin = QSpinBox()
        self.shortcut_step_spin.setRange(1, 30)
        self.shortcut_step_spin.setValue(5)
        self.shortcut_step_spin.setSuffix("°")
        self.shortcut_step_spin.setStyleSheet("""
            QSpinBox {
                background-color: rgba(0, 122, 255, 0.1);
                color: rgb(28, 28, 30);
                border: 2px solid transparent;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 13px;
                font-weight: 500;
                min-width: 70px;
            }
            QSpinBox:hover {
                border: 2px solid rgba(0, 122, 255, 0.3);
            }
            QSpinBox:focus {
                border: 2px solid #007AFF;
            }
        """)
        self.shortcut_step_spin.valueChanged.connect(self.on_shortcut_step_changed)
        shortcut_layout.addWidget(self.shortcut_step_spin)

        # 周期设置（同时用于发送间隔和命令总时间）
        period_label = QLabel("周期:")
        period_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;"
        )
        shortcut_layout.addWidget(period_label)

        self.shortcut_period_spin = QSpinBox()
        self.shortcut_period_spin.setRange(50, 1000)
        self.shortcut_period_spin.setValue(200)
        self.shortcut_period_spin.setSuffix("ms")
        self.shortcut_period_spin.setStyleSheet("""
            QSpinBox {
                background-color: rgba(0, 122, 255, 0.1);
                color: rgb(28, 28, 30);
                border: 2px solid transparent;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 13px;
                font-weight: 500;
                min-width: 80px;
            }
            QSpinBox:hover {
                border: 2px solid rgba(0, 122, 255, 0.3);
            }
            QSpinBox:focus {
                border: 2px solid #007AFF;
            }
        """)
        self.shortcut_period_spin.valueChanged.connect(self.on_shortcut_period_changed)
        shortcut_layout.addWidget(self.shortcut_period_spin)

        # 快捷键配置按钮
        self.config_shortcut_btn = QPushButton("配置快捷键")
        self.config_shortcut_btn.setFixedHeight(30)
        self.config_shortcut_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: 500;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
        """)
        self.config_shortcut_btn.clicked.connect(self.show_shortcut_config)
        shortcut_layout.addWidget(self.config_shortcut_btn)

        shortcut_layout.addStretch()

        # 控制按钮
        btn_layout = QHBoxLayout()

        # 归零按钮
        self.reset_all_btn = QPushButton("全部归零")
        self.reset_all_btn.setFixedHeight(36)
        self.reset_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FFB340;
            }
            QPushButton:pressed {
                background-color: #E08600;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.reset_all_btn.clicked.connect(self.reset_all_servos)
        self.reset_all_btn.setEnabled(False)
        btn_layout.addWidget(self.reset_all_btn)

        # 保存零偏按钮
        self.save_offset_btn = QPushButton("保存零偏")
        self.save_offset_btn.setFixedHeight(36)
        self.save_offset_btn.setStyleSheet("""
            QPushButton {
                background-color: #5856D6;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7B79E8;
            }
            QPushButton:pressed {
                background-color: #4A48B8;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.save_offset_btn.clicked.connect(self.save_offsets)
        self.save_offset_btn.setEnabled(False)
        btn_layout.addWidget(self.save_offset_btn)

        # 加载零偏按钮
        self.load_offset_btn = QPushButton("加载零偏")
        self.load_offset_btn.setFixedHeight(36)
        self.load_offset_btn.setStyleSheet("""
            QPushButton {
                background-color: #AF52DE;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #C77AED;
            }
            QPushButton:pressed {
                background-color: #9B46C6;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.load_offset_btn.clicked.connect(self.load_offsets)
        self.load_offset_btn.setEnabled(False)
        btn_layout.addWidget(self.load_offset_btn)

        # 添加到顺序执行按钮
        self.add_to_sequence_btn = QPushButton("添加到顺序")
        self.add_to_sequence_btn.setFixedHeight(36)
        self.add_to_sequence_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.add_to_sequence_btn.clicked.connect(self.add_to_sequence)
        self.add_to_sequence_btn.setEnabled(False)
        btn_layout.addWidget(self.add_to_sequence_btn)

        left_layout.addLayout(speed_layout)
        left_layout.addLayout(shortcut_layout)
        left_layout.addLayout(btn_layout)

        # 滚动区域用于容纳所有舵机控制
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")

        self.sync_control_container = QWidget()
        self.sync_control_layout = QVBoxLayout(self.sync_control_container)
        self.sync_control_layout.setSpacing(16)
        self.sync_control_layout.addStretch()

        scroll.setWidget(self.sync_control_container)
        left_layout.addWidget(scroll)

        # 分隔线
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")

        # ================== 右边：顺序执行 ==================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(20)

        # 右边标题和说明
        right_title_layout = QHBoxLayout()
        right_title = QLabel("顺序执行")
        right_title.setStyleSheet(
            "color: rgb(28, 28, 30); font-size: 18px; font-weight: 700;"
        )
        right_title_layout.addWidget(right_title)
        right_title_layout.addStretch()

        help_label = QLabel("格式: ID1=20,ID2=30,ID3=-20,ID4=-30,runTime=1s,wait=2s")
        help_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 12px;")
        right_title_layout.addWidget(help_label)

        # 循环执行复选框
        self.loop_checkbox = QCheckBox("循环执行")
        self.loop_checkbox.setStyleSheet("""
            QCheckBox {
                color: rgb(28, 28, 30);
                font-size: 13px;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid rgba(0, 122, 255, 0.3);
                border-radius: 4px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #007AFF;
                border: 2px solid #007AFF;
            }
        """)
        right_title_layout.addWidget(self.loop_checkbox)

        # 指令输入区域（使用可拖拽列表控件）
        self.sequence_list = DragDropListWidget()
        self.sequence_list.set_parent_gui(self)
        self.sequence_list.setStyleSheet("""
            QListWidget {
                background-color: white;
                border: 2px solid rgba(0, 122, 255, 0.2);
                border-radius: 12px;
                padding: 8px;
                font-family: Consolas, Monaco, monospace;
                font-size: 13px;
                outline: none;
            }
            QListWidget:focus {
                border: 2px solid #007AFF;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background-color: rgba(0, 122, 255, 0.2);
                color: rgb(28, 28, 30);
            }
            QListWidget::item:hover {
                background-color: rgba(0, 122, 255, 0.1);
            }
        """)
        self.sequence_list.itemClicked.connect(self.on_sequence_item_clicked)

        # 控制按钮
        seq_btn_layout = QHBoxLayout()

        # 保存文件按钮
        self.save_seq_btn = QPushButton("保存文件")
        self.save_seq_btn.setFixedHeight(36)
        self.save_seq_btn.setStyleSheet("""
            QPushButton {
                background-color: #5856D6;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7B79E8;
            }
            QPushButton:pressed {
                background-color: #4A48B8;
            }
        """)
        self.save_seq_btn.clicked.connect(self.save_sequence_file)
        seq_btn_layout.addWidget(self.save_seq_btn)

        # 读取文件按钮
        self.load_seq_btn = QPushButton("读取文件")
        self.load_seq_btn.setFixedHeight(36)
        self.load_seq_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
        """)
        self.load_seq_btn.clicked.connect(self.load_sequence_file)
        seq_btn_layout.addWidget(self.load_seq_btn)

        # 删除选中行按钮
        self.delete_seq_btn = QPushButton("删除选中")
        self.delete_seq_btn.setFixedHeight(36)
        self.delete_seq_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FFB340;
            }
            QPushButton:pressed {
                background-color: #E08600;
            }
        """)
        self.delete_seq_btn.clicked.connect(self.delete_sequence_row)
        seq_btn_layout.addWidget(self.delete_seq_btn)

        # 清空按钮
        self.clear_seq_btn = QPushButton("清空")
        self.clear_seq_btn.setFixedHeight(36)
        self.clear_seq_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FF453A;
            }
            QPushButton:pressed {
                background-color: #D63027;
            }
        """)
        self.clear_seq_btn.clicked.connect(self.clear_sequence)
        seq_btn_layout.addWidget(self.clear_seq_btn)

        self.run_sequence_btn = QPushButton("开始执行")
        self.run_sequence_btn.setFixedHeight(36)
        self.run_sequence_btn.setStyleSheet("""
            QPushButton {
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4CD964;
            }
            QPushButton:pressed {
                background-color: #28A745;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.run_sequence_btn.clicked.connect(self.run_sequence)
        self.run_sequence_btn.setEnabled(False)
        seq_btn_layout.addWidget(self.run_sequence_btn)

        self.stop_sequence_btn = QPushButton("停止执行")
        self.stop_sequence_btn.setFixedHeight(36)
        self.stop_sequence_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FF453A;
            }
            QPushButton:pressed {
                background-color: #D63027;
            }
            QPushButton:disabled {
                background-color: #C7C7CC;
                color: white;
            }
        """)
        self.stop_sequence_btn.clicked.connect(self.stop_sequence)
        self.stop_sequence_btn.setEnabled(False)
        seq_btn_layout.addWidget(self.stop_sequence_btn)

        seq_btn_layout.addStretch()

        # 进度显示
        self.sequence_progress = QLabel("就绪")
        self.sequence_progress.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;"
        )
        seq_btn_layout.addWidget(self.sequence_progress)

        right_layout.addLayout(right_title_layout)
        right_layout.addWidget(self.sequence_list)
        right_layout.addLayout(seq_btn_layout)

        # 添加到主布局
        main_layout.addWidget(left_widget, stretch=1)
        main_layout.addWidget(divider)
        main_layout.addWidget(right_widget, stretch=1)

        return tab

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}", port.device)

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        if self.port_combo.count() == 0:
            self.status_bar.showMessage("没有可用串口")
            return

        port = self.port_combo.currentData()
        if not port:
            return

        try:
            baudrate = int(self.baud_combo.currentText())
            self.arm.connect(port, baudrate)
            self.connected = True

            # 禁用串口和波特率选择，启用扫描按钮
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.scan_btn.setEnabled(True)

            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF3B30;
                    color: white;
                    border: none;
                    border-radius: 10px;
                    padding: 10px 20px;
                    font-weight: 600;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #FF453A;
                }
            """)

            self.connection_indicator.set_color(QColor(52, 199, 89))
            self.scan_btn.setEnabled(True)

            self.status_bar.showMessage(f"已连接: {port} @ {baudrate}bps")

        except Exception as e:
            self.status_bar.showMessage(f"连接失败: {str(e)}")

    def disconnect(self):
        self.arm.disconnect()

        # 停止所有拖动条定时器
        for data in self.slider_data.values():
            if data["timer"]:
                data["timer"].stop()
        self.slider_data.clear()

        self.connected = False
        self.found_servos = []
        self.last_servo_data = {}
        self.stop_monitoring()
        self.stop_keyboard_monitor()
        self.shortcut_checkbox.setChecked(False)
        self.clear_sync_controls()

        # 重新启用串口和波特率选择，禁用控制功能
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.scan_btn.setEnabled(False)
        self.servo_select_combo.clear()
        self.servo_select_combo.setEnabled(False)
        self.target_angle_spin.setEnabled(False)
        self.set_angle_btn.setEnabled(False)
        self.reset_all_btn.setEnabled(False)
        self.save_offset_btn.setEnabled(False)
        self.load_offset_btn.setEnabled(False)
        self.run_sequence_btn.setEnabled(False)
        self.stop_sequence_btn.setEnabled(False)

        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4CD964;
            }
            QPushButton:disabled {
                background-color: #A8A8A8;
                color: white;
            }
        """)

        self.connection_indicator.set_color(QColor(200, 200, 200))
        self.scan_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.monitoring_label.setText("监控状态: 等待扫描")
        self.monitoring_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;"
        )

        self.status_bar.showMessage("已断开")

    def start_scan(self):
        if not self.connected:
            return

        if self.scanner_thread and self.scanner_thread.isRunning():
            return

        self.scan_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(101)
        self.progress_bar.setValue(0)
        self.scan_info.setText("正在扫描...")
        self.table.setRowCount(0)
        self.found_servos = []

        self.scanner_thread = ServoScannerThread(self.arm, 0, 10)
        self.scanner_thread.progress.connect(self.on_scan_progress)
        self.scanner_thread.found.connect(self.on_servo_found)
        self.scanner_thread.finished.connect(self.on_scan_finished)
        self.scanner_thread.serial_error.connect(self.handle_serial_error)
        self.scanner_thread.start()

    def on_scan_progress(self, current, total):
        self.progress_bar.setValue(current)

    def on_servo_found(self, servo_id):
        self.found_servos.append(servo_id)
        self.scan_info.setText(f"已发现: {len(self.found_servos)} 个舵机")

        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(str(servo_id))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item)

    def create_servo_slider(self, servo_id):
        """为指定舵机创建滑块控件"""
        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: white;
                border-radius: 12px;
            }
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 舵机ID标签
        id_label = QLabel(f"舵机 {servo_id}")
        id_label.setStyleSheet(
            "color: rgb(28, 28, 30); font-size: 16px; font-weight: 700; min-width: 70px;"
        )
        layout.addWidget(id_label)

        # 滑块
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-175, 175)
        slider.setValue(0)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: rgba(0, 122, 255, 0.1);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 24px;
                height: 24px;
                background: #007AFF;
                border-radius: 12px;
                margin: -8px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #5AC8FA;
            }
        """)
        layout.addWidget(slider)

        # 角度显示标签
        angle_label = QLabel("0°")
        angle_label.setStyleSheet(
            "color: rgb(0, 122, 255); font-size: 16px; font-weight: 700; min-width: 60px;"
        )
        angle_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(angle_label)

        # 连接信号
        slider.sliderPressed.connect(
            lambda: self.on_slider_pressed(servo_id, angle_label)
        )
        slider.sliderReleased.connect(lambda: self.on_slider_released(servo_id))
        slider.valueChanged.connect(
            lambda value: self.on_slider_value_changed(servo_id, value, angle_label)
        )

        return card, slider

    def on_speed_changed(self, value):
        """速度设置变化时更新"""
        self.servo_speed = value

    def on_slider_pressed(self, servo_id, angle_label):
        """滑块按下时开始定时发送"""
        slider = self.servo_sliders[servo_id]
        current_value = slider.value()

        self.slider_data[servo_id] = {
            "timer": QTimer(),
            "current_value": current_value,
            "release_count": 0,
            "is_dragging": True,
            "angle_label": angle_label,
        }

        data = self.slider_data[servo_id]
        data["timer"].timeout.connect(lambda: self.send_servo_command(servo_id))
        data["timer"].start(100)

        # 立即发送一次
        self.send_servo_command(servo_id)

    def on_slider_value_changed(self, servo_id, value, angle_label):
        """滑块值变化时更新显示和记录"""
        angle_label.setText(f"{value}°")
        if servo_id in self.slider_data:
            self.slider_data[servo_id]["current_value"] = value

    def on_slider_released(self, servo_id):
        """滑块松开时标记状态"""
        if servo_id in self.slider_data:
            self.slider_data[servo_id]["is_dragging"] = False
            self.slider_data[servo_id]["release_count"] = 0

    def send_servo_command(self, servo_id):
        """发送舵机命令"""
        if servo_id not in self.slider_data:
            return

        data = self.slider_data[servo_id]

        if self.connected:
            try:
                self.arm.move_joint(
                    servo_id, data["current_value"], velocity=self.servo_speed
                )
            except Exception:
                pass

        # 处理松开后的发送逻辑
        if not data["is_dragging"]:
            data["release_count"] += 1
            if data["release_count"] >= 3:
                # 发送3次后停止
                data["timer"].stop()
                del self.slider_data[servo_id]

    def reset_all_servos(self):
        """将所有舵机归零（回到零偏角度）"""
        if not self.connected:
            return

        # 先停止所有正在进行的拖动
        for data in self.slider_data.values():
            if data["timer"]:
                data["timer"].stop()
        self.slider_data.clear()

        # 停止所有长按定时器
        for timer in self.long_press_timers.values():
            timer.stop()
        self.long_press_timers.clear()

        # 将所有滑块设为0
        for servo_id, slider in self.servo_sliders.items():
            slider.setValue(0)

        if self.servo_sliders:
            try:
                self.arm.move_joints(
                    {servo_id: 0.0 for servo_id in self.servo_sliders},
                    duration=3.0,
                    acceleration_ms=200,
                    deceleration_ms=200,
                )
            except Exception as e:
                print(f"发送归零命令失败: {e}")

        # 如果快捷键已启用，重新启动键盘监控线程以重置线程内数据
        if self.shortcut_enabled:
            self.stop_keyboard_monitor()
            self.start_keyboard_monitor()

        self.status_bar.showMessage("所有舵机已归零")

    def load_offsets(self):
        """从文件读取零偏"""
        if os.path.exists(self.offset_file):
            try:
                # 检查文件是否为空
                if os.path.getsize(self.offset_file) == 0:
                    self.servo_offsets = {}
                    self.status_bar.showMessage("零偏文件为空")
                    return

                with open(self.offset_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 验证数据格式
                if not isinstance(data, dict):
                    self.servo_offsets = {}
                    self.status_bar.showMessage("零偏文件格式错误")
                    return

                # 将键转换为整数
                self.servo_offsets = {}
                for k, v in data.items():
                    try:
                        servo_id = int(k)
                        self.servo_offsets[servo_id] = float(v)
                    except (ValueError, TypeError):
                        continue

                self.status_bar.showMessage(
                    f"已加载零偏文件: {len(self.servo_offsets)} 个舵机"
                )
                self.apply_joint_config()
            except json.JSONDecodeError:
                self.status_bar.showMessage("零偏文件格式损坏")
                self.servo_offsets = {}
            except Exception as e:
                self.status_bar.showMessage(f"加载零偏失败: {str(e)}")
                self.servo_offsets = {}
        else:
            self.servo_offsets = {}
            self.status_bar.showMessage("零偏文件不存在")

    def apply_joint_config(self):
        """Push GUI calibration into the SDK's joint model."""
        for servo_id in self.found_servos:
            self.arm.configure_joint(
                JointConfig(
                    name=f"joint_{servo_id}",
                    servo_id=servo_id,
                    zero_offset_deg=self.servo_offsets.get(servo_id, 0.0),
                    min_deg=-175.0,
                    max_deg=175.0,
                    max_speed_dps=2000.0,
                )
            )

    def save_offsets(self):
        """保存当前角度为零偏（使用表格显示的数据）"""
        if not self.connected:
            self.status_bar.showMessage("请先连接串口")
            return

        try:
            # 使用最近一次刷新时表格显示的角度作为零偏
            for servo_id in self.found_servos:
                if servo_id in self.last_servo_data:
                    info = self.last_servo_data[servo_id]
                    angle = info["angle"]
                    if angle is not None:
                        self.servo_offsets[servo_id] = angle
                        print(f"舵机 {servo_id} 保存角度: {angle}")

            # 保存到文件
            with open(self.offset_file, "w", encoding="utf-8") as f:
                json.dump(self.servo_offsets, f, ensure_ascii=False, indent=2)

            print(f"保存的零偏数据: {self.servo_offsets}")
            self.apply_joint_config()
            self.status_bar.showMessage(f"已保存零偏: {len(self.servo_offsets)} 个舵机")
        except Exception as e:
            self.status_bar.showMessage(f"保存零偏失败: {str(e)}")

    def clear_sync_controls(self):
        """清空同步控制区域的所有控件"""
        # 停止所有定时器
        for data in self.slider_data.values():
            if data["timer"]:
                data["timer"].stop()
        self.slider_data.clear()
        # 移除所有控件（除了最后一个stretch）
        while self.sync_control_layout.count() > 1:
            item = self.sync_control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.servo_sliders.clear()

    def on_scan_finished(self, found):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_info.setText(f"扫描完成 - 共 {len(found)} 个舵机")
        self.apply_joint_config()

        # 填充舵机选择下拉框
        self.servo_select_combo.clear()
        for servo_id in self.found_servos:
            self.servo_select_combo.addItem(f"舵机 {servo_id}", servo_id)

        # 创建同步控制滑块
        self.clear_sync_controls()
        for servo_id in self.found_servos:
            card, slider = self.create_servo_slider(servo_id)
            # 在stretch之前插入
            self.sync_control_layout.insertWidget(
                self.sync_control_layout.count() - 1, card
            )
            self.servo_sliders[servo_id] = slider

        if found:
            # 启用控制功能
            self.servo_select_combo.setEnabled(True)
            self.target_angle_spin.setEnabled(True)
            self.set_angle_btn.setEnabled(True)
            self.reset_all_btn.setEnabled(True)
            self.save_offset_btn.setEnabled(True)
            self.load_offset_btn.setEnabled(True)
            self.add_to_sequence_btn.setEnabled(True)
            self.run_sequence_btn.setEnabled(True)

            self.refresh_servo_info()
            QTimer.singleShot(
                500, lambda: self.start_monitoring() if len(found) > 0 else None
            )

    def refresh_servo_info(self):
        if not self.connected or not self.found_servos:
            return

        if self.info_thread and self.info_thread.isRunning():
            return

        self.info_thread = SyncMonitorThread(self.arm, self.found_servos)
        self.info_thread.all_info_ready.connect(self.on_all_info_ready)
        self.info_thread.finished.connect(self.on_info_finished)
        self.info_thread.serial_error.connect(self.handle_serial_error)
        self.info_thread.start()

    def handle_serial_error(self):
        self.status_bar.showMessage("检测到串口异常，正在断开连接...")
        self.disconnect()

    def on_all_info_ready(self, all_info):
        # 一次性更新所有舵机信息
        self.last_servo_data = all_info  # 保存最近一次的数据
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                servo_id = int(item.text())
                if servo_id in all_info:
                    info = all_info[servo_id]
                    # 创建并设置不可编辑的表格项
                    for col, value in enumerate(
                        [
                            (
                                f"{info['angle']:.1f}"
                                if info["angle"] is not None
                                else "—"
                            ),
                            f"{info['turn']:.1f}" if info["turn"] is not None else "—",
                            (
                                f"{info['power']:.2f}"
                                if info["power"] is not None
                                else "—"
                            ),
                            str(info["temp"]) if info["temp"] is not None else "—",
                        ],
                        start=1,
                    ):
                        cell_item = QTableWidgetItem(value)
                        cell_item.setFlags(
                            cell_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                        )
                        self.table.setItem(row, col, cell_item)

    def on_info_finished(self):
        self.status_bar.showMessage("信息已更新")

    def start_monitoring(self):
        self.monitoring = True
        self.monitoring_label.setText("监控状态: 运行中")
        self.monitoring_label.setStyleSheet(
            "color: rgb(52, 199, 89); font-size: 13px; font-weight: 600;"
        )

        self.refresh_timer.start(500)
        self.status_bar.showMessage("持续监控已启动: 每 500ms")

    def stop_monitoring(self):
        self.monitoring = False
        if self.refresh_timer.isActive():
            self.refresh_timer.stop()
        self.monitoring_label.setText("监控状态: 已停止")
        self.monitoring_label.setStyleSheet(
            "color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;"
        )

    def set_servo_angle(self):
        """设置舵机角度（多圈模式）"""
        if not self.connected:
            self.status_bar.showMessage("请先连接串口")
            return

        servo_id = self.servo_select_combo.currentData()
        if servo_id is None:
            self.status_bar.showMessage("请先选择舵机")
            return

        target_angle = self.target_angle_spin.value()

        try:
            self.arm.move_joint(servo_id, target_angle)
            self.status_bar.showMessage(
                f"已设置舵机 {servo_id} 角度为 {target_angle}° (多圈模式)"
            )
        except Exception as e:
            self.status_bar.showMessage(f"设置角度失败: {str(e)}")

    def set_servo_damping(self):
        """设置舵机阻尼模式"""
        if not self.connected:
            self.status_bar.showMessage("请先连接串口")
            return

        servo_id = self.servo_select_combo.currentData()
        if servo_id is None:
            self.status_bar.showMessage("请先选择舵机")
            return

        power = self.damping_power_spin.value()

        try:
            self.arm.set_damping(servo_id, power)
            self.status_bar.showMessage(f"已设置舵机 {servo_id} 阻尼功率为 {power}mW")
        except Exception as e:
            self.status_bar.showMessage(f"设置阻尼失败: {str(e)}")

    def parse_sequence_line(self, line):
        """解析一条顺序执行指令"""
        line = line.strip()
        if not line:
            return None

        parts = line.split(",")
        servo_data = {}
        run_time = 1.0
        wait_time = 0.0

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                value = value.strip()

                if key.startswith("ID"):
                    try:
                        servo_id = int(key[2:])
                        angle = float(value)
                        servo_data[servo_id] = angle
                    except ValueError:
                        continue
                elif key == "runTime":
                    try:
                        run_time = float(value.replace("s", ""))
                    except ValueError:
                        run_time = 1.0
                elif key == "wait":
                    try:
                        wait_time = float(value.replace("s", ""))
                    except ValueError:
                        wait_time = 0.0

        if not servo_data:
            return None

        return {
            "servo_data": servo_data,
            "run_time": max(0.1, run_time),
            "wait_time": max(0.1, wait_time),
        }

    def on_sequence_item_clicked(self, item):
        """点击列表项时的处理 - 同步拖动条并控制舵机"""
        row = self.sequence_list.row(item) + 1

        # 解析当前行的指令
        line_text = item.text()
        cmd = self.parse_sequence_line(line_text)

        if cmd and "servo_data" in cmd:
            # 同步每个舵机的拖动条并发送控制指令
            for servo_id, offset_value in cmd["servo_data"].items():
                if servo_id in self.servo_sliders:
                    self.servo_sliders[servo_id].setValue(int(offset_value))

                # 发送控制指令到舵机
                if self.connected:
                    try:
                        self.arm.move_joint(
                            servo_id,
                            offset_value,
                            velocity=self.servo_speed_spin.value(),
                        )
                    except Exception as e:
                        print(f"控制舵机 {servo_id} 失败: {e}")

        self.status_bar.showMessage(f"已选择第 {row} 行")

    def run_sequence(self):
        """开始执行顺序指令"""
        if not self.connected:
            self.status_bar.showMessage("请先连接串口")
            return

        # 先停止所有正在进行的拖动
        for data in self.slider_data.values():
            if data["timer"]:
                data["timer"].stop()
        self.slider_data.clear()

        # 解析指令
        self.sequence_commands = []
        for i in range(self.sequence_list.count()):
            line = self.sequence_list.item(i).text()
            cmd = self.parse_sequence_line(line)
            if cmd:
                self.sequence_commands.append(cmd)

        if not self.sequence_commands:
            self.status_bar.showMessage("没有有效的指令")
            return

        # 初始化执行状态
        self.sequence_running = True
        self.current_command_index = 0
        self.loop_count = 0
        self.waiting_timer = QTimer()
        self.waiting_timer.setSingleShot(True)
        self.waiting_timer.timeout.connect(self.execute_next_command)

        # 更新UI状态 - 只禁用编辑按钮，不禁用整个标签页
        self.run_sequence_btn.setEnabled(False)
        self.stop_sequence_btn.setEnabled(True)
        self.add_to_sequence_btn.setEnabled(False)
        self.delete_seq_btn.setEnabled(False)
        self.clear_seq_btn.setEnabled(False)
        self.save_seq_btn.setEnabled(False)
        self.load_seq_btn.setEnabled(False)

        # 开始执行
        self.execute_next_command()

    def execute_next_command(self):
        """执行下一条指令"""
        if not self.sequence_running:
            self.sequence_finished()
            return

        # 检查是否执行完一轮且需要循环
        if self.current_command_index >= len(self.sequence_commands):
            if self.loop_checkbox.isChecked():
                # 循环模式：重置索引，增加循环计数
                self.current_command_index = 0
                self.loop_count += 1
            else:
                # 非循环模式：结束
                self.sequence_finished()
                return

        cmd = self.sequence_commands[self.current_command_index]

        # 更新进度显示
        if self.loop_checkbox.isChecked():
            self.sequence_progress.setText(
                f"执行中: 第{self.loop_count + 1}轮 {self.current_command_index + 1}/{len(self.sequence_commands)}"
            )
        else:
            self.sequence_progress.setText(
                f"执行中: {self.current_command_index + 1}/{len(self.sequence_commands)}"
            )
        self.sequence_progress.setStyleSheet(
            "color: #007AFF; font-size: 13px; font-weight: 600;"
        )

        try:
            self.arm.move_joints(
                cmd["servo_data"],
                duration=cmd["run_time"],
                acceleration_ms=100,
                deceleration_ms=100,
                power_mw=10000,
            )
        except Exception as e:
            print(f"发送同步指令失败: {e}")

        # 更新滑块位置（如果有）
        for servo_id, offset_angle in cmd["servo_data"].items():
            if servo_id in self.servo_sliders:
                self.servo_sliders[servo_id].setValue(int(offset_angle))

        # 等待 run_time + wait_time
        total_wait = int((cmd["run_time"] + cmd["wait_time"]) * 1000)
        self.current_command_index += 1
        self.waiting_timer.start(total_wait)

    def stop_sequence(self):
        """停止顺序执行"""
        self.sequence_running = False
        if self.waiting_timer:
            self.waiting_timer.stop()
        if self.connected:
            try:
                self.arm.stop()
            except Exception as e:
                self.status_bar.showMessage(f"停止机械臂失败: {e}")
        self.sequence_finished()

    def sequence_finished(self):
        """顺序执行完成"""
        self.run_sequence_btn.setEnabled(True)
        self.stop_sequence_btn.setEnabled(False)
        self.add_to_sequence_btn.setEnabled(True)
        self.delete_seq_btn.setEnabled(True)
        self.clear_seq_btn.setEnabled(True)
        self.save_seq_btn.setEnabled(True)
        self.load_seq_btn.setEnabled(True)

        if not self.sequence_running:
            self.sequence_progress.setText("已停止")
            self.sequence_progress.setStyleSheet(
                "color: #FF3B30; font-size: 13px; font-weight: 600;"
            )
            self.status_bar.showMessage("顺序执行已停止")
        else:
            self.sequence_progress.setText("完成")
            self.sequence_progress.setStyleSheet(
                "color: #34C759; font-size: 13px; font-weight: 600;"
            )
            self.status_bar.showMessage("顺序执行完成")

    def add_to_sequence(self):
        """将当前滑块数据添加到顺序执行"""
        if not self.found_servos:
            return

        # 弹出对话框输入 runTime 和 wait
        dialog = QDialog(self)
        dialog.setWindowTitle("添加到顺序执行")
        dialog.setMinimumWidth(300)
        dialog.setStyleSheet("""
            QDialog {
                background-color: rgb(242, 242, 247);
            }
            QLabel {
                color: rgb(28, 28, 30);
                font-size: 14px;
                font-weight: 500;
            }
            QDoubleSpinBox {
                background-color: white;
                border: 2px solid rgba(0, 122, 255, 0.2);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
            }
            QDoubleSpinBox:focus {
                border: 2px solid #007AFF;
            }
        """)

        layout = QFormLayout(dialog)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        run_time_spin = QDoubleSpinBox()
        run_time_spin.setRange(0.1, 999.0)
        run_time_spin.setValue(1.0)
        run_time_spin.setSingleStep(0.1)
        run_time_spin.setDecimals(1)
        run_time_spin.setSuffix(" s")

        wait_spin = QDoubleSpinBox()
        wait_spin.setRange(0.1, 999.0)
        wait_spin.setValue(1.0)
        wait_spin.setSingleStep(0.1)
        wait_spin.setDecimals(1)
        wait_spin.setSuffix(" s")

        layout.addRow("运行时间:", run_time_spin)
        layout.addRow("等待时间:", wait_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 24px;
                font-weight: 600;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton:pressed {
                background-color: #0056CC;
            }
            QPushButton[text="取消"] {
                background-color: #8E8E93;
            }
            QPushButton[text="取消"]:hover {
                background-color: #AEAEB2;
            }
        """)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # 构建指令字符串
        parts = []
        for servo_id in sorted(self.found_servos):
            if servo_id in self.servo_sliders:
                value = self.servo_sliders[servo_id].value()
                parts.append(f"ID{servo_id}={value}")

        parts.append(f"runTime={run_time_spin.value()}s")
        parts.append(f"wait={wait_spin.value()}s")

        cmd_str = ",".join(parts)

        # 添加到列表
        self.sequence_list.addItem(cmd_str)

        # 选中新添加的行
        new_row = self.sequence_list.count()
        self.sequence_list.setCurrentRow(new_row - 1)

        self.status_bar.showMessage("已添加到顺序执行")

    def save_sequence_file(self):
        """保存顺序执行指令到文件"""
        if self.sequence_list.count() == 0:
            self.status_bar.showMessage("没有内容可保存")
            return

        # 收集所有行
        lines = []
        for i in range(self.sequence_list.count()):
            lines.append(self.sequence_list.item(i).text())

        content = "\n".join(lines)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存顺序指令", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.status_bar.showMessage(f"已保存到: {os.path.basename(file_path)}")
            except Exception as e:
                self.status_bar.showMessage(f"保存失败: {str(e)}")

    def load_sequence_file(self):
        """从文件读取顺序执行指令"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "读取顺序指令", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # 清空列表并添加新行
                self.sequence_list.clear()
                lines = content.split("\n")
                for line in lines:
                    if line.strip():
                        self.sequence_list.addItem(line.strip())

                self.status_bar.showMessage(f"已读取: {os.path.basename(file_path)}")
            except Exception as e:
                self.status_bar.showMessage(f"读取失败: {str(e)}")

    def delete_sequence_row(self):
        """删除选中的行"""
        current_row = self.sequence_list.currentRow()
        if current_row >= 0:
            self.sequence_list.takeItem(current_row)
            self.status_bar.showMessage(f"已删除第 {current_row + 1} 行")

            # 如果删除后还有行，选中上一行或第一行
            if self.sequence_list.count() > 0:
                new_row = min(current_row, self.sequence_list.count() - 1)
                self.sequence_list.setCurrentRow(new_row)
        else:
            self.status_bar.showMessage("请先选择要删除的行")

    def clear_sequence(self):
        """清空所有指令"""
        self.sequence_list.clear()
        self.status_bar.showMessage("已清空所有指令")

    # ==================== 快捷键功能 ====================

    def load_shortcuts(self):
        """加载快捷键配置"""
        if os.path.exists(SHORTCUT_FILE):
            try:
                with open(SHORTCUT_FILE, "r", encoding="utf-8") as f:
                    self.shortcuts = json.load(f)
            except:
                self.shortcuts = DEFAULT_SHORTCUTS.copy()
        else:
            self.shortcuts = DEFAULT_SHORTCUTS.copy()

    def save_shortcuts(self):
        """保存快捷键配置"""
        try:
            with open(SHORTCUT_FILE, "w", encoding="utf-8") as f:
                json.dump(self.shortcuts, f, ensure_ascii=False, indent=2)
            self.status_bar.showMessage("快捷键配置已保存")
        except Exception as e:
            self.status_bar.showMessage(f"保存快捷键失败: {str(e)}")

    def on_shortcut_toggled(self, state):
        """快捷键开关状态变化"""
        self.shortcut_enabled = state == Qt.CheckState.Checked.value

        if self.shortcut_enabled:
            if not self.connected:
                self.status_bar.showMessage("请先连接串口")
                self.shortcut_checkbox.setChecked(False)
                self.shortcut_enabled = False
                return

            # 禁用所有拖动条
            for servo_id, slider in self.servo_sliders.items():
                slider.setEnabled(False)

            # 启动键盘监控线程
            self.start_keyboard_monitor()
            self.status_bar.showMessage("快捷键已启用，拖动条已锁定")
        else:
            # 停止键盘监控线程
            self.stop_keyboard_monitor()

            # 启用所有拖动条
            for servo_id, slider in self.servo_sliders.items():
                slider.setEnabled(True)

            self.status_bar.showMessage("快捷键已禁用，拖动条已解锁")

    def on_shortcut_step_changed(self, value):
        """步长变化"""
        self.shortcut_step = value

    def on_shortcut_period_changed(self, value):
        """周期变化"""
        self.shortcut_period = value

    def start_keyboard_monitor(self):
        """启动键盘监控线程"""
        if self.keyboard_thread and self.keyboard_thread.isRunning():
            return

        self.keyboard_thread = KeyboardMonitorThread()
        self.keyboard_thread.key_pressed.connect(self.on_key_pressed)
        self.keyboard_thread.key_released.connect(self.on_key_released)
        self.keyboard_thread.start()

    def stop_keyboard_monitor(self):
        """停止键盘监控线程"""
        if self.keyboard_thread:
            self.keyboard_thread.stop()
            self.keyboard_thread.wait()
            self.keyboard_thread = None

        # 停止所有长按定时器
        for timer in self.long_press_timers.values():
            timer.stop()
        self.long_press_timers.clear()

    def on_key_pressed(self, key_name):
        """处理按键事件（包括长按）"""
        if not self.shortcut_enabled or not self.connected:
            return

        # 查找匹配的快捷键
        servo_id = None
        direction = 0

        for key, value in self.shortcuts.items():
            if value == key_name:
                if "_plus" in key:
                    servo_id = int(key.split("_")[1])
                    direction = 1
                elif "_minus" in key:
                    servo_id = int(key.split("_")[1])
                    direction = -1
                break

        if servo_id and direction != 0:
            # 处理单次按键
            self.handle_shortcut_command(servo_id, direction)

            # 设置长按定时器（首次延迟300ms，之后按周期发送）
            if key_name not in self.long_press_timers:
                timer = QTimer()
                timer.setInterval(self.shortcut_period)  # 长按期间按设置的周期发送
                timer.timeout.connect(
                    lambda id=servo_id, dir=direction, kn=key_name: self.handle_long_press(
                        id, dir, kn
                    )
                )
                self.long_press_timers[key_name] = timer
                # 首次长按延迟300ms后开始连续发送
                QTimer.singleShot(300, timer.start)

    def on_key_released(self, key_name):
        """处理按键释放事件"""
        # 停止长按定时器
        if key_name in self.long_press_timers:
            self.long_press_timers[key_name].stop()
            del self.long_press_timers[key_name]

    def handle_long_press(self, servo_id, direction, key_name):
        """处理长按事件 - 每500ms发送一次新的角度"""
        # 检查按键是否仍然按下
        if self.keyboard_thread and self.keyboard_thread.is_key_down(key_name):
            self.handle_shortcut_command(servo_id, direction)

    def handle_shortcut_command(self, servo_id, direction):
        """处理快捷键指令"""
        if servo_id not in self.servo_sliders:
            return

        slider = self.servo_sliders[servo_id]
        current_value = slider.value()
        new_value = current_value + direction * self.shortcut_step

        # 限制在 -175 到 175 范围内
        new_value = max(-175, min(175, new_value))

        # 只有当值确实变化时才更新和发送命令
        if new_value != current_value:
            # 更新滑块
            slider.setValue(new_value)

            # 发送同步控制命令
            self.send_shortcut_sync_command(servo_id, new_value)

    def send_shortcut_sync_command(self, servo_id, target_offset):
        """发送快捷键同步控制命令"""
        if not self.connected:
            return

        try:
            interval = self.shortcut_period
            ramp = max(20, interval // 4)
            self.arm.move_joints(
                {servo_id: target_offset},
                duration=interval / 1000.0,
                acceleration_ms=ramp,
                deceleration_ms=ramp,
                power_mw=15000,
            )

            self.status_bar.showMessage(f"舵机 {servo_id}: {target_offset}°")
        except Exception as e:
            print(f"发送快捷键命令失败: {e}")

    def show_shortcut_config(self):
        """显示快捷键配置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("配置快捷键")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: rgb(242, 242, 247);
            }
            QLabel {
                color: rgb(28, 28, 30);
                font-size: 14px;
                font-weight: 500;
            }
            QLineEdit {
                background-color: white;
                border: 2px solid rgba(0, 122, 255, 0.2);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #007AFF;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        # 创建表格布局
        grid_layout = QGridLayout()
        grid_layout.setSpacing(12)

        # 表头
        header_label = QLabel("舵机ID")
        header_label.setStyleSheet("font-weight: 600; color: rgb(134, 134, 139);")
        grid_layout.addWidget(header_label, 0, 0)

        plus_header = QLabel("增加 (+)")
        plus_header.setStyleSheet("font-weight: 600; color: rgb(52, 199, 89);")
        grid_layout.addWidget(plus_header, 0, 1)

        minus_header = QLabel("减小 (-)")
        minus_header.setStyleSheet("font-weight: 600; color: rgb(255, 59, 48);")
        grid_layout.addWidget(minus_header, 0, 2)

        row = 1

        # 只显示扫描到的舵机ID
        servo_ids_to_show = (
            sorted(self.found_servos) if self.found_servos else range(1, 5)
        )

        for servo_id in servo_ids_to_show:
            # 舵机ID标签
            id_label = QLabel(f"ID {servo_id}")
            id_label.setStyleSheet("font-weight: 600;")
            grid_layout.addWidget(id_label, row, 0)

            # 增加快捷键 - 使用按键捕获模式
            plus_edit = QLineEdit()
            plus_edit.setText(self.shortcuts.get(f"servo_{servo_id}_plus", ""))
            plus_edit.setPlaceholderText("点击设置")
            plus_edit.setObjectName(f"plus_{servo_id}")
            plus_edit.setReadOnly(True)
            plus_edit.mousePressEvent = lambda event, edit=plus_edit, sid=servo_id, typ="plus": self.on_shortcut_edit_clicked(
                event, edit, sid, typ
            )
            plus_edit.setStyleSheet("""
                QLineEdit {
                    background-color: white;
                    border: 2px solid rgba(52, 199, 89, 0.3);
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 14px;
                    cursor: pointer;
                }
                QLineEdit:focus {
                    border: 2px solid #34C759;
                    background-color: rgba(52, 199, 89, 0.05);
                }
                QLineEdit[text=""] {
                    color: rgb(134, 134, 139);
                }
            """)
            grid_layout.addWidget(plus_edit, row, 1)

            # 减小快捷键 - 使用按键捕获模式
            minus_edit = QLineEdit()
            minus_edit.setText(self.shortcuts.get(f"servo_{servo_id}_minus", ""))
            minus_edit.setPlaceholderText("点击设置")
            minus_edit.setObjectName(f"minus_{servo_id}")
            minus_edit.setReadOnly(True)
            minus_edit.mousePressEvent = lambda event, edit=minus_edit, sid=servo_id, typ="minus": self.on_shortcut_edit_clicked(
                event, edit, sid, typ
            )
            minus_edit.setStyleSheet("""
                QLineEdit {
                    background-color: white;
                    border: 2px solid rgba(255, 59, 48, 0.3);
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 14px;
                    cursor: pointer;
                }
                QLineEdit:focus {
                    border: 2px solid #FF3B30;
                    background-color: rgba(255, 59, 48, 0.05);
                }
                QLineEdit[text=""] {
                    color: rgb(134, 134, 139);
                }
            """)
            grid_layout.addWidget(minus_edit, row, 2)

            row += 1

        # 当前正在监听的输入框
        self.current_listening_edit = None
        self.current_listening_servo_id = None
        self.current_listening_type = None

        layout.addLayout(grid_layout)

        # 重置按钮
        reset_btn = QPushButton("重置为默认")
        reset_btn.setFixedHeight(36)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FFB340;
            }
        """)
        reset_btn.clicked.connect(lambda: self.reset_shortcuts(dialog))
        layout.addWidget(reset_btn)

        # 确定/取消按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 24px;
                font-weight: 600;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #5AC8FA;
            }
            QPushButton[text="取消"] {
                background-color: #8E8E93;
            }
        """)

        buttons.accepted.connect(lambda: self.save_shortcut_config(dialog))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def on_shortcut_edit_clicked(self, event, edit, servo_id, edit_type):
        """点击快捷键输入框时开始监听按键"""
        # 如果已经在监听，先取消之前的监听
        if self.current_listening_edit:
            self.current_listening_edit.setText(
                self.shortcuts.get(
                    f"servo_{self.current_listening_servo_id}_{self.current_listening_type}",
                    "",
                )
            )
            self.current_listening_edit.setStyleSheet("""
                QLineEdit {
                    background-color: white;
                    border: 2px solid rgba(52, 199, 89, 0.3);
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 14px;
                    cursor: pointer;
                }
            """)

        # 设置当前监听状态
        self.current_listening_edit = edit
        self.current_listening_servo_id = servo_id
        self.current_listening_type = edit_type

        # 设置监听状态样式
        edit.setText("...")
        edit.setStyleSheet("""
            QLineEdit {
                background-color: rgba(0, 122, 255, 0.1);
                border: 2px dashed #007AFF;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
                color: #007AFF;
                font-weight: 600;
            }
        """)

        # 启动按键监听
        import keyboard

        keyboard.on_press(self.capture_key_for_shortcut)

    def capture_key_for_shortcut(self, event):
        """捕获按键并设置到当前输入框"""
        if not self.current_listening_edit:
            return

        try:
            key_name = event.name
            # 处理特殊键名
            if len(key_name) == 1:
                key_name = f"Key_{key_name.upper()}"
            elif key_name in ["space", "enter", "backspace", "tab"]:
                key_name = f"Key_{key_name.capitalize()}"

            # 设置按键名到输入框
            self.current_listening_edit.setText(key_name)

            # 保存到临时配置
            self.shortcuts[
                f"servo_{self.current_listening_servo_id}_{self.current_listening_type}"
            ] = key_name

            # 恢复输入框样式
            self.current_listening_edit.setStyleSheet("""
                QLineEdit {
                    background-color: white;
                    border: 2px solid rgba(52, 199, 89, 0.3);
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 14px;
                    cursor: pointer;
                }
            """)

            # 清除监听状态
            import keyboard

            keyboard.unhook_all()
            self.current_listening_edit = None
            self.current_listening_servo_id = None
            self.current_listening_type = None

        except Exception as e:
            print(f"捕获按键失败: {e}")

    def reset_shortcuts(self, dialog):
        """重置快捷键为默认值"""
        servo_ids_to_reset = (
            sorted(self.found_servos) if self.found_servos else range(1, 5)
        )
        for servo_id in servo_ids_to_reset:
            plus_edit = dialog.findChild(QLineEdit, f"plus_{servo_id}")
            minus_edit = dialog.findChild(QLineEdit, f"minus_{servo_id}")
            if plus_edit:
                plus_edit.setText(DEFAULT_SHORTCUTS.get(f"servo_{servo_id}_plus", ""))
            if minus_edit:
                minus_edit.setText(DEFAULT_SHORTCUTS.get(f"servo_{servo_id}_minus", ""))

    def save_shortcut_config(self, dialog):
        """保存快捷键配置"""
        servo_ids_to_save = (
            sorted(self.found_servos) if self.found_servos else range(1, 5)
        )
        for servo_id in servo_ids_to_save:
            plus_edit = dialog.findChild(QLineEdit, f"plus_{servo_id}")
            minus_edit = dialog.findChild(QLineEdit, f"minus_{servo_id}")
            if plus_edit:
                self.shortcuts[f"servo_{servo_id}_plus"] = plus_edit.text()
            if minus_edit:
                self.shortcuts[f"servo_{servo_id}_minus"] = minus_edit.text()

        self.save_shortcuts()
        dialog.accept()

    def closeEvent(self, event):
        self.stop_monitoring()
        self.stop_sequence()
        self.stop_keyboard_monitor()
        # 停止所有定时器
        for data in self.slider_data.values():
            if data["timer"]:
                data["timer"].stop()
        self.slider_data.clear()
        if self.arm.connected:
            self.arm.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)

    window = ServoControlGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
