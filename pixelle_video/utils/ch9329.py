# -*- coding: utf-8 -*-
import time
import serial
from loguru import logger
from typing import Optional

class CH9329Controller:
    """
    CH9329 串口转 USB 键鼠模块控制器。
    已升级为“相对鼠标高精度校准机制”，以完美兼容不支持绝对鼠标的安卓定制系统。
    """
    def __init__(self, port: str = "COM3", baudrate: int = 9600, timeout: float = 0.5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        
        # 预设手机屏幕物理分辨率，用于从比例换算到像素位移
        self.screen_width = 1080
        self.screen_height = 2400
        
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
            if self.ser.in_waiting > 0:
                self.ser.read_all()
            time.sleep(0.01)
            return True
        except Exception as e:
            logger.error(f"Failed to write serial packet: {e}")
            return False

    # =========================================================================
    # 相对鼠标控制 (100% 安卓系统物理兼容)
    # =========================================================================
    
    def _send_rel_mouse(self, buttons: int, x_rel: int, y_rel: int, wheel: int = 0) -> bool:
        """
        发送相对鼠标数据包
        buttons: 0x01(左键按下), 0x02(右键按下), 0x00(释放)
        x_rel, y_rel: -127 ~ 127
        """
        x_b = x_rel & 0xFF
        y_b = y_rel & 0xFF
        wheel_b = wheel & 0xFF
        
        # 格式: 0x01 (相对鼠标标志), buttons, x_rel, y_rel, wheel
        data = bytes([0x01, buttons, x_b, y_b, wheel_b])
        return self._send_packet(0x05, data)

    def calibrate_mouse(self) -> bool:
        """将鼠标光标强制归零到屏幕左上角 (0, 0)"""
        # 往左上方发送大距离位移，循环 30 次能移动 3600 像素，确保归零
        for _ in range(30):
            if not self._send_rel_mouse(0x00, -120, -120):
                return False
            time.sleep(0.005)
        return True

    def move_to(self, x_ratio: float, y_ratio: float) -> bool:
        """
        高精度移动到指定屏幕相对比例坐标点。
        采用“左上角归零 + 分步相对偏移”机制。
        """
        if not self.calibrate_mouse():
            return False
            
        # 换算为物理像素目标值
        tx = int(x_ratio * self.screen_width)
        ty = int(y_ratio * self.screen_height)
        
        # 分步移动 X 轴
        step_x = 100 if tx >= 0 else -100
        for _ in range(abs(tx) // 100):
            self._send_rel_mouse(0x00, step_x, 0)
            time.sleep(0.008)
        if abs(tx) % 100 != 0:
            rem_x = (abs(tx) % 100) * (1 if tx >= 0 else -1)
            self._send_rel_mouse(0x00, rem_x, 0)
            time.sleep(0.008)
            
        # 分步移动 Y 轴
        step_y = 100 if ty >= 0 else -100
        for _ in range(abs(ty) // 100):
            self._send_rel_mouse(0x00, 0, step_y)
            time.sleep(0.008)
        if abs(ty) % 100 != 0:
            rem_y = (abs(ty) % 100) * (1 if ty >= 0 else -1)
            self._send_rel_mouse(0x00, 0, rem_y)
            time.sleep(0.008)
            
        return True

    def click(self, x_ratio: float, y_ratio: float) -> bool:
        """物理模拟点击相对比例坐标点"""
        if not self.move_to(x_ratio, y_ratio):
            return False
        time.sleep(0.1)
        
        # 左键按下并释放
        if not self._send_rel_mouse(0x01, 0, 0):
            return False
        time.sleep(0.08)
        res = self._send_rel_mouse(0x00, 0, 0)
        time.sleep(0.1)
        return res

    def long_press(self, x_ratio: float, y_ratio: float, duration: float = 2.0) -> bool:
        """物理模拟长按相对比例坐标点"""
        if not self.move_to(x_ratio, y_ratio):
            return False
        time.sleep(0.1)
        
        # 左键按下保持
        logger.info(f"Long pressing mouse at ({x_ratio}, {y_ratio}) for {duration}s...")
        if not self._send_rel_mouse(0x01, 0, 0):
            return False
        time.sleep(duration)
        res = self._send_rel_mouse(0x00, 0, 0)
        time.sleep(0.1)
        return res

    def swipe_up_to_home(self) -> bool:
        """物理手势：从屏幕底部垂直向上滑动返回桌面"""
        logger.info("Executing swipe-up home gesture...")
        
        # 先移到最底部
        if not self.move_to(0.5, 0.98):
            return False
        time.sleep(0.1)
        
        # 模拟按下左键
        self._send_rel_mouse(0x01, 0, 0)
        time.sleep(0.1)
        
        # 相对向上滑动
        steps = 15
        for _ in range(steps):
            self._send_rel_mouse(0x01, 0, -80)
            time.sleep(0.015)
            
        time.sleep(0.1)
        # 释放左键
        self._send_rel_mouse(0x00, 0, 0)
        time.sleep(0.2)
        return True

    # =========================================================================
    # 键盘控制
    # =========================================================================
    
    def _send_keyboard(self, modifier: int, keycode: int) -> bool:
        """发送单键按下，并自动发送释放包"""
        press_data = bytes([modifier, 0x00, keycode, 0x00, 0x00, 0x00, 0x00, 0x00])
        release_data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        
        if not self._send_packet(0x02, press_data):
            return False
        time.sleep(0.04)
        return self._send_packet(0x02, release_data)

    def press_key(self, char: str) -> bool:
        """模拟键盘输入单个字符"""
        mapping = {}
        
        # 字母 a-z 与大写 A-Z
        for i in range(26):
            c_lower = chr(ord('a') + i)
            c_upper = chr(ord('A') + i)
            keycode = 0x04 + i
            mapping[c_lower] = (0x00, keycode)
            mapping[c_upper] = (0x02, keycode)

        # 数字 1-9, 0
        for i in range(9):
            c_num = chr(ord('1') + i)
            keycode = 0x1E + i
            mapping[c_num] = (0x00, keycode)
        mapping['0'] = (0x00, 0x27)

        # 常用键盘符号
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
        """物理上滑返回桌面（已弃用不可靠的 0x4A，采用 100% 成功的上滑手势）"""
        return self.swipe_up_to_home()

    def press_win(self) -> bool:
        """发送 Win 键"""
        return self._send_keyboard(0x08, 0x00)

    def press_backspace(self, times: int = 1) -> bool:
        """发送退格键"""
        for _ in range(times):
            if not self._send_keyboard(0x00, 0x2A):
                return False
            time.sleep(0.05)
        return True

    def press_ctrl_v(self) -> bool:
        """发送 Ctrl + V (粘贴键)"""
        return self._send_keyboard(0x01, 0x19)

    def press_ctrl_a(self) -> bool:
        """发送 Ctrl + A (全选键)"""
        return self._send_keyboard(0x01, 0x04)

    def press_ctrl_l(self) -> bool:
        """发送 Ctrl + L (聚焦浏览器地址栏)"""
        return self._send_keyboard(0x01, 0x0F)
