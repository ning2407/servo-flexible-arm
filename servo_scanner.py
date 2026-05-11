#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
总线伺服舵机扫描器
扫描总线上连接的舵机设备
"""

import sys
import time
import serial
import serial.tools.list_ports
from typing import List, Dict, Optional

try:
    import fashionstar_uart_sdk as uservo
except ImportError:
    print("警告: fashionstar_uart_sdk 未安装，请运行 'pip install fashionstar-uart-sdk'")
    sys.exit(1)


class ServoScanner:
    """舵机扫描器"""

    def __init__(self, baudrate: int = 115200, timeout: float = 0.1):
        self.baudrate = baudrate
        self.timeout = timeout
        self.servo_manager: Optional[uservo.UartServoManager] = None
        self.uart: Optional[serial.Serial] = None

    def list_serial_ports(self) -> List[Dict]:
        """列出所有可用串口"""
        ports = serial.tools.list_ports.comports()
        port_list = []
        for port in ports:
            port_info = {
                'device': port.device,
                'description': port.description,
                'hwid': port.hwid
            }
            port_list.append(port_info)
        return port_list

    def open_port(self, port: str) -> bool:
        """打开串口"""
        try:
            self.uart = serial.Serial(
                port=port,
                baudrate=self.baudrate,
                parity=serial.PARITY_NONE,
                stopbits=1,
                bytesize=8,
                timeout=self.timeout
            )
            self.servo_manager = uservo.UartServoManager(self.uart, is_debug=False)
            return True
        except Exception as e:
            print(f"打开串口失败: {e}")
            return False

    def close_port(self):
        """关闭串口"""
        if self.uart and self.uart.is_open:
            self.uart.close()
        self.servo_manager = None
        self.uart = None

    def scan_servos(self, start_id: int = 0, end_id: int = 253, delay: float = 0.02) -> List[int]:
        """扫描指定范围内的舵机ID"""
        if not self.servo_manager:
            print("错误: 串口未打开")
            return []

        print(f"正在扫描舵机 ID 范围: {start_id} ~ {end_id}")
        print("-" * 50)
        
        found_servos = []
        for servo_id in range(start_id, end_id + 1):
            try:
                is_online = self.servo_manager.ping(servo_id)
                if is_online:
                    print(f"✓ 发现舵机 ID: {servo_id}")
                    found_servos.append(servo_id)
                time.sleep(delay)
            except Exception as e:
                pass

        print("-" * 50)
        print(f"扫描完成，共发现 {len(found_servos)} 个舵机")
        if found_servos:
            print(f"舵机 ID 列表: {found_servos}")
        
        return found_servos

    def get_servo_info(self, servo_id: int) -> Dict:
        """获取单个舵机的详细信息"""
        if not self.servo_manager:
            return {}

        try:
            # 尝试查询角度
            angle = None
            try:
                angle = self.servo_manager.query_servo_angle(servo_id)
            except:
                pass

            # 尝试查询电压电流等信息
            voltage = None
            current = None
            power = None
            temp = None
            status = None
            
            try:
                voltage = self.servo_manager.query_voltage(servo_id)
                current = self.servo_manager.query_current(servo_id)
                power = self.servo_manager.query_power(servo_id)
                temp = self.servo_manager.query_temperature(servo_id)
                status = self.servo_manager.query_status(servo_id)
            except:
                pass

            return {
                'id': servo_id,
                'online': True,
                'angle': angle,
                'voltage': voltage,
                'current': current,
                'power': power,
                'temp': temp,
                'status': status
            }
        except Exception as e:
            return {
                'id': servo_id,
                'online': False,
                'error': str(e)
            }


def print_serial_ports(ports: List[Dict]):
    """打印串口列表"""
    print("\n可用串口列表:")
    print("-" * 60)
    for i, port in enumerate(ports, 1):
        print(f"{i}. {port['device']:12} - {port['description']}")
    print("-" * 60)


def main():
    scanner = ServoScanner()
    
    # 列出可用串口
    ports = scanner.list_serial_ports()
    
    if not ports:
        print("未找到可用串口，请检查硬件连接")
        return

    print_serial_ports(ports)

    # 选择串口
    port_index = 0
    if len(ports) > 1:
        try:
            choice = input(f"\n请选择串口 (1~{len(ports)}，默认为1): ").strip()
            if choice:
                port_index = int(choice) - 1
            if port_index < 0 or port_index >= len(ports):
                print("无效选择，使用默认串口")
                port_index = 0
        except:
            port_index = 0

    selected_port = ports[port_index]['device']
    print(f"\n正在打开串口: {selected_port}")

    # 打开串口
    if not scanner.open_port(selected_port):
        print("无法打开串口")
        return

    try:
        # 扫描舵机
        print("\n开始扫描舵机...")
        found_servos = scanner.scan_servos(start_id=0, end_id=30)

        # 获取详细信息
        if found_servos:
            print("\n正在获取舵机详细信息...")
            print("=" * 80)
            print(f"{'ID':<6} {'角度(°)':<10} {'电压(V)':<10} {'电流(A)':<10} {'功率(W)':<10} {'状态':<10}")
            print("-" * 80)
            
            for servo_id in found_servos:
                info = scanner.get_servo_info(servo_id)
                angle_str = f"{info['angle']:.1f}" if info['angle'] is not None else "N/A"
                volt_str = f"{info['voltage']:.2f}" if info['voltage'] is not None else "N/A"
                curr_str = f"{info['current']:.2f}" if info['current'] is not None else "N/A"
                pow_str = f"{info['power']:.2f}" if info['power'] is not None else "N/A"
                status_str = f"{info['status']:08b}" if info['status'] is not None else "N/A"
                
                print(f"{info['id']:<6} {angle_str:<10} {volt_str:<10} {curr_str:<10} {pow_str:<10} {status_str:<10}")
            print("=" * 80)

    finally:
        # 关闭串口
        print("\n正在关闭串口...")
        scanner.close_port()
        print("完成")


if __name__ == "__main__":
    main()
