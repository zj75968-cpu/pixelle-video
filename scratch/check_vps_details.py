import socket
import paramiko
import sys

HOST = "23.238.47.62"
PORT = 22
USER = "root"
PASS = "A5WwhvG117gvXrE00P"

def run_remote_cmd(ssh, cmd):
    print(f"\n>>> {cmd}", flush=True)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    print(f"[Exit Code: {exit_code}]")
    if out:
        print("STDOUT:")
        print(out)
    if err:
        print("STDERR:")
        print(err)

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.bind(("192.168.1.2", 0))
        s.connect((HOST, PORT))
        ssh.connect(HOST, port=PORT, username=USER, password=PASS, sock=s, timeout=15)
        print("Connected to VPS!", flush=True)
    except Exception as e:
        print(f"Failed to connect: {e}", flush=True)
        sys.exit(1)

    try:
        # Search for '新建' (new) or '定时' (schedule) in remote 4_Publish.py to ensure they're removed
        run_remote_cmd(ssh, "grep -n '新建' /root/pixelle-video/web/views/4_Publish.py")
        run_remote_cmd(ssh, "grep -n '定时' /root/pixelle-video/web/views/4_Publish.py")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
