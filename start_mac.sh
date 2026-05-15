#!/bin/bash
# ============================================================
# Pixelle-Video — Mac mini 一键启动脚本
# 同时启动 Streamlit + Cloudflare Tunnel，并显示公网地址
# 用法：chmod +x start_mac.sh && ./start_mac.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── 颜色输出 ───────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERR]${RESET}  $*"; }

# ─── 检查依赖 ───────────────────────────────────────────────
check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "$1 未找到，请先安装：$2"
    exit 1
  fi
}

check_cmd cloudflared "brew install cloudflared"
check_cmd adb         "brew install android-platform-tools"

# ─── 检查配置文件 ────────────────────────────────────────────
if [ ! -f "config.yaml" ]; then
  warn "config.yaml 不存在，正在从 config.example.yaml 复制…"
  cp config.example.yaml config.yaml
  warn "请先编辑 config.yaml 填入 API Key 等配置，然后重新运行本脚本。"
  open -a TextEdit config.yaml 2>/dev/null || nano config.yaml
  exit 1
fi

# ─── 激活虚拟环境（优先 uv，其次 .venv）─────────────────────
STREAMLIT_CMD=""
if command -v uv &>/dev/null; then
  info "使用 uv 运行 Streamlit"
  STREAMLIT_CMD="uv run streamlit run web/app.py --server.port 8501"
elif [ -f ".venv/bin/activate" ]; then
  info "激活 .venv 虚拟环境"
  source .venv/bin/activate
  STREAMLIT_CMD="streamlit run web/app.py --server.port 8501"
else
  info "未检测到 .venv，尝试用系统 Python"
  STREAMLIT_CMD="python3 -m streamlit run web/app.py --server.port 8501"
fi

# ─── 日志目录 ────────────────────────────────────────────────
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
STREAMLIT_LOG="$LOG_DIR/streamlit.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"

# ─── 清理旧进程 ──────────────────────────────────────────────
cleanup() {
  info "正在停止所有服务…"
  [ -n "$STREAMLIT_PID" ] && kill "$STREAMLIT_PID" 2>/dev/null && success "Streamlit 已停止"
  [ -n "$TUNNEL_PID"    ] && kill "$TUNNEL_PID"    2>/dev/null && success "Cloudflare Tunnel 已停止"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ─── 启动 Streamlit ─────────────────────────────────────────
info "启动 Streamlit…（日志：$STREAMLIT_LOG）"
eval "$STREAMLIT_CMD" > "$STREAMLIT_LOG" 2>&1 &
STREAMLIT_PID=$!

# 等待 Streamlit 就绪
info "等待 Streamlit 启动（最多 30 秒）…"
for i in $(seq 1 30); do
  if curl -s http://localhost:8501/_stcore/health &>/dev/null; then
    success "Streamlit 已就绪 → http://localhost:8501"
    break
  fi
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    error "Streamlit 启动失败，查看日志：$STREAMLIT_LOG"
    cat "$STREAMLIT_LOG" | tail -20
    exit 1
  fi
  sleep 1
done

# ─── 启动 Cloudflare Tunnel ──────────────────────────────────
info "启动 Cloudflare Tunnel…（日志：$TUNNEL_LOG）"
cloudflared tunnel --url http://localhost:8501 > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

# 等待 Tunnel 地址出现（最多 20 秒）
info "等待 Cloudflare Tunnel 分配公网地址…"
PUBLIC_URL=""
for i in $(seq 1 20); do
  PUBLIC_URL=$(grep -oE 'https://[a-z0-9\-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
  if [ -n "$PUBLIC_URL" ]; then
    break
  fi
  sleep 1
done

# ─── 显示结果 ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}============================================${RESET}"
echo -e "${GREEN}  Pixelle-Video 启动成功！${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo -e "  本机访问：${CYAN}http://localhost:8501${RESET}"
if [ -n "$PUBLIC_URL" ]; then
  echo -e "  公网地址：${YELLOW}${PUBLIC_URL}${RESET}"
  # 复制到剪贴板（macOS）
  echo -n "$PUBLIC_URL" | pbcopy 2>/dev/null && echo -e "  ${GREEN}✓ 公网地址已复制到剪贴板${RESET}"
else
  warn "未能获取公网地址，查看日志：$TUNNEL_LOG"
  warn "可能原因：网络问题 / cloudflared 启动慢，请稍等片刻后查看 $TUNNEL_LOG"
fi
echo -e "${BOLD}============================================${RESET}"
echo ""
echo -e "  按 ${RED}Ctrl+C${RESET} 停止所有服务"
echo ""

# ─── 保持运行，监控子进程 ────────────────────────────────────
while true; do
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    error "Streamlit 意外退出！查看日志：$STREAMLIT_LOG"
    cleanup
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    warn "Cloudflare Tunnel 意外退出，正在重启…"
    cloudflared tunnel --url http://localhost:8501 >> "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
  fi
  sleep 5
done
