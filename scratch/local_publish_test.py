# -*- coding: utf-8 -*-
"""
本地小红书发布及双手机连通性自动化测试脚本

此脚本专门在本地运行，用于测试你连接的两个手机，执行屏幕解锁、打开小红书、确认发帖等操作。
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# 将项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def run_adb(args):
    """运行 ADB 命令并返回输出"""
    try:
        res = subprocess.run(["adb"] + args, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"

def get_adb_devices():
    """获取本地所有 ADB 设备及其状态"""
    output = run_adb(["devices"])
    devices = []
    print("📋 当前系统检测到的手机设备列表：")
    print(output)
    
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            serial, status = parts[0], parts[1]
            devices.append((serial, status))
    return devices

def test_single_device(serial, index):
    """对单台手机进行小红书自动化发布节点测试"""
    print(f"\n{'='*50}")
    print(f"📱 正在测试第 {index} 台手机：[序列号: {serial}]")
    print(f"{'='*50}")
    
    # 1. 唤醒并解锁屏幕
    print("🔌 正在尝试唤醒屏幕...")
    run_adb(["-s", serial, "shell", "input", "keyevent", "224"])
    time.sleep(1)
    
    # 模拟向上划动解锁
    print("🔓 正在尝试划屏解锁...")
    run_adb(["-s", serial, "shell", "input", "swipe", "500", "1800", "500", "400", "300"])
    time.sleep(1)
    
    # 2. 检查 uiautomator2 依赖
    try:
        import uiautomator2 as u2
        print("🔍 正在连接手机无障碍服务 (uiautomator2)...")
        d = u2.connect(serial)
        info = d.info
        print(f"✅ 连接成功！手机分辨率：{info.get('displayWidth')}x{info.get('displayHeight')}")
    except ImportError:
        print("⚠️ 本地未检测到 uiautomator2 库。请运行：pip install uiautomator2")
        print("💡 临时采用原生 ADB Shell 注入模式运行...")
        d = None
    except Exception as e:
        print(f"❌ 无法连接 uiautomator2：{e}。请确保已在手机的开发者选项中开启「USB 调试（安全设置）/ 允许模拟点击」")
        d = None

    # 3. 启动小红书 APP 并尝试点击发布
    print("🚀 正在手机上拉起小红书 App...")
    run_adb(["-s", serial, "shell", "am", "force-stop", "com.xingin.xhs"])
    time.sleep(1)
    run_adb(["-s", serial, "shell", "monkey", "-p", "com.xingin.xhs", "-c", "android.intent.category.LAUNCHER", "1"])
    time.sleep(4)  # 等待小红书加载

    if d:
        try:
            print("👁️ 正在利用无障碍引擎寻找小红书底部的 [+] 加号发布按钮...")
            # 尝试通过无障碍描述定位小红书加号
            publish_btn = d(descriptionContains="发布") or d(descriptionContains="加号") or d(resourceId="com.xingin.xhs:id/tab_add")
            if publish_btn.exists(timeout=5):
                print("🎯 成功找到 [+] 按钮！正在自动点击以打开发布选择器...")
                publish_btn.click()
                time.sleep(2)
                
                # 截图保存到本地
                screenshot_path = Path(__file__).resolve().parent / f"screenshot_{serial}.png"
                d.screenshot(str(screenshot_path))
                print(f"📸 已成功抓取当前手机小红书发布页面截图，保存为：{screenshot_path.name}")
                
                # 退出发布页面回到主页
                print("↩️ 测试完毕，正在退回桌面...")
                d.press("back")
            else:
                print("⚠️ 未能在小红书首页检测到 '+' 号发布按钮，可能手机未处于小红书首页或被弹窗遮挡。")
                print("💡 采用备用物理点击（点击底部中点位置）...")
                w, h = info.get('displayWidth', 1080), info.get('displayHeight', 2400)
                d.click(w // 2, int(h * 0.97))
                time.sleep(2)
                d.press("back")
        except Exception as e:
            print(f"❌ 自动控制点击失败：{e}")
    else:
        # ADB 原生降级逻辑
        print("💡 正在通过 ADB 指令向手机注入虚拟点击以打开 [+] 按钮...")
        # 默认中低端手机底部发布按钮坐标大概在屏幕下方正中间
        run_adb(["-s", serial, "shell", "input", "tap", "540", "2250"])
        time.sleep(2)
        run_adb(["-s", serial, "shell", "input", "keyevent", "4"]) # 退回

    print(f"🎉 手机 {serial} 测试流执行完成！")

def main():
    print("="*60)
    print("      Pixelle-Video 手机发布联调自动化测试工具")
    print("="*60)
    
    devices = get_adb_devices()
    
    if not devices:
        print("❌ 未检测到任何已连接设备。请将手机通过 USB 连接电脑，并开启 USB 调试。")
        return
        
    unauthorized = [d for d in devices if d[1] == "unauthorized"]
    authorized = [d for d in devices if d[1] == "device"]
    
    if unauthorized:
        print("\n⚠️ 发现未授权设备：")
        for serial, _ in unauthorized:
            print(f"   🔓 {serial} (未授权)")
        print("\n👉 解决办法：")
        print("   请解锁手机屏幕，在手机弹出的【是否允许 USB 调试？】对话框中：")
        print("   1. 勾选【始终允许来自此计算机的调试】")
        print("   2. 点击【允许/确定】")
        print("   3. 允许后重新执行此测试！\n")
        
    if not authorized:
        print("⚠️ 当前无任何「已授权」的手机，无法进行发布流自动化测试。请先完成上述授权。")
        return
        
    print(f"\n🚀 检测到共有 {len(authorized)} 台已授权的手机，开始进行实机发布流测试...\n")
    for idx, (serial, _) in enumerate(authorized, 1):
        test_single_device(serial, idx)
        
    print("\n✅ 所有可用手机的 E2E 节点连通性测试全部结束！")

if __name__ == "__main__":
    main()
