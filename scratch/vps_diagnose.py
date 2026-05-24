import socket
import paramiko
import sys
import yaml

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
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return exit_code, out, err

def main():
    ssh = ssh_connect()
    if not ssh:
        print("Error: Could not connect to VPS.")
        sys.exit(1)
        
    try:
        print("\n=== 1. Check services ===")
        for svc in ["pixelle-api", "pixelle-web"]:
            code, out, err = run_cmd(ssh, f"systemctl status {svc} --no-pager -l")
            print(f"\n--- {svc} Status (exit {code}) ---")
            print("\n".join(out.split("\n")[:15]))
            
        print("\n=== 2. Check config.yaml ===")
        code, out, err = run_cmd(ssh, "cat /root/pixelle-video/config.yaml")
        print(out)
        
        print("\n=== 3. Check registered agent URL in active config / database ===")
        code, out, err = run_cmd(ssh, "ls -la /root/pixelle-video/data/")
        print("Data dir files:")
        print(out)
        
        print("\n=== 4. Check active config.yaml keys related to phone_agent ===")
        # check if phone_agent.url exists in remote config
        
        print("\n=== 5. Check logs of pixelle-api for active devices ===")
        code, out, err = run_cmd(ssh, "journalctl -u pixelle-api -n 40 --no-pager")
        print(out)
        
        print("\n=== 6. Check logs of pixelle-web ===")
        code, out, err = run_cmd(ssh, "journalctl -u pixelle-web -n 40 --no-pager")
        print(out)

    finally:
        ssh.close()

if __name__ == "__main__":
    main()
