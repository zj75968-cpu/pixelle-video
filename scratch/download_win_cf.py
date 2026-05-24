import sys
import os
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CF_WIN_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
DEST_PATH = Path.home() / "cloudflared.exe"

def main():
    print(f"[*] 开始下载 Windows 64位 cloudflared.exe ...")
    print(f"  目标路径: {DEST_PATH}")
    
    if DEST_PATH.exists():
        print("[+] 预装包已存在，跳过下载。")
        sys.exit(0)
        
    try:
        def _progress(count, block_size, total_size):
            if total_size > 0 and count % 100 == 0:
                pct = min(100, count * block_size * 100 // total_size)
                print(f"  [下载进度] {pct}%")
                
        urllib.request.urlretrieve(CF_WIN_URL, str(DEST_PATH), _progress)
        print("[+] 电脑端 Windows cloudflared.exe 下载成功！")
    except Exception as e:
        print(f"[错误] 下载 Windows cloudflared 失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
