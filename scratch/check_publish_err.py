import socket
import paramiko
import sys

HOST = "23.238.47.62"
PORT = 22
USER = "root"
PASS = "A5WwhvG117gvXrE00P"

def main():
    print("Connecting to VPS SSH...", flush=True)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.bind(("192.168.1.2", 0))
        s.connect((HOST, PORT))
        ssh.connect(HOST, port=PORT, username=USER, password=PASS, sock=s, timeout=15)
        print("Connected!", flush=True)
    except Exception as e:
        print(f"Failed to connect: {e}", flush=True)
        sys.exit(1)

    try:
        # Run runpy check on remote VPS
        cmd = "/root/pixelle-video/.venv/bin/python -c \"import sys; sys.path.insert(0, '/root/pixelle-video'); import runpy; runpy.run_path('/root/pixelle-video/web/views/4_Publish.py')\""
        print(f"Executing: {cmd}", flush=True)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        
        print(f"\nExit Code: {exit_code}")
        if out:
            print("STDOUT:")
            print(out)
        if err:
            print("STDERR (Errors):")
            print(err)
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
