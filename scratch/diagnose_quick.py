import paramiko
import socket
import sys

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
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    print("STDOUT:")
    print(out)
    if err:
        print("STDERR:")
        print(err)
    return out

def main():
    ssh = ssh_connect()
    if not ssh:
        sys.exit(1)
        
    run_cmd(ssh, "docker logs infra_nginx_1 --tail 50")
    run_cmd(ssh, "curl -sI http://127.0.0.1:8501/")
    run_cmd(ssh, "curl -sI http://172.19.0.1:8501/")
    run_cmd(ssh, "iptables -t nat -L -n -v")
    
    ssh.close()

if __name__ == "__main__":
    main()
