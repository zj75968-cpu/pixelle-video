#!/data/data/com.termux/files/usr/bin/bash
# Pixelle Phone Agent - 开机自启脚本
# 存放位置：~/.termux/boot/start_agent.sh
# 依赖：Termux:Boot（F-Droid 安装）
#
# 安装步骤：
#   1. F-Droid 安装 Termux:Boot
#   2. 打开 Termux:Boot 一次（授予权限）
#   3. 运行：bash /sdcard/install_boot.sh
#      （由 Pixelle-Video 一键初始化后自动推送）

# ─── 配置区（首次使用后由 install_boot.sh 自动填写）─────────────
AGENT_TOKEN="${PIXELLE_AGENT_TOKEN:-}"         # 从环境变量读取，或直接填写
PIXELLE_SERVER_URL="${PIXELLE_SERVER_URL:-}"   # Pixelle-Video 服务器地址
AGENT_PORT="${AGENT_PORT:-7777}"
PUSH_DIR="/sdcard/DCIM/PixelleVideo"
LOG_FILE=~/pixelle_agent.log
# ─────────────────────────────────────────────────────────────────

# 等待系统完全启动
sleep 10

# 将标准输出重定向到日志文件
exec >> "$LOG_FILE" 2>&1
echo ""
echo "===== $(date) ====="
echo "Pixelle Phone Agent 开机自启..."

# 检查 phone_agent.py 是否存在
if [ ! -f ~/phone_agent.py ]; then
    echo "❌ ~/phone_agent.py 不存在，请重新初始化"
    exit 1
fi

# 检查 cloudflared
if [ ! -f ~/cloudflared ]; then
    echo "⚠ ~/cloudflared 不存在，将不使用穿透"
    AUTO_CF=""
else
    AUTO_CF="--auto-cloudflare"
fi

# 构建启动命令
CMD="python ~/phone_agent.py --token $AGENT_TOKEN --port $AGENT_PORT --push-dir $PUSH_DIR"

if [ -n "$AUTO_CF" ]; then
    CMD="$CMD $AUTO_CF"
fi

if [ -n "$PIXELLE_SERVER_URL" ]; then
    CMD="$CMD --pixelle-url $PIXELLE_SERVER_URL"
fi

echo "启动命令: $CMD"
exec $CMD
