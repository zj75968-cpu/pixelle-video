import subprocess
import os
import time
import sys

# 重置 stdout 编码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ADB = r'C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE'
SERIAL = '10ACBE28M70044L'

def adb_run(args_list):
    """使用 subprocess.run 传入参数列表，绝对安全避免 Windows 命令行双引号剥离 Bug"""
    cmd = [ADB, "-s", SERIAL] + args_list
    print(f"[ADB] Executing: {' '.join(cmd)}", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ADB][ERR] code {res.returncode}\nstdout: {res.stdout}\nstderr: {res.stderr}", flush=True)
    return res.returncode

def preprocess_and_push(local_src, remote_dest):
    """智能预处理：转换 CRLF 换行符为 Unix \n，并自动替换 Termux 不兼容的选项，再执行推送"""
    print(f"[Prep] 正在预处理并推送 {local_src} → {remote_dest}...", flush=True)
    with open(local_src, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # 彻底抹除 CRLF 换行符
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    
    # 解决 Termux 不兼容选项，并抹除极慢的 pkg update 以开启极速闪装
    if local_src.endswith("setup_termux.sh"):
        content = content.replace("2>&1 | tail -3", "")
        content = content.replace("--quiet", "")
        content = content.replace("pkg update -y", "echo 'Skip slow pkg update for super-speed'")
        
    temp_local = local_src + ".unix.tmp"
    with open(temp_local, "w", newline="\n", encoding="utf-8") as f:
        f.write(content)
        
    try:
        adb_run(["push", temp_local, remote_dest])
    finally:
        if os.path.exists(temp_local):
            os.remove(temp_local)

def main():
    print("=== 开始华为手机 Termux 自动化一键调试服务 ===", flush=True)
    
    # 1. 强力终止旧的 Termux，清理资源
    print("\n1. 强力终止旧的 Termux 进程以释放一切端口和残留...", flush=True)
    adb_run(["shell", "am", "force-stop", "com.termux"])
    time.sleep(1.5)
    
    # 2. 推送文件（使用智能 Unix 转换器 + 极速闪装替换）
    print("\n2. 智能预处理并推送最新的初始化脚本和心跳自愈代理到手机中...", flush=True)
    preprocess_and_push("scripts/setup_termux.sh", "/sdcard/pixelle_setup.sh")
    preprocess_and_push("scripts/phone_agent.py", "/sdcard/phone_agent.py")
    time.sleep(1.0)
    
    # 3. 启动全新 Termux
    print("\n3. 启动一个全新干净的 Termux 终端窗口...", flush=True)
    adb_run(["shell", "am", "start", "-n", "com.termux/.app.TermuxActivity"])
    print("等待窗口加载...", flush=True)
    time.sleep(5.0)  # 留足时间
    
    # 4. 模拟输入命令灌装
    print("\n4. 正在为您自动向手机 Termux 模拟输入一键灌装命令...", flush=True)
    
    # 输入 "bash /sdcard/pixelle_setup.sh"
    # 分段发送以保障 100% 成功
    adb_run(["shell", "input", "text", "bash"])
    time.sleep(0.2)
    adb_run(["shell", "input", "keyevent", "62"]) # space
    time.sleep(0.2)
    adb_run(["shell", "input", "text", "/sdcard/pixelle_setup.sh"])
    time.sleep(0.5)
    
    # 发送回车以执行灌装
    print("发送回车开始灌装...", flush=True)
    adb_run(["shell", "input", "keyevent", "66"])
    
    # 灌装时间长一些，需要 15 秒
    print("灌装命令已在手机上运行，正在静候灌装执行完毕（约 15 秒）...", flush=True)
    for s in range(15, 0, -1):
        print(f" 倒计时 {s} 秒...", flush=True)
        time.sleep(1.0)
        
    # 5. 模拟输入启动命令
    print("\n5. 一键灌装完成，正在自动向手机 Termux 输入启动指令...", flush=True)
    
    # 输入 source $HOME/.bashrc 并回车以加载别名环境
    print("加载别名环境...", flush=True)
    adb_run(["shell", "input", "text", "source"])
    time.sleep(0.2)
    adb_run(["shell", "input", "keyevent", "62"]) # space
    time.sleep(0.2)
    adb_run(["shell", "input", "text", "$HOME/.bashrc"])
    time.sleep(0.3)
    adb_run(["shell", "input", "keyevent", "66"])
    time.sleep(1.0)
    
    # 输入 start 并回车
    print("输入 start 并执行挂机...", flush=True)
    adb_run(["shell", "input", "text", "start"])
    time.sleep(0.3)
    adb_run(["shell", "input", "keyevent", "66"])
    
    print("\n=== 一键自动调试与挂机代理开启成功！请看手机屏幕！ ===", flush=True)

if __name__ == "__main__":
    main()
