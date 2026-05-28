# -*- coding: utf-8 -*-
"""
小红书硬件发布最小 MVP 测试脚本
可以直接物理运行测试：消重 -> 图床上传 -> CH9329手机端动作执行
"""
import os
import time
import random
import httpx
import serial
from PIL import Image, ImageEnhance

# =========================================================================
# 🛠️ 核心配置（根据你的实际环境在这里直接修改）
# =========================================================================
CONFIG = {
    # 1. 硬件控制配置
    "com_port": "COM3",           # CH340 虚拟出的串口号
    "baudrate": 9600,             # 默认波特率 9600
    "unlock_pin": "",             # 手机解锁密码（数字，若没有则留空）

    # 2. Lsky Pro 图床配置
    "lsky_url": "http://192.168.1.100/api/v1/upload",  # 你的 Lsky Pro 上传 API 直链接
    "lsky_token": "Bearer <YOUR_TOKEN>",                # 你的 Lsky 授权 Token
    "lsky_album_id": None,                             # 相册ID（可选）

    # 3. 手机屏幕操作位置比例（0.0 ~ 1.0）
    "coords": {
        "browser_address_bar_x": 0.5,
        "browser_address_bar_y": 0.08,
        "browser_image_x": 0.5,
        "browser_image_y": 0.5,
        "browser_save_btn_x": 0.5,
        "browser_save_btn_y": 0.85,
        "xhs_icon_x": 0.3,
        "xhs_icon_y": 0.5,
        "xhs_add_btn_x": 0.5,
        "xhs_add_btn_y": 0.95,
        "xhs_first_album_x": 0.25,
        "xhs_first_album_y": 0.25,
        "xhs_next_btn_x": 0.85,
        "xhs_next_btn_y": 0.08,
        "xhs_publish_btn_x": 0.5,
        "xhs_publish_btn_y": 0.92
    }
}

# 测试图片源及临时文件
SRC_IMAGE = os.path.join(os.path.dirname(__file__), "xhs_demo_post.png")
TEMP_JPG = os.path.join(os.path.dirname(__file__), "temp_mvp.jpg")

# =========================================================================
# 1️⃣ PIL 像素级消重
# =========================================================================
def pixel_de_duplicate(input_path: str, output_path: str) -> bool:
    print(f"[消重] 开始消重: {input_path}...")
    try:
        with Image.open(input_path) as img:
            width, height = img.size
            
            # 裁剪 1 像素
            img = img.crop((1, 1, width - 1, height - 1))
            
            # 微调亮度 (0.99)
            img = ImageEnhance.Brightness(img).enhance(0.99)
            
            # 微调对比度 (0.99)
            img = ImageEnhance.Contrast(img).enhance(0.99)
            
            # 极其微小的旋转并还原大小 (0.15度)
            img = img.rotate(0.15, resample=Image.Resampling.BICUBIC, expand=False)
            
            # 去除 EXIF 信息并存为 JPEG
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(output_path, "JPEG", quality=95)
            print(f"[OK] 消重成功 -> {output_path}")
            return True
    except Exception as e:
        print(f"[ERR] 消重失败: {e}")
        return False

# =========================================================================
# 2️⃣ 上传图床并获得局域网直链
# =========================================================================
def upload_to_lsky(file_path: str) -> str:
    print(f"[图床] 上传文件 {file_path} 至 Lsky Pro...")
    token = CONFIG["lsky_token"]
    if not token.startswith("Bearer "):
        token = f"Bearer {token}"
        
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }
    
    data = {}
    if CONFIG["lsky_album_id"] is not None:
        data["album_id"] = str(CONFIG["lsky_album_id"])
        
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "image/jpeg")}
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(CONFIG["lsky_url"], headers=headers, data=data, files=files)
                
            if resp.status_code != 200:
                print(f"[ERR] 图床服务器返回 HTTP {resp.status_code}: {resp.text}")
                return ""
                
            res = resp.json()
            if not res.get("status"):
                print(f"[ERR] 图床接口返回错误: {res.get('message')}")
                return ""
                
            url = res.get("data", {}).get("links", {}).get("url")
            print(f"[OK] 图床上传成功! 直链地址: {url}")
            return url
    except Exception as e:
        print(f"[ERR] 图床上传异常: {e}")
        return ""

