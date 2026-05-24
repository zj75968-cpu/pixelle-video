import sys
import os
import urllib.request
import subprocess
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SERIAL = "10ACBE28M70044L"
ADB_PATH = r"C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE"

if not os.path.exists(ADB_PATH):
    ADB_PATH = "adb"

CF_ARM64_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
LOCAL_CF_PATH = Path(__file__).resolve().parent.parent / "resources" / "cloudflared-linux-arm64"

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
    print("[*] 启动 Cloudflared 预装包极速灌装...")
    
    # 创建本地 resources 目录（如果不存在）
    LOCAL_CF_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. 检查本地是否已经有下载好的包
    if not LOCAL_CF_PATH.exists():
        print(f"[-] 本地未发现 ARM64 预装包，正在通过电脑网络下载: {CF_ARM64_URL}")
        try:
            def _progress(count, block_size, total_size):
                if total_size > 0 and count % 100 == 0:
                    pct = min(100, count * block_size * 100 // total_size)
                    print(f"  [下载进度] {pct}%")
            
            urllib.request.urlretrieve(CF_ARM64_URL, str(LOCAL_CF_PATH), _progress)
            print("[+] 电脑端下载 ARM64 cloudflared 成功！")
        except Exception as e:
            print(f"[警告] 电脑端下载失败，可能存在网络限制: {e}")
            print("[-] 我们将跳过电脑端预装包推送，依靠手机 Termux 本地自行下载（网络差时可能会卡住）。")
            sys.exit(0)
    else:
        print("[+] 发现本地已缓存的 ARM64 cloudflared 包。")

    # 2. 强行推送到手机 /sdcard/cloudflared
    print(f"[-] 正在推送预装包到手机: {LOCAL_CF_PATH.name} -> /sdcard/cloudflared ...")
    rc, out, err = _adb_run("push", str(LOCAL_CF_PATH), "/sdcard/cloudflared", timeout=120)
    if rc == 0:
        print("[+] 手机端 Cloudflared 预装包推送成功！")
    else:
        print(f"[错误] 推送预装包失败: {err or out}")

if __name__ == "__main__":
    main()
