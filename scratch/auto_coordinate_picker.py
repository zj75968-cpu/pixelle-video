# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import time
from pathlib import Path

# 获取项目根目录
_project_root = Path(__file__).resolve().parent.parent

# 全局 active serial
active_serial = None

def get_active_device():
    """获取第一个状态为 device 的设备 Serial"""
    global active_serial
    adb_path = "adb"
    try:
        result = subprocess.run([adb_path, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        lines = result.stdout.strip().split("\n")
        devices = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial, status = parts[0], parts[1]
                if status == "device":
                    devices.append(serial)
        if devices:
            # 优先选择不是 IP 的物理设备
            phys = [d for d in devices if ":" not in d]
            if phys:
                active_serial = phys[0]
            else:
                active_serial = devices[0]
            print(f"[INFO] 锁定活动设备 Serial: {active_serial}")
            return active_serial
    except Exception as e:
        print(f"[ERROR] 获取设备列表失败: {e}")
    return None

def run_adb(args):
    """运行 ADB 命令并返回输出"""
    global active_serial
    adb_path = "adb"
    
    # 插入 -s <serial>
    prefix = []
    if active_serial:
        prefix = ["-s", active_serial]
        
    cmd = [adb_path] + prefix + args
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), -1

def get_screen_size():
    """获取屏幕分辨率"""
    out, code = run_adb(["shell", "wm", "size"])
    if code == 0 and "Physical size:" in out:
        size_str = out.split("Physical size:")[-1].strip()
        try:
            w, h = map(int, size_str.split("x"))
            return w, h
        except ValueError:
            pass
    return None

def dump_ui(name):
    """Dump 当前 UI 结构到本地"""
    print(f"正在获取手机当前界面布局 {name}...")
    xml_path = f"/sdcard/{name}.xml"
    run_adb(["shell", "uiautomator", "dump", xml_path])
    
    local_xml = _project_root / "runtime" / f"{name}.xml"
    local_xml.parent.mkdir(parents=True, exist_ok=True)
    run_adb(["pull", xml_path, str(local_xml)])
    
    # 顺便截张图作为备用，方便视觉二次确认
    png_path = f"/sdcard/{name}.png"
    run_adb(["shell", "screencap", "-p", png_path])
    local_png = _project_root / "runtime" / f"{name}.png"
    run_adb(["pull", png_path, str(local_png)])
    
    if local_xml.exists():
        print(f"[OK] 成功保存布局文件和截图到: runtime/{name}.xml 和 runtime/{name}.png")
        return True
    else:
        print(f"[FAIL] 保存布局文件失败，请检查是否在手机上点击了允许 USB 调试。")
        return False

def main():
    print("==================================================")
    print("         CH9329 手机屏幕坐标自动分析助手")
    print("==================================================")
    
    if not get_active_device():
        print("[ERROR] 未检测到已连接的活动的 ADB 设备，请重新拔插 USB 线并确保手机开启了 USB 调试！")
        sys.exit(1)
        
    size = get_screen_size()
    if not size:
        print("[ERROR] 无法获取手机屏幕分辨率，请确认手机已解锁并且屏幕亮起。")
        sys.exit(1)
        
    w, h = size
    print(f"[INFO] 检测到手机屏幕分辨率为: {w} x {h}")
    
    # 步骤 1: 浏览器页面
    print("\n--------------------------------------------------")
    print("【步骤 1】浏览器坐标抓取")
    print("请在手机浏览器中打开任意网页（最好是包含单张图片的页面，如百度首页或直链地址）")
    input("准备好后，请按 [Enter] 回车键继续...")
    dump_ui("browser_page")
    
    # 步骤 2: 小红书首页
    print("\n--------------------------------------------------")
    print("【步骤 2】小红书首页坐标抓取")
    print("请在手机上打开 [小红书] App，并停留在 [首页]（确保能看到底部的 + 号发帖按钮）")
    input("准备好后，请按 [Enter] 回车键继续...")
    dump_ui("xhs_home")
    
    # 步骤 3: 小红书选图/下一步
    print("\n--------------------------------------------------")
    print("【步骤 3】小红书选图界面坐标抓取")
    print("请在小红书首页点击底部的 [+] 号，进入相册选图界面（确保能看到最近照片的第一格和右上角的下一步）")
    input("准备好后，请按 [Enter] 回车键继续...")
    dump_ui("xhs_album")
    
    # 步骤 4: 小红书发帖编辑页
    print("\n--------------------------------------------------")
    print("【步骤 4】小红书发帖文案编辑页")
    print("请在选图界面点击右上角，进入写标题、写文案的发布预览页面（确保能看到底部的 [发布笔记] 按钮）")
    input("准备好后，请按 [Enter] 回车键继续...")
    dump_ui("xhs_edit")
    
    print("\n==================================================")
    print("所有的界面布局已成功抓取！")
    print("现在请在电脑终端回告我，我将开始自动解析这四个 XML 文件，")
    print("帮您精准提取所有按钮坐标并一键写入 config.yaml。")
    print("==================================================")

if __name__ == "__main__":
    main()
