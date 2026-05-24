import paramiko
import socket
import sys
import json

HOST = "23.238.47.62"
PORT = 22
USER = "root"
PASS = "A5WwhvG117gvXrE00P"

def ssh_connect():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.bind(("192.168.1.2", 0))
        s.connect((HOST, PORT))
        ssh.connect(HOST, port=PORT, username=USER, password=PASS, sock=s, timeout=15)
        print("Connected.")
        return ssh
    except Exception as e:
        print(f"Failed to connect: {e}")
        return None

def run_cmd(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    return out

def main():
    ssh = ssh_connect()
    if not ssh:
        sys.exit(1)
        
    print("Checking /phone-agent/status via curl on VPS:")
    status = run_cmd(ssh, "curl -s http://127.0.0.1:8000/api/phone-agent/status")
    print(status)
    
    print("\nChecking tail of pixelle-api.log:")
    logs = run_cmd(ssh, "journalctl -u pixelle-api -n 30 --no-pager")
    print(logs)
    
    ssh.close()

if __name__ == "__main__":
    main()
