import socket
import paramiko
import sys

HOST = "23.238.47.62"
PORT = 22
USER = "root"
PASS = "A5WwhvG117gvXrE00P"

def ssh_connect(max_retries=3):
    for i in range(max_retries):
        try:
            print(f"Connecting to SSH {i+1}/{max_retries}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
                print("Connected using standard connection.")
                return ssh
            except Exception as e_default:
                print(f"Standard connection failed: {e_default}. Retrying with bound socket...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10)
                s.bind(("192.168.1.2", 0))
                s.connect((HOST, PORT))
                ssh.connect(HOST, port=PORT, username=USER, password=PASS, sock=s, timeout=10)
                print("Connected using bound socket.")
                return ssh
        except Exception as e:
            print(f"Failed to connect: {e}")
    return None

def run_cmd(ssh, cmd):
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    if err:
        print(f"[ERR] {err}")

def main():
    ssh = ssh_connect()
    if not ssh:
        print("Could not connect to VPS")
        sys.exit(1)
        
    try:
        run_cmd(ssh, "ss -tulpn")
        run_cmd(ssh, "docker ps -a")
        run_cmd(ssh, "curl -sI http://127.0.0.1/")
        run_cmd(ssh, "curl -sI https://web.23-238-47-62.sslip.io/ --insecure")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
