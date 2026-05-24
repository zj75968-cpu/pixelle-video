import subprocess
import time
import sys

# 重置 stdout 编码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ADB = r'C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE'
SERIAL = '10ACBE28M70044L'

def adb_run(args_list):
    cmd = [ADB, "-s", SERIAL] + args_list
    print(f"[ADB] Executing: {' '.join(cmd)}", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode

def main():
    print("=== 开始华为手机 Termux 强力一键补发唤醒服务 ===", flush=True)
    
    # 1. 确保 Termux 处于最前台
    print("1. 确保 Termux 激活在前台...", flush=True)
    adb_run(["shell", "am", "start", "-n", "com.termux/.app.TermuxActivity"])
    time.sleep(1.0)
    
    # 2. 模拟发送 Ctrl+C 以清空所有正在输入的杂乱字符
    print("2. 发送 Ctrl+C 清空当前行输入...", flush=True)
    # 发送 KEYCODE_CTRL_LEFT 模拟 Ctrl+C
    # Termux 可以通过 input 快捷方式清空，我们发送多次回车更稳妥
    adb_run(["shell", "input", "keyevent", "66"]) # Enter
    time.sleep(0.3)
    adb_run(["shell", "input", "keyevent", "66"]) # Enter
    time.sleep(0.3)
    
    # 3. 模拟键盘输入执行灌装：bash /sdcard/pixelle_setup.sh
    cmd_setup = "bash /sdcard/pixelle_setup.sh"
    print(f"3. 模拟键盘输入并执行灌装: {cmd_setup}", flush=True)
    adb_run(["shell", "input", "text", "bash"])
    time.sleep(0.2)
    adb_run(["shell", "input", "keyevent", "62"]) # space
    time.sleep(0.2)
    adb_run(["shell", "input", "text", "/sdcard/pixelle_setup.sh"])
    time.sleep(0.3)
    adb_run(["shell", "input", "keyevent", "66"]) # Enter
    
    # 极速闪装（无 pkg update），只需等待 5 秒
    print("等待极速灌装写入文件（约 5 秒）...", flush=True)
    time.sleep(5.0)
    
    # 4. 模拟输入并执行启动命令
    cmd_start = "bash /data/data/com.termux/files/home/start.sh"
    print(f"\n4. 模拟键盘输入并启动服务: {cmd_start}", flush=True)
    
    adb_run(["shell", "input", "text", "bash"])
    time.sleep(0.2)
    adb_run(["shell", "input", "keyevent", "62"]) # space
    time.sleep(0.2)
    adb_run(["shell", "input", "text", "/data/data/com.termux/files/home/start.sh"])
    time.sleep(0.3)
    adb_run(["shell", "input", "keyevent", "66"]) # Enter
    
    print("=== 强力闪装与启动指令全部发送完毕！ ===", flush=True)

if __name__ == "__main__":
    main()
