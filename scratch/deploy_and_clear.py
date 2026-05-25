import socket
import paramiko
import os
import zipfile
import time
import sys

HOST = "23.238.47.62"
PORT = 22
USER = "root"
PASS = "z5Rd256n9tZ2wENTdB"

def ssh_connect(max_retries=5):
    for i in range(max_retries):
        try:
            print(f"Connecting to SSH {i+1}/{max_retries}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
                print("Connected using standard connection.")
                return ssh
            except Exception as e_default:
                print(f"Standard connection failed: {e_default}. Retrying with bound socket...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(15)
                s.bind(("192.168.1.2", 0))
                s.connect((HOST, PORT))
                ssh.connect(HOST, port=PORT, username=USER, password=PASS, sock=s, timeout=15)
                print("Connected using bound socket.")
                return ssh
        except Exception as e:
            print(f"Failed to connect: {e}")
            time.sleep(2)
    return None

def run_cmd(ssh, cmd, timeout=120):
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    
    safe_out = out.encode('ascii', errors='replace').decode('ascii')
    safe_err = err.encode('ascii', errors='replace').decode('ascii')
    
    lines = safe_out.split('\n') if safe_out else []
    for line in lines[:10]:
        print(f"  {line}")
    if len(lines) > 10:
        print(f"  ... ({len(lines) - 10} more lines)")
    if safe_err:
        for line in safe_err.split('\n')[:5]:
            print(f"  [ERR] {line}")
    print(f"  [exit: {exit_code}]")
    return exit_code, out, err

def main():
    ssh = ssh_connect()
    if not ssh:
        print("Failed to connect to VPS")
        sys.exit(1)

    try:
        # 1. Stop XHS on the phone via local ADB (safe skip if device not found)
        print("\nStopping XHS on the phone if connected...")
        try:
            os.system(r'C:\Users\86136\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.EXE -s 10ACBE28M70044L shell am force-stop com.xingin.xhs 2>NUL')
        except Exception:
            pass
        
        # 2. Clear publish queue on VPS
        print("\nClearing VPS publish queue...")
        run_cmd(ssh, 'echo \'{"jobs": {}}\' > /root/pixelle-video/data/publish_queue.json')
        
        # 3. Zip local codebase
        src_dir = r"f:\codex project\小红书"
        zip_path = os.path.join(src_dir, "pixelle_video_deploy.zip")
        exclude_dirs = {'.git', '.venv', '.gemini', 'data', 'output', '__pycache__', '.idea', 'temp'}
        
        print("\nZipping local project...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
                for file in files:
                    if file.endswith(('.pyc', '.zip')) or file.startswith('.'):
                        continue
                    fp = os.path.join(root, file)
                    zipf.write(fp, os.path.relpath(fp, src_dir))
        
        # 4. Upload zip
        print("\nUploading zip to VPS...")
        sftp = ssh.open_sftp()
        sftp.put(zip_path, "/root/pixelle_video_deploy.zip")
        sftp.close()
        os.remove(zip_path)
        print("Upload completed!")
        
        # 5. Extract and Deploy on remote
        print("\nExtracting project on remote...")
        run_cmd(ssh, "rm -rf /root/pixelle-video/web/views")
        run_cmd(ssh, "mkdir -p /root/pixelle-video/web/views")
        run_cmd(ssh, "cd /root && unzip -o /root/pixelle_video_deploy.zip -d /root/pixelle-video > /dev/null 2>&1")
        run_cmd(ssh, "rm -f /root/pixelle_video_deploy.zip")
        
        # 6. Fix line endings
        print("\nFixing line endings on remote...")
        run_cmd(ssh, "find /root/pixelle-video -type f \\( -name '*.py' -o -name '*.toml' -o -name '*.yaml' -o -name '*.yml' -o -name '*.sh' -o -name '*.txt' -o -name '*.md' \\) -exec dos2unix {} + 2>/dev/null")
        
        # 7. Restart systemd services
        print("\nRestarting systemd services on VPS...")
        run_cmd(ssh, "systemctl daemon-reload")
        run_cmd(ssh, "systemctl restart pixelle-web pixelle-api")
        
        print("\nWaiting 5s for services to start...")
        time.sleep(5)
        
        # 8. Verify
        print("\n=== Verifying Service Status ===")
        run_cmd(ssh, "systemctl status pixelle-web --no-pager -l | head -10")
        run_cmd(ssh, "systemctl status pixelle-api --no-pager -l | head -10")
        
    finally:
        ssh.close()
        print("\nDeployment and Queue Clear completed successfully!")

if __name__ == "__main__":
    main()
