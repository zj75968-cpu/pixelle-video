import subprocess
import os
import sys

SERIAL = "10ACBE28M70044L"
ADB_PATH = r"C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE"

if not os.path.exists(ADB_PATH):
    ADB_PATH = "adb"

def _adb_run(*args):
    cmd = [ADB_PATH, "-s", SERIAL] + list(args)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)

def main():
    print("Checking running processes on Android device:")
    rc, out, err = _adb_run("shell", "ps -ef | grep -E 'termux|python|cloudflared|wget|bash'")
    print(out)
    if err:
        print("Error:", err)

if __name__ == "__main__":
    main()
