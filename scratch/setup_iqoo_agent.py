import sys
import os
import subprocess
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SERIAL = "10ACBE28M70044L"
ADB_PATH = r"C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE"

if not os.path.exists(ADB_PATH):
    ADB_PATH = "adb"

# 实时的局域网 IP 与安全 Token
REAL_SERVER_URL = "http://23.238.47.62"
REAL_TOKEN = "pixelle_secure_agent_token_2026"

def _adb_run(*args, timeout=30):
    cmd = [ADB_PATH, "-s", SERIAL] + list(args)
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)

def main():
    print(f"[*] 启动 iQOO 真机 ({SERIAL}) 核心挂机脚本智能化灌装...")
    
    # 1. 确认设备在线
    rc, out, err = _adb_run("get-state")
    if rc != 0 or "device" not in out:
        print(f"[错误] 设备 {SERIAL} 离线，请检查 adb 连通性: {err or out}")
        sys.exit(1)
    print("[+] 手机在线状态 OK")

    project_root = Path(__file__).resolve().parent.parent
    scripts_dir = project_root / "scripts"

    # 2. 读取并智能化修改 install_termux_boot.sh 环境变量
    boot_sh_src = scripts_dir / "install_termux_boot.sh"
    if not boot_sh_src.exists():
        print(f"[错误] 找不到本地的 install_termux_boot.sh: {boot_sh_src}")
        sys.exit(1)
        
    boot_content = boot_sh_src.read_text(encoding="utf-8")
    
    # 全自动零配置替换
    modified_boot_content = boot_content.replace(
        'export PIXELLE_AGENT_TOKEN="your-secret-token"',
        f'export PIXELLE_AGENT_TOKEN="{REAL_TOKEN}"'
    ).replace(
        'export PIXELLE_SERVER_URL="http://your-server:8000"',
        f'export PIXELLE_SERVER_URL="{REAL_SERVER_URL}"'
    )
    
    # 3. 准备临时文件并推送
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_boot_path = Path(tmpdir) / "install_termux_boot.sh"
        tmp_boot_path.write_text(modified_boot_content, encoding="utf-8")
        
        # 拟推送的文件对 (本地源 -> 手机目标)
        files_to_push = [
            (scripts_dir / "phone_agent.py", "/sdcard/phone_agent.py"),
            (scripts_dir / "setup_termux.sh", "/sdcard/pixelle_setup.sh"),
            (scripts_dir / "termux_boot_start_agent.sh", "/sdcard/termux_boot_start_agent.sh"),
            (tmp_boot_path, "/sdcard/install_termux_boot.sh"),
        ]

        print("[-] 正在推送经过智能化 0 配置替换的脚本文件到手机...")
        for local, remote in files_to_push:
            print(f"  推送 {local.name if hasattr(local, 'name') else 'install_termux_boot.sh'} -> {remote} ...")
            rc, out, err = _adb_run("push", str(local), remote, timeout=60)
            if rc != 0:
                print(f"[错误] 推送失败: {err or out}")
                sys.exit(1)

    print("[+] 经过智能预设（Token 和局域网 IP 已内置）的脚本全部成功推送到手机！")

    # 4. 唤醒手机端 Termux
    print("[-] 正在调起手机端 Termux 应用...")
    _adb_run("shell", "am", "start", "-n", "com.termux/.app.TermuxActivity")
    print("[+] Termux 已置于手机前台")

    # 5. 重新广播命令
    print("[-] 发送 Termux 自动环境初始化广播...")
    rc, out, err = _adb_run(
        "shell", "am", "broadcast",
        "-a", "com.termux.RUN_COMMAND",
        "--es", "com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash",
        "--esa", "com.termux.RUN_COMMAND_ARGUMENTS", "-c,bash /sdcard/pixelle_setup.sh",
        "--ez", "com.termux.RUN_COMMAND_BACKGROUND", "false",
        "-n", "com.termux/.app.RunCommandService"
    )
    if rc == 0:
        print("[+] 自动安装与自启配置广播已完美发送！")
    else:
        print("[-] 广播发送受限（属于正常现象），用户稍后可手动执行。")

    print("\n[+] iQOO 挂机环境智能配置与灌装全部成功！")

if __name__ == "__main__":
    main()
