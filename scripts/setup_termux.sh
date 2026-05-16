#!/data/data/com.termux/files/usr/bin/bash
# Pixelle Phone Agent - Termux 初始化脚本
# 使用方式：在 Termux 中执行  bash /sdcard/pixelle_setup.sh

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Pixelle Phone Agent - 初始化中...       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 1. 更新包列表
echo "[1/5] 更新 Termux 包列表..."
pkg update -y 2>&1 | tail -3

# 2. 安装 Python
echo "[2/5] 安装 Python..."
pkg install python wget -y 2>&1 | tail -3

# 3. 安装 Flask
echo "[3/5] 安装 Flask..."
pip install flask --quiet

# 4. 下载 cloudflared
echo "[4/5] 下载 cloudflared..."
ARCH=$(uname -m)
case "$ARCH" in
    aarch64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    armv7l)  CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm" ;;
    *)       CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
esac

if [ -f ~/cloudflared ]; then
    echo "  cloudflared 已存在，跳过下载"
else
    wget -q "$CF_URL" -O ~/cloudflared && chmod +x ~/cloudflared
    echo "  cloudflared 下载完成 ($ARCH)"
fi

# 5. 复制 phone_agent.py
echo "[5/5] 安装 phone_agent..."
cp /sdcard/phone_agent.py ~/phone_agent.py
chmod +x ~/phone_agent.py

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ 初始化完成！                         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "手动启动（将 TOKEN 替换为你设置的密钒）："
echo ""
echo "  窗口1：python ~/phone_agent.py --token TOKEN --port 7777"
echo "  窗口2：~/cloudflared tunnel --url http://localhost:7777"
echo ""
echo "将 cloudflared 输出的 URL 填入 Pixelle-Video 设置页即可。"
echo ""
echo "开机自动启动（可选，需要 Termux:Boot）："
echo "  bash /sdcard/install_termux_boot.sh"