# =========================================================================
# 3️⃣ CH9329 控制器
# =========================================================================
class CH9329MVP:
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.5)
            print(f"[串口] 成功连接 {self.port}")
            return True
        except Exception as e:
            print(f"[ERR] 无法打开串口 {self.port}: {e}")
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[串口] 连接已关闭")

    def _send_packet(self, cmd, data):
        if not self.ser or not self.ser.is_open:
            return False
        # 帧头 + 地址 + 命令 + 长度 + 数据 + 校验
        packet = bytes([0x57, 0xAB, 0x00, cmd, len(data)]) + data
        checksum = bytes([sum(packet) & 0xFF])
        self.ser.write(packet + checksum)
        self.ser.flush()
        time.sleep(0.01)
        return True

    def move_to(self, x_ratio, y_ratio):
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        data = bytes([0x02, 0x00, x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, (y >> 8) & 0xFF, 0x00])
        return self._send_packet(0x04, data)

    def click(self, x_ratio, y_ratio):
        self.move_to(x_ratio, y_ratio)
        time.sleep(0.1)
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        # 按下
        self._send_packet(0x04, bytes([0x02, 0x01, x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, (y >> 8) & 0xFF, 0x00]))
        time.sleep(0.08)
        # 释放
        self._send_packet(0x04, bytes([0x02, 0x00, x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, (y >> 8) & 0xFF, 0x00]))
        time.sleep(0.1)

    def long_press(self, x_ratio, y_ratio, duration=2.5):
        self.move_to(x_ratio, y_ratio)
        time.sleep(0.1)
        x = int(x_ratio * 4095)
        y = int(y_ratio * 4095)
        self._send_packet(0x04, bytes([0x02, 0x01, x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, (y >> 8) & 0xFF, 0x00]))
        time.sleep(duration)
        self._send_packet(0x04, bytes([0x02, 0x00, x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, (y >> 8) & 0xFF, 0x00]))
        time.sleep(0.1)

    def _send_keyboard(self, mod, keycode):
        self._send_packet(0x02, bytes([mod, 0x00, keycode, 0x00, 0x00, 0x00, 0x00, 0x00]))
        time.sleep(0.04)
        self._send_packet(0x02, bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))

    def write_text(self, text, delay=0.05):
        mapping = {}
        for i in range(26):
            mapping[chr(ord('a') + i)] = (0x00, 0x04 + i)
            mapping[chr(ord('A') + i)] = (0x02, 0x04 + i)
        for i in range(9):
            mapping[chr(ord('1') + i)] = (0x00, 0x1E + i)
        mapping['0'] = (0x00, 0x27)
        mapping[' '] = (0x00, 0x2C)
        mapping['\n'] = (0x00, 0x28)
        mapping['-'] = (0x00, 0x2D)
        mapping['_'] = (0x02, 0x2D)
        mapping[':'] = (0x02, 0x33)
        mapping['.'] = (0x00, 0x37)
        mapping['/'] = (0x00, 0x38)

        for char in text:
            if char in mapping:
                mod, code = mapping[char]
                self._send_keyboard(mod, code)
                time.sleep(delay)

    def press_backspace(self, count=10):
        for _ in range(count):
            self._send_keyboard(0x00, 0x2A)
            time.sleep(0.03)

