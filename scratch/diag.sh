#!/data/data/com.termux/files/usr/bin/bash
echo "[*] Killing old instances..."
pkill -9 -f python || true
pkill -9 -f phone_agent || true
sleep 1

echo "[*] Starting phone agent with logs redirected to /sdcard/python_log.txt ..."
nohup python /data/data/com.termux/files/home/phone_agent.py --token pixelle_secure_agent_token_2026 --port 7777 --auto-cloudflare --pixelle-url http://23.238.47.62 > /sdcard/python_log.txt 2>&1 &
sleep 2
echo "[*] Diagnostic setup completed"
