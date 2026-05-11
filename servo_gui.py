#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fashion Star 总线伺服舵机 - iOS风格现代化GUI界面
清新、简洁、精致的设计
"""

import sys
import time
import serial
import serial.tools.list_ports
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSplitter,
    QStatusBar, QProgressBar, QFrame, QScrollArea, QTabWidget,
    QDoubleSpinBox, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QBrush, QPen

try:
    import fashionstar_uart_sdk as uservo
except ImportError:
    print("警告: fashionstar_uart_sdk 未安装")


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
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedHeight(40)
        refresh_btn.setStyleSheet("""
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
        """)
        refresh_btn.clicked.connect(self.refresh_ports)
        btn_layout.addWidget(refresh_btn)
        
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
        
        self.servo_manager = None
        self.connected = False
        self.found_servos = []
        self.stop_monitoring()
        
        # 重新启用串口和波特率选择，禁用控制功能
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.scan_btn.setEnabled(False)
        self.servo_select_combo.clear()
        self.servo_select_combo.setEnabled(False)
        self.target_angle_spin.setEnabled(False)
        self.set_angle_btn.setEnabled(False)
        self.damping_power_spin.setEnabled(False)
        self.set_damping_btn.setEnabled(False)
        
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

    def on_scan_finished(self, found):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_info.setText(f"扫描完成 - 共 {len(found)} 个舵机")
        
        # 填充舵机选择下拉框
        self.servo_select_combo.clear()
        for servo_id in self.found_servos:
            self.servo_select_combo.addItem(f"舵机 {servo_id}", servo_id)
        
        if found:
            # 启用控制功能
            self.servo_select_combo.setEnabled(True)
            self.target_angle_spin.setEnabled(True)
            self.set_angle_btn.setEnabled(True)
            
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

    def closeEvent(self, event):
        self.stop_monitoring()
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