# =========================================================================
# 🚀 完整发帖主流程
# =========================================================================
def run_mvp_publish():
    # Step 1: 消重
    if not pixel_de_duplicate(SRC_IMAGE, TEMP_JPG):
        return
        
    # Step 2: 图床上传
    direct_url = upload_to_lsky(TEMP_JPG)
    if not direct_url:
        print("[FAIL] 图床直链获取失败，终止流程。")
        return

    # Step 3: CH9329 模拟操作
    mvp = CH9329MVP(CONFIG["com_port"], CONFIG["baudrate"])
    if not mvp.connect():
        return

    coords = CONFIG["coords"]
    try:
        # 1. 物理唤醒并解锁
        print("[行动] 唤醒手机并解锁...")
        mvp._send_keyboard(0x08, 0x00)  # Win/Meta 键唤醒
        time.sleep(1.0)
        mvp._send_keyboard(0x00, 0x2C)  # 空格
        time.sleep(1.0)
        
        if CONFIG["unlock_pin"]:
            print(f"[行动] 输入锁屏密码: {CONFIG['unlock_pin']}")
            mvp.write_text(CONFIG["unlock_pin"])
            time.sleep(0.5)
            mvp._send_keyboard(0x00, 0x28)  # Enter 回车解锁
            time.sleep(2.0)

        # 返回桌面首页
        mvp._send_keyboard(0x00, 0x4A)  # Home 键
        time.sleep(1.5)

        # 2. 启动浏览器
        print("[行动] 打开系统默认浏览器...")
        mvp._send_keyboard(0x08, 0x00)  # 按 Win
        time.sleep(1.0)
        mvp.write_text("browser")       # 搜索浏览器
        time.sleep(1.0)
        mvp._send_keyboard(0x00, 0x28)  # 回车打开
        time.sleep(3.0)

        # 3. 访问直链并保存
        print(f"[行动] 输入图床 URL: {direct_url} ...")
        mvp.click(coords["browser_address_bar_x"], coords["browser_address_bar_y"])
        time.sleep(0.5)
        mvp.press_backspace(50)  # 擦除旧地址
        time.sleep(0.5)
        mvp.write_text(direct_url)
        time.sleep(0.5)
        mvp._send_keyboard(0x00, 0x28)  # 回车访问
        time.sleep(4.0)  # 等待图片加载

        print("[行动] 长按图片并点击保存...")
        mvp.long_press(coords["browser_image_x"], coords["browser_image_y"], duration=2.5)
        time.sleep(1.0)
        mvp.click(coords["browser_save_btn_x"], coords["browser_save_btn_y"])
        time.sleep(2.0)

        # 4. 进入小红书
        print("[行动] 回到桌面，打开小红书...")
        mvp._send_keyboard(0x00, 0x4A)  # Home 键
        time.sleep(1.5)
        
        mvp._send_keyboard(0x08, 0x00)  # 按 Win
        time.sleep(1.0)
        mvp.write_text("xhs")
        time.sleep(1.0)
        mvp._send_keyboard(0x00, 0x28)  # 回车打开小红书
        time.sleep(6.0)  # 等待广告

        # 5. 发布流程
        print("[行动] 点击 '+' 按钮开始发布...")
        mvp.click(coords["xhs_add_btn_x"], coords["xhs_add_btn_y"])
        time.sleep(3.0)

        print("[行动] 选中刚刚下载的第一张图片...")
        mvp.click(coords["xhs_first_album_x"], coords["xhs_first_album_y"])
        time.sleep(1.5)

        print("[行动] 点击下一步（相册确认页）...")
        mvp.click(coords["xhs_next_btn_x"], coords["xhs_next_btn_y"])
        time.sleep(2.0)
        
        print("[行动] 点击下一步（滤镜调整页）...")
        mvp.click(coords["xhs_next_btn_x"], coords["xhs_next_btn_y"])
        time.sleep(2.5)

        # 6. 编辑标题正文并发布
        print("[行动] 模拟输入标题与正文文案...")
        # 点击标题输入框（比例 0.35）并键入
        mvp.click(0.3, 0.35)
        time.sleep(0.8)
        mvp.write_text("mvp test title")
        time.sleep(1.0)

        # 点击正文输入框（比例 0.45）并键入
        mvp.click(0.3, 0.45)
        time.sleep(0.8)
        mvp.write_text("This is an automatic post from Pixelle MVP. #hardware #automation")
        time.sleep(1.5)

        print("[行动] 点击发布按钮！")
        mvp.click(coords["xhs_publish_btn_x"], coords["xhs_publish_btn_y"])
        time.sleep(5.0)

        print("[🎉] 物理控制发布完成！")

    finally:
        mvp.disconnect()
        # 清除临时文件
        if os.path.exists(TEMP_JPG):
            os.remove(TEMP_JPG)

if __name__ == "__main__":
    if not os.path.exists(SRC_IMAGE):
        # 创建空白测试图
        img = Image.new('RGB', (800, 800), color=(73, 109, 137))
        img.save(SRC_IMAGE)
    run_mvp_publish()
