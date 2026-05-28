# -*- coding: utf-8 -*-
import time
import serial
from loguru import logger
from typing import Optional, Tuple

class CH9329Controller:
    """
    CH9329 串口转 USB 键鼠模块控制器。
    用于通过物理串口发送指令在手机上进行绝对鼠标定位和打字输入。
    """
    def __init__(self, port: str = "COM3", baudrate: int = 9600, timeout: float = 0.5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        
    def connect(self) -> bool:
        """建立串口连接"""
        if self.ser and self.ser.is_open:
            return True
        try:
            logger.info(f"Opening serial port {self.port} at {self.baudrate} baud...")
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            logger.info(f"Serial port {self.port} opened successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to open serial port {self.port}: {e}")
            self.ser = None
            return False
            
    def disconnect(self):
        """断开串口连接"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                logger.info(f"Serial port {self.port} closed.")
            except Exception as e:
                logger.warning(f"Error closing serial port: {e}")
        self.ser = None

    def _send_packet(self, cmd: int, data: bytes) -> bool:
        """组装并发送 CH9329 协议包"""
        if not self.ser or not self.ser.is_open:
            if not self.connect():
                return False
                
        # 帧结构: 帧头(57 AB) + 地址码(00) + 命令码(cmd) + 数据长度(len) + 数据(data) + 校验和(sum)
        head = bytes([0x57, 0xAB])
        addr = bytes([0x00])
        cmd_b = bytes([cmd])
        length_b = bytes([len(data)])
        
        sum_data = 0x57 + 0xAB + 0x00 + cmd + len(data) + sum(data)
        checksum = bytes([sum_data & 0xFF])
        
        packet = head + addr + cmd_b + length_b + data + checksum
        
        try:
            self.ser.write(packet)
            self.ser.flush()
            # Clear Rx buffer to prevent memory accumulate
            if self.ser.in_waiting > 0:
                self.ser.read_all()
            # 微量延时，避免命令发送过快导致硬件粘包
            time.sleep(0.01)
            return True
        except Exception as e:
            logger.error(f"Failed to write serial packet: {e}")
            return False

    # =========================================================================
    # 鼠标控制 (绝对坐标)
    # =========================================================================
    
    def _send_abs_mouse(self, buttons: int, x: int, y: int) -> bool:
        """
        发送绝对坐标鼠标指令
        buttons: 0x01(左键按下), 0x02(右键按下), 0x00(释放)
        x, y: 0 ~ 4095
        """
        # 数据区长度为 7，格式: 0x02, buttons, x_low, x_high, y_low, y_high, 0x00
        x_low = x & 0xFF
        x_high = (x >> 8) & 0xFF
        y_low = y & 0xFF
        y_high = (y >> 8) & 0xFF
        
        data = bytes([0x02, buttons, x_low, x_high, y_low, y_high, 0x00])
        return self._send_packet(0x04, data)

    def move_to(self, x_ratio: float, y_ratio: float) -> bool:
        """
        移动鼠标至屏幕相对比例位置。
        CH9329 绝对坐标为 0~4095
        """
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        x = max(0, min(4095, x))
        y = max(0, min(4095, y))
        return self._send_abs_mouse(0x00, x, y)

    def click(self, x_ratio: float, y_ratio: float) -> bool:
        """点击屏幕上某个坐标点"""
        if not self.move_to(x_ratio, y_ratio):
            return False
        time.sleep(0.1)
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        
        # 左键按下
        if not self._send_abs_mouse(0x01, x, y):
            return False
        time.sleep(0.08)
        # 释放
        res = self._send_abs_mouse(0x00, x, y)
        time.sleep(0.1)
        return res

    def long_press(self, x_ratio: float, y_ratio: float, duration: float = 2.0) -> bool:
        """在坐标点上长按鼠标指定秒数"""
        if not self.move_to(x_ratio, y_ratio):
            return False
        time.sleep(0.1)
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        
        # 左键按下并保持
        logger.info(f"Long pressing mouse at ({x_ratio}, {y_ratio}) for {duration}s...")
        if not self._send_abs_mouse(0x01, x, y):
            return False
        time.sleep(duration)
        # 释放
        res = self._send_abs_mouse(0x00, x, y)
        time.sleep(0.1)
        return res

    # =========================================================================
    # 键盘控制
    # =========================================================================
    
    def _send_keyboard(self, modifier: int, keycode: int) -> bool:
        """发送单键按下，并自动发送释放包"""
        # 数据区长度为 8，格式: modifier, 0x00, keycode, 0x00, 0x00, 0x00, 0x00, 0x00
        press_data = bytes([modifier, 0x00, keycode, 0x00, 0x00, 0x00, 0x00, 0x00])
        release_data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        
        if not self._send_packet(0x02, press_data):
            return False
        time.sleep(0.04)
        return self._send_packet(0x02, release_data)

    def press_key(self, char: str) -> bool:
        """模拟键盘输入单个字符"""
        # 字符到键码映射表
        mapping = {}
        
        # 字母 a-z
        for i in range(26):
            c_lower = chr(ord('a') + i)
            c_upper = chr(ord('A') + i)
            keycode = 0x04 + i
            mapping[c_lower] = (0x00, keycode)  # No shift
            mapping[c_upper] = (0x02, keycode)  # Shift

        # 数字 1-9, 0
        for i in range(9):
            c_num = chr(ord('1') + i)
            keycode = 0x1E + i
            mapping[c_num] = (0x00, keycode)
        mapping['0'] = (0x00, 0x27)

        # 常用符号映射 (modifier, keycode)
        mapping[' '] = (0x00, 0x2C)
        mapping['\n'] = (0x00, 0x28)
        mapping['-'] = (0x00, 0x2D)
        mapping['_'] = (0x02, 0x2D)
        mapping['='] = (0x00, 0x2E)
        mapping['+'] = (0x02, 0x2E)
        mapping['['] = (0x00, 0x2F)
        mapping[']'] = (0x00, 0x30)
        mapping[';'] = (0x00, 0x33)
        mapping[':'] = (0x02, 0x33)
        mapping['.'] = (0x00, 0x37)
        mapping['/'] = (0x00, 0x38)
        mapping['?'] = (0x02, 0x38)
        mapping[','] = (0x00, 0x36)
        mapping['\\'] = (0x00, 0x34)
        mapping['|'] = (0x02, 0x34)

        if char not in mapping:
            # 遇到不能直接模拟的字符，回退尝试不加 Shift 的普通键入，或者忽略
            logger.warning(f"Unsupported key simulation for char '{char}'. Skipping.")
            return False
            
        mod, code = mapping[char]
        return self._send_keyboard(mod, code)

    def write_text(self, text: str, delay: float = 0.05):
        """输入长文本字符串"""
        logger.info(f"Typing text via CH9329: {text}")
        for char in text:
            self.press_key(char)
            time.sleep(delay)

    def press_enter(self) -> bool:
        """发送回车键"""
        return self._send_keyboard(0x00, 0x28)

    def press_space(self) -> bool:
        """发送空格键"""
        return self._send_keyboard(0x00, 0x2C)

    def press_home(self) -> bool:
        """发送 Home 键 (常用于返回桌面)"""
        return self._send_keyboard(0x00, 0x4A)

    def press_win(self) -> bool:
        """发送 Win 键 (在 Android 实体键盘上代表 Meta 键，常能拉起全局搜索)"""
        # Win 键即 GUI 键，modifier 对应 0x08
        return self._send_keyboard(0x08, 0x00)

    def press_backspace(self, times: int = 1) -> bool:
        """发送退格键"""
        for _ in range(times):
            if not self._send_keyboard(0x00, 0x2A):
                return False
            time.sleep(0.05)
        return True
