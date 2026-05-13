#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fashion Star 总线伺服舵机 - iOS风格现代化GUI界面
清新、简洁、精致的设计
"""

import sys
import time
import sys
import os
import json
import struct
import serial
import serial.tools.list_ports
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSplitter,
    QStatusBar, QProgressBar, QFrame, QScrollArea, QTabWidget,
    QDoubleSpinBox, QSpinBox, QSlider, QTextEdit, QFileDialog,
    QDialog, QFormLayout, QDialogButtonBox, QListWidget,
    QListWidgetItem, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QMimeData
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QBrush, QPen, QDrag

try:
    import fashionstar_uart_sdk as uservo
except ImportError:
    uservo = None
    print("提示: fashionstar_uart_sdk 未安装，部分功能不可用")


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
            self.parent_gui.status_bar.showMessage(f"已重新排序，当前第 {current_row + 1} 行")


class ServoScannerThread(QThread):
    """舵机扫描线程"""
    progress = pyqtSignal(int, int)
    found = pyqtSignal(int)
    finished = pyqtSignal(list)
    serial_error = pyqtSignal()

    def __init__(self, servo_manager, start_id=0, end_id=30):
        super().__init__()
        self.servo_manager = servo_manager
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
                is_online = self.servo_manager.ping(servo_id)
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

    def __init__(self, servo_manager, servo_ids):
        super().__init__()
        self.servo_manager = servo_manager
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
            angle = self.servo_manager.query_servo_angle(servo_id)
        except:
            angle = None
            self.error_count += 1
        
        try:
            voltage = self.servo_manager.query_voltage(servo_id)
            current = self.servo_manager.query_current(servo_id)
            power = self.servo_manager.query_power(servo_id)
            temp = self.servo_manager.query_temperature(servo_id)
            status = self.servo_manager.query_status(servo_id)
        except:
            voltage = current = power = temp = status = None
            self.error_count += 1

        return {
            'id': servo_id,
            'angle': angle,
            'voltage': voltage,
            'current': current,
            'power': power,
            'temp': temp,
            'status': status
        }


class SyncMonitorThread(QThread):
    """同步监控线程（高效方式）"""
    all_info_ready = pyqtSignal(dict)  # 发送所有舵机的信息
    finished = pyqtSignal()
    serial_error = pyqtSignal()

    def __init__(self, servo_manager, servo_ids):
        super().__init__()
        self.servo_manager = servo_manager
        self.servo_ids = servo_ids
        self.error_count = 0
        self.max_errors = 3

    def run(self):
        try:
            # 使用同步监控命令一次性获取所有舵机数据
            servo_monitor_data = self.servo_manager.send_sync_servo_monitor(self.servo_ids)
            
            # 转换所有数据格式
            result_dict = {}
            for servo_id, info in servo_monitor_data.items():
                if info:
                    result_dict[servo_id] = {
                        'id': servo_id,
                        'angle': info.angle_monitor,
                        'turn': info.turn,
                        'power': info.power / 1000.0 if info.power is not None else None,
                        'temp': info.temp
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
            painter.setBrush(QBrush(QColor(self.color.red(), self.color.green(), self.color.blue(), 30)))
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
        self.servo_manager: Optional[uservo.UartServoManager] = None
        self.uart: Optional[serial.Serial] = None
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
        
        self.init_ui()
        self.refresh_ports()

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
        panel.setStyleSheet("background-color: rgb(255, 255, 255); border-right: 1px solid rgba(0, 0, 0, 0.08);")
        
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
        port_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 12px; font-weight: 600;")
        port_sub_layout.addWidget(port_label)
        
        self.port_combo = QComboBox()
        port_sub_layout.addWidget(self.port_combo)
        port_layout.addLayout(port_sub_layout)
        
        # 波特率选择
        baud_sub_layout = QVBoxLayout()
        baud_sub_layout.setSpacing(6)
        baud_label = QLabel("波特率")
        baud_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 12px; font-weight: 600;")
        baud_sub_layout.addWidget(baud_label)
        
        self.baud_combo = QComboBox()
        self.baud_combo.addItems([
            "9600", "19200", "38400", "57600", "115200",
            "230400", "460800", "500000", "576000", "921600", "1000000"
        ])
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
        scan_title.setStyleSheet("color: rgb(28, 28, 30); font-size: 16px; font-weight: 700; padding-bottom: 4px;")
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
        table_title.setStyleSheet("color: rgb(28, 28, 30); font-size: 18px; font-weight: 700;")
        header_layout.addWidget(table_title)
        
        header_layout.addStretch()
        
        self.monitoring_label = QLabel("监控状态: 等待扫描")
        self.monitoring_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;")
        header_layout.addWidget(self.monitoring_label)
        
        layout.addLayout(header_layout)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "ID", "角度", "多圈角度", "功率", "温度"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        select_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;")
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
        angle_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 600;")
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
        speed_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 14px; font-weight: 600;")
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
        right_title.setStyleSheet("color: rgb(28, 28, 30); font-size: 18px; font-weight: 700;")
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
        self.sequence_progress.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;")
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
            self.uart = serial.Serial(
                port=port,
                baudrate=baudrate,
                parity=serial.PARITY_NONE,
                stopbits=1,
                bytesize=8,
                timeout=0.1
            )
            self.servo_manager = uservo.UartServoManager(self.uart, is_debug=False)
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
        if self.uart and self.uart.is_open:
            self.uart.close()
        
        # 停止所有拖动条定时器
        for data in self.slider_data.values():
            if data['timer']:
                data['timer'].stop()
        self.slider_data.clear()
        
        self.servo_manager = None
        self.connected = False
        self.found_servos = []
        self.last_servo_data = {}
        self.stop_monitoring()
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
        self.monitoring_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;")
        
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
        
        self.scanner_thread = ServoScannerThread(self.servo_manager, 0, 100)
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
        id_label.setStyleSheet("color: rgb(28, 28, 30); font-size: 16px; font-weight: 700; min-width: 70px;")
        layout.addWidget(id_label)
        
        # 滑块
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-90, 90)
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
        angle_label.setStyleSheet("color: rgb(0, 122, 255); font-size: 16px; font-weight: 700; min-width: 60px;")
        angle_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(angle_label)
        
        # 连接信号
        slider.sliderPressed.connect(lambda: self.on_slider_pressed(servo_id, angle_label))
        slider.sliderReleased.connect(lambda: self.on_slider_released(servo_id))
        slider.valueChanged.connect(lambda value: self.on_slider_value_changed(servo_id, value, angle_label))
        
        return card, slider

    def on_speed_changed(self, value):
        """速度设置变化时更新"""
        self.servo_speed = value

    def on_slider_pressed(self, servo_id, angle_label):
        """滑块按下时开始定时发送"""
        slider = self.servo_sliders[servo_id]
        current_value = slider.value()
        
        self.slider_data[servo_id] = {
            'timer': QTimer(),
            'current_value': current_value,
            'release_count': 0,
            'is_dragging': True,
            'angle_label': angle_label
        }
        
        data = self.slider_data[servo_id]
        data['timer'].timeout.connect(lambda: self.send_servo_command(servo_id))
        data['timer'].start(100)
        
        # 立即发送一次
        self.send_servo_command(servo_id)

    def on_slider_value_changed(self, servo_id, value, angle_label):
        """滑块值变化时更新显示和记录"""
        angle_label.setText(f"{value}°")
        if servo_id in self.slider_data:
            self.slider_data[servo_id]['current_value'] = value

    def on_slider_released(self, servo_id):
        """滑块松开时标记状态"""
        if servo_id in self.slider_data:
            self.slider_data[servo_id]['is_dragging'] = False
            self.slider_data[servo_id]['release_count'] = 0

    def send_servo_command(self, servo_id):
        """发送舵机命令"""
        if servo_id not in self.slider_data:
            return
        
        data = self.slider_data[servo_id]
        
        if self.connected and self.servo_manager:
            try:
                # 零偏角度 + 拖动条数值
                offset = self.servo_offsets.get(servo_id, 0.0)
                target_angle = offset + data['current_value']
                self.servo_manager.set_servo_angle(servo_id, target_angle, is_mturn=True, velocity=self.servo_speed)
            except Exception as e:
                pass
        
        # 处理松开后的发送逻辑
        if not data['is_dragging']:
            data['release_count'] += 1
            if data['release_count'] >= 3:
                # 发送3次后停止
                data['timer'].stop()
                del self.slider_data[servo_id]

    def reset_all_servos(self):
        """将所有舵机归零（回到零偏角度）"""
        if not self.connected or not self.servo_manager:
            return
        
        # 先停止所有正在进行的拖动
        for data in self.slider_data.values():
            if data['timer']:
                data['timer'].stop()
        self.slider_data.clear()
        
        # 将所有滑块设为0，并发送命令
        for servo_id, slider in self.servo_sliders.items():
            slider.setValue(0)
            # 直接发送归零命令
            try:
                offset = self.servo_offsets.get(servo_id, 0.0)
                target_angle = offset  # 滑块值为0时 = 零偏角度
                self.servo_manager.set_servo_angle(servo_id, target_angle, is_mturn=True, velocity=self.servo_speed)
            except Exception as e:
                pass
        
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
                
                with open(self.offset_file, 'r', encoding='utf-8') as f:
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
                
                self.status_bar.showMessage(f"已加载零偏文件: {len(self.servo_offsets)} 个舵机")
            except json.JSONDecodeError:
                self.status_bar.showMessage("零偏文件格式损坏")
                self.servo_offsets = {}
            except Exception as e:
                self.status_bar.showMessage(f"加载零偏失败: {str(e)}")
                self.servo_offsets = {}
        else:
            self.servo_offsets = {}
            self.status_bar.showMessage("零偏文件不存在")

    def save_offsets(self):
        """保存当前角度为零偏（使用表格显示的数据）"""
        if not self.connected or not self.servo_manager:
            self.status_bar.showMessage("请先连接串口")
            return
        
        try:
            # 使用最近一次刷新时表格显示的角度作为零偏
            for servo_id in self.found_servos:
                if servo_id in self.last_servo_data:
                    info = self.last_servo_data[servo_id]
                    angle = info['angle']
                    if angle is not None:
                        self.servo_offsets[servo_id] = angle
                        print(f"舵机 {servo_id} 保存角度: {angle}")
            
            # 保存到文件
            with open(self.offset_file, 'w', encoding='utf-8') as f:
                json.dump(self.servo_offsets, f, ensure_ascii=False, indent=2)
            
            print(f"保存的零偏数据: {self.servo_offsets}")
            self.status_bar.showMessage(f"已保存零偏: {len(self.servo_offsets)} 个舵机")
        except Exception as e:
            self.status_bar.showMessage(f"保存零偏失败: {str(e)}")

    def clear_sync_controls(self):
        """清空同步控制区域的所有控件"""
        # 停止所有定时器
        for data in self.slider_data.values():
            if data['timer']:
                data['timer'].stop()
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
        
        # 填充舵机选择下拉框
        self.servo_select_combo.clear()
        for servo_id in self.found_servos:
            self.servo_select_combo.addItem(f"舵机 {servo_id}", servo_id)
        
        # 创建同步控制滑块
        self.clear_sync_controls()
        for servo_id in self.found_servos:
            card, slider = self.create_servo_slider(servo_id)
            # 在stretch之前插入
            self.sync_control_layout.insertWidget(self.sync_control_layout.count() - 1, card)
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
            QTimer.singleShot(500, lambda: self.start_monitoring() if len(found) > 0 else None)

    def refresh_servo_info(self):
        if not self.connected or not self.found_servos:
            return
        
        if self.info_thread and self.info_thread.isRunning():
            return
        
        self.info_thread = SyncMonitorThread(self.servo_manager, self.found_servos)
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
                    for col, value in enumerate([
                        f"{info['angle']:.1f}" if info['angle'] is not None else "—",
                        f"{info['turn']:.1f}" if info['turn'] is not None else "—",
                        f"{info['power']:.2f}" if info['power'] is not None else "—",
                        str(info['temp']) if info['temp'] is not None else "—"
                    ], start=1):
                        cell_item = QTableWidgetItem(value)
                        cell_item.setFlags(cell_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, col, cell_item)

    def on_info_finished(self):
        self.status_bar.showMessage("信息已更新")

    def start_monitoring(self):
        self.monitoring = True
        self.monitoring_label.setText("监控状态: 运行中")
        self.monitoring_label.setStyleSheet("color: rgb(52, 199, 89); font-size: 13px; font-weight: 600;")
        
        self.refresh_timer.start(500)
        self.status_bar.showMessage("持续监控已启动: 每 500ms")

    def stop_monitoring(self):
        self.monitoring = False
        if self.refresh_timer.isActive():
            self.refresh_timer.stop()
        self.monitoring_label.setText("监控状态: 已停止")
        self.monitoring_label.setStyleSheet("color: rgb(134, 134, 139); font-size: 13px; font-weight: 500;")

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
            self.servo_manager.set_servo_angle(servo_id, target_angle, is_mturn=True)
            self.status_bar.showMessage(f"已设置舵机 {servo_id} 角度为 {target_angle}° (多圈模式)")
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
            self.servo_manager.set_damping(servo_id, power)
            self.status_bar.showMessage(f"已设置舵机 {servo_id} 阻尼功率为 {power}mW")
        except Exception as e:
            self.status_bar.showMessage(f"设置阻尼失败: {str(e)}")

    def parse_sequence_line(self, line):
        """解析一条顺序执行指令"""
        line = line.strip()
        if not line:
            return None
        
        parts = line.split(',')
        servo_data = {}
        run_time = 1.0
        wait_time = 0.0
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            if '=' in part:
                key, value = part.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key.startswith('ID'):
                    try:
                        servo_id = int(key[2:])
                        angle = float(value)
                        servo_data[servo_id] = angle
                    except ValueError:
                        continue
                elif key == 'runTime':
                    try:
                        run_time = float(value.replace('s', ''))
                    except ValueError:
                        run_time = 1.0
                elif key == 'wait':
                    try:
                        wait_time = float(value.replace('s', ''))
                    except ValueError:
                        wait_time = 0.0
        
        if not servo_data:
            return None
        
        return {
            'servo_data': servo_data,
            'run_time': max(0.1, run_time),
            'wait_time': max(0.1, wait_time)
        }
    
    def on_sequence_item_clicked(self, item):
        """点击列表项时的处理 - 同步拖动条并控制舵机"""
        row = self.sequence_list.row(item) + 1
        
        # 解析当前行的指令
        line_text = item.text()
        cmd = self.parse_sequence_line(line_text)
        
        if cmd and 'servo_data' in cmd:
            # 同步每个舵机的拖动条并发送控制指令
            for servo_id, offset_value in cmd['servo_data'].items():
                if servo_id in self.servo_sliders:
                    self.servo_sliders[servo_id].setValue(int(offset_value))
                
                # 发送控制指令到舵机
                if self.connected and self.servo_manager:
                    zero_offset = self.servo_offsets.get(servo_id, 0.0)
                    target_angle = zero_offset + offset_value
                    try:
                        self.servo_manager.set_servo_angle(
                            servo_id,
                            target_angle,
                            is_mturn=True,
                            velocity=self.servo_speed_spin.value()
                        )
                    except Exception as e:
                        print(f"控制舵机 {servo_id} 失败: {e}")
        
        self.status_bar.showMessage(f"已选择第 {row} 行")
    
    def run_sequence(self):
        """开始执行顺序指令"""
        if not self.connected or not self.servo_manager:
            self.status_bar.showMessage("请先连接串口")
            return
        
        # 先停止所有正在进行的拖动
        for data in self.slider_data.values():
            if data['timer']:
                data['timer'].stop()
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
        self.sequence_progress.setStyleSheet("color: #007AFF; font-size: 13px; font-weight: 600;")
        
        # 准备同步指令数据
        command_data_list = []
        t_acc = 100  # 启动加速时间 (ms)
        t_dec = 100  # 运动减速时间 (ms)
        power = 10000  # 功率 (mW)
        
        for servo_id, offset_angle in cmd['servo_data'].items():
            zero_offset = self.servo_offsets.get(servo_id, 0.0)
            target_angle = zero_offset + offset_angle
            interval = int(cmd['run_time'] * 1000)
            
            # 使用 struct.pack 打包数据，格式: '<BlLHHH'
            packed_data = struct.pack(
                '<BlLHHH',
                servo_id,
                int(target_angle * 10),  # 角度需要放大10倍
                interval,
                t_acc,
                t_dec,
                power
            )
            command_data_list.append(packed_data)
        
        # 发送同步指令
        try:
            self.servo_manager.send_sync_multiturnanglebyinterval(
                command_id=14,
                servo_num=len(command_data_list),
                command_data_list=command_data_list
            )
        except Exception as e:
            print(f"发送同步指令失败: {e}")
        
        # 更新滑块位置（如果有）
        for servo_id, offset_angle in cmd['servo_data'].items():
            if servo_id in self.servo_sliders:
                self.servo_sliders[servo_id].setValue(int(offset_angle))
        
        # 等待 run_time + wait_time
        total_wait = int((cmd['run_time'] + cmd['wait_time']) * 1000)
        self.current_command_index += 1
        self.waiting_timer.start(total_wait)
    
    def stop_sequence(self):
        """停止顺序执行"""
        self.sequence_running = False
        if self.waiting_timer:
            self.waiting_timer.stop()
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
            self.sequence_progress.setStyleSheet("color: #FF3B30; font-size: 13px; font-weight: 600;")
            self.status_bar.showMessage("顺序执行已停止")
        else:
            self.sequence_progress.setText("完成")
            self.sequence_progress.setStyleSheet("color: #34C759; font-size: 13px; font-weight: 600;")
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
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
        
        content = '\n'.join(lines)
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存顺序指令",
            "",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.status_bar.showMessage(f"已保存到: {os.path.basename(file_path)}")
            except Exception as e:
                self.status_bar.showMessage(f"保存失败: {str(e)}")
    
    def load_sequence_file(self):
        """从文件读取顺序执行指令"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "读取顺序指令",
            "",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 清空列表并添加新行
                self.sequence_list.clear()
                lines = content.split('\n')
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
    
    def closeEvent(self, event):
        self.stop_monitoring()
        self.stop_sequence()
        # 停止所有定时器
        for data in self.slider_data.values():
            if data['timer']:
                data['timer'].stop()
        self.slider_data.clear()
        if self.uart and self.uart.is_open:
            self.uart.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    window = ServoControlGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
