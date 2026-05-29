# -*- coding: utf-8 -*-
"""
自动寻找桌面上运行的 scrcpy 投屏窗口并截图，以便 AI 助手直接“看”到手机屏幕进行调试。
不需要安装额外的 pip 库，只依赖内置的 ctypes 和 PIL。
"""
import os
import sys
import ctypes
from ctypes import wintypes
from PIL import ImageGrab
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent

# Windows API 定义
EnumWindows = ctypes.windll.user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
GetWindowText = ctypes.windll.user32.GetWindowTextW
GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
IsWindowVisible = ctypes.windll.user32.IsWindowVisible
GetWindowRect = ctypes.windll.user32.GetWindowRect

def find_scrcpy_window():
    """寻找标题含有 scrcpy 的可见窗口句柄"""
    scrcpy_hwnd = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buff, length + 1)
                title = buff.value
                if "scrcpy" in title.lower():
                    scrcpy_hwnd.append((hwnd, title))
        return True
        
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return scrcpy_hwnd

def capture_window():
    dest_path = _project_root / "runtime" / "live_screen.png"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    windows = find_scrcpy_window()
    if not windows:
        print("[WARN] 未在电脑桌面上找到运行中的 scrcpy 投屏窗口，将截取全屏作为备用。")
        # 截取全屏
        img = ImageGrab.grab()
        img.save(dest_path)
        print(f"[OK] 全屏截图已保存至: runtime/live_screen.png")
        return False
        
    hwnd, title = windows[0]
    print(f"[INFO] 找到投屏窗口: '{title}'")
    
    # 获取窗口坐标
    rect = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    
    # 截取该窗口
    try:
        # 在某些 Windows DPI 缩放情况下，坐标可能需要调整，但 grab 默认能抓到
        img = ImageGrab.grab(bbox)
        img.save(dest_path)
        print(f"[OK] 投屏窗口截图已成功保存至: runtime/live_screen.png")
        return True
    except Exception as e:
        print(f"[ERROR] 截图失败: {e}")
        # 退回截全屏
        img = ImageGrab.grab()
        img.save(dest_path)
        return False

if __name__ == "__main__":
    capture_window()
