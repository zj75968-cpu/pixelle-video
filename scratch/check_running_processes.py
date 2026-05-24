import sys
import subprocess
import socket

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

print("=== Running Python Processes (via tasklist) ===")
try:
    res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"], capture_output=True, text=True, encoding='gbk', errors='ignore')
    print(res.stdout)
except Exception as e:
    print(e)

print("\n=== Checking listening ports ===")
for port in [8000, 8501]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    res = s.connect_ex(('127.0.0.1', port))
    if res == 0:
        print(f"Port {port} is OPEN (listening)")
    else:
        print(f"Port {port} is CLOSED")
    s.close()
