#!/data/data/com.termux/files/usr/bin/bash
# Pixelle Phone Agent - Termux 一键灌装 + 自动挂机脚本
# ---------------------------------------------------------
# 使用方式（手机 Termux 中）：
#     curl http://<VPS>/s | bash
#   或：
#     curl -sSL http://<VPS>/api/phone-agent/setup | bash
#   若 curl 损坏，可用：
#     wget -O - http://<VPS>/s | bash
#
# 该脚本会：
#   1. 安装 Termux 依赖（python / flask / requests / wget / cloudflared）
#   2. 从 VPS 拉取最新 phone_agent.py
#   3. 在 ~/.pixelle.env 中固化 PIXELLE_URL 与 PIXELLE_TOKEN
#   4. 生成 ~/start.sh 与 `start` 命令（写入 ~/.bashrc）
#   5. 立即启动一次 phone_agent（自带 cloudflared 隧道 + 自动注册到 VPS）
#
# 服务器侧渲染时会将 __PIXELLE_URL__ / __PIXELLE_TOKEN__ 替换为真实值。
# 如果脚本是手动下载的（占位符未替换），可通过环境变量或 CLI 参数覆盖：
#     PIXELLE_URL=http://1.2.3.4 PIXELLE_TOKEN=mytoken bash setup_termux.sh

set -e

# ---------- 0. 解析配置（优先级：CLI > env > 模板占位符 > 兜底） ----------
RAW_URL="__PIXELLE_URL__"
RAW_TOKEN="__PIXELLE_TOKEN__"
PLACEHOLDER_URL="__PIXELLE_URL""__"
PLACEHOLDER_TOKEN="__PIXELLE_TOKEN""__"

# 占位符未被替换时清空，便于走环境变量/参数
[ "$RAW_URL" = "$PLACEHOLDER_URL" ] && RAW_URL=""
[ "$RAW_TOKEN" = "$PLACEHOLDER_TOKEN" ] && RAW_TOKEN=""

PIXELLE_URL="${1:-${PIXELLE_URL:-$RAW_URL}}"
PIXELLE_TOKEN="${2:-${PIXELLE_TOKEN:-$RAW_TOKEN}}"

if [ -z "$PIXELLE_URL" ]; then
    echo "❌ 未能确定 Pixelle-Video VPS 地址"
    echo "   请使用： curl http://<你的VPS>/s | bash"
    echo "   如果 curl 报 CANNOT LINK EXECUTABLE： wget -O - http://<你的VPS>/s | bash"
    echo "   或：    PIXELLE_URL=http://<你的VPS> bash setup_termux.sh"
    exit 1
fi
PIXELLE_URL="${PIXELLE_URL%/}"   # 去掉结尾的斜杠

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Pixelle Phone Agent - 一键灌装中...             ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  VPS 地址  : $PIXELLE_URL"
if [ -n "$PIXELLE_TOKEN" ]; then
    echo "  Token     : (已注入，长度 ${#PIXELLE_TOKEN})"
else
    echo "  Token     : (未配置，将以无鉴权模式运行)"
fi
echo ""

# ---------- 1. 申请存储权限（首次需要用户在弹窗中点击允许） ----------
if [ ! -d "$HOME/storage" ]; then
    echo "[1/6] 申请存储权限..."
    termux-setup-storage 2>/dev/null || true
fi

# ---------- 2. 更新 Termux 包索引 + 装 python / wget ----------
echo "[2/6] 安装 Termux 基础依赖（python / pip / wget / proot）..."
APT_SOURCES="${PREFIX:-/data/data/com.termux/files/usr}/etc/apt/sources.list"
APT_DIR="$(dirname "$APT_SOURCES")"
if [ -d "$APT_DIR" ] && { [ ! -s "$APT_SOURCES" ] || ! grep -q "termux-main" "$APT_SOURCES" 2>/dev/null; }; then
    cat > "$APT_SOURCES" <<'EOF_APT'
deb https://packages.termux.dev/apt/termux-main stable main
EOF_APT
    echo "  已写入 Termux 官方软件源: $APT_SOURCES"
fi

if ! apt update -y >/dev/null 2>&1; then
    echo "  apt update 失败，尝试切换到清华镜像..."
    cat > "$APT_SOURCES" <<'EOF_APT'
deb https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main stable main
EOF_APT
    apt update -y >/dev/null 2>&1
fi

apt install -y python python-pip wget proot ca-certificates openssl >/dev/null 2>&1

fix_termux_dns() {
    DNS_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/resolv.conf"
    DNS_DIR="$(dirname "$DNS_FILE")"
    if [ -d "$DNS_DIR" ]; then
        if [ ! -s "$DNS_FILE" ] || grep -Eq 'nameserver[[:space:]]+(127\.|::1|0\.0\.0\.0)' "$DNS_FILE" 2>/dev/null; then
            cat > "$DNS_FILE" <<'EOF_DNS'
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 223.5.5.5
EOF_DNS
            echo "  已修复 Termux DNS: $DNS_FILE"
        fi
    fi
}
fix_termux_dns

download_url() {
    URL="$1"
    DEST="$2"
    if command -v wget >/dev/null 2>&1; then
        wget -q "$URL" -O "$DEST"
        return $?
    fi
    if command -v python >/dev/null 2>&1; then
        python - "$URL" "$DEST" <<'PY_DOWNLOAD'
import sys
import urllib.request

url, dest = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=60) as resp:
    data = resp.read()
with open(dest, "wb") as f:
    f.write(data)
PY_DOWNLOAD
        return $?
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "$DEST"
        return $?
    fi
    return 127
}

# ---------- 3. 安装 Python 依赖 ----------
echo "[3/6] 安装 Python 依赖（flask / requests）..."
python -m pip install --quiet flask requests

# ---------- 4. 下载 cloudflared ----------
echo "[4/6] 下载 cloudflared..."
ARCH="$(uname -m)"
case "$ARCH" in
    aarch64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    armv7l)  CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm" ;;
    *)       CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
esac

CF_BIN="$HOME/cloudflared-bin"
CF_WRAPPER="$HOME/cloudflared"
install_cloudflared_wrapper() {
    cat > "$CF_WRAPPER" <<'EOF_CF_WRAPPER'
#!/data/data/com.termux/files/usr/bin/bash
CF_BIN="$HOME/cloudflared-bin"
DNS_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/resolv.conf"
CERT_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/tls/cert.pem"

if command -v proot >/dev/null 2>&1 && [ -s "$DNS_FILE" ]; then
    [ -s "$CERT_FILE" ] && export SSL_CERT_FILE="$CERT_FILE"
    exec proot -b "$DNS_FILE:/etc/resolv.conf" "$CF_BIN" "$@"
fi

exec "$CF_BIN" "$@"
EOF_CF_WRAPPER
    chmod +x "$CF_WRAPPER"
}

if [ -x "$CF_BIN" ]; then
    echo "  cloudflared-bin 已存在，跳过下载"
elif [ -x "$CF_WRAPPER" ] && ! head -n 1 "$CF_WRAPPER" 2>/dev/null | grep -q '^#!'; then
    mv "$CF_WRAPPER" "$CF_BIN"
    chmod +x "$CF_BIN"
    echo "  已迁移旧 cloudflared 二进制到 $CF_BIN"
elif [ -f "/sdcard/cloudflared" ]; then
    cp "/sdcard/cloudflared" "$CF_BIN"
    chmod +x "$CF_BIN"
    echo "  已从 /sdcard/cloudflared 安装到 $CF_BIN"
else
    download_url "$CF_URL" "$CF_BIN"
    chmod +x "$CF_BIN"
    echo "  cloudflared 下载完成（$ARCH）"
fi
install_cloudflared_wrapper

# ---------- 5. 从 VPS 拉取最新 phone_agent.py ----------
echo "[5/6] 从 VPS 拉取 phone_agent.py..."
AGENT_URL="${PIXELLE_URL}/api/phone-agent/agent-script"
if ! download_url "$AGENT_URL" "$HOME/phone_agent.py"; then
    echo "❌ 下载 phone_agent.py 失败：$AGENT_URL"
    echo "   请确认 VPS 端 FastAPI 已重启并加载最新代码。"
    exit 1
fi
chmod +x "$HOME/phone_agent.py"

# ---------- 6. 写入配置 + 生成 start.sh + 注入 bashrc 别名 ----------
echo "[6/6] 写入 ~/.pixelle.env + 生成 start.sh ..."
cat > "$HOME/.pixelle.env" <<EOF
# Pixelle Phone Agent 配置（由 setup_termux.sh 自动生成，可手动编辑）
export PIXELLE_URL="$PIXELLE_URL"
export PIXELLE_TOKEN="$PIXELLE_TOKEN"
export AGENT_PORT="${AGENT_PORT:-7777}"
EOF
chmod 600 "$HOME/.pixelle.env"

cat > "$HOME/start.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Pixelle Phone Agent 启动入口
# - 加载 ~/.pixelle.env
# - 启动 phone_agent.py（自动开启 cloudflared 隧道并把 URL 上报到 VPS）
set -e

[ -f "$HOME/.pixelle.env" ] && . "$HOME/.pixelle.env"

: "${PIXELLE_URL:?未配置 PIXELLE_URL，请重跑 setup}"
: "${AGENT_PORT:=7777}"

echo "[start] Pixelle-Video VPS = $PIXELLE_URL"
echo "[start] 本地端口          = $AGENT_PORT"
echo "[start] 正在启动 phone_agent + cloudflared，自动上报 URL ..."

# 让 cloudflared 在 PATH 里
export PATH="$HOME:$PATH"
if [ ! -x "$HOME/cloudflared-bin" ] && [ -f "/sdcard/cloudflared" ]; then
    cp "/sdcard/cloudflared" "$HOME/cloudflared-bin"
    chmod +x "$HOME/cloudflared-bin"
    echo "[start] 已从 /sdcard/cloudflared 安装 cloudflared-bin"
fi
if [ -x "$HOME/cloudflared-bin" ]; then
    cat > "$HOME/cloudflared" <<'EOF_CF_WRAPPER'
#!/data/data/com.termux/files/usr/bin/bash
CF_BIN="$HOME/cloudflared-bin"
DNS_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/resolv.conf"
CERT_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/tls/cert.pem"

if command -v proot >/dev/null 2>&1 && [ -s "$DNS_FILE" ]; then
    [ -s "$CERT_FILE" ] && export SSL_CERT_FILE="$CERT_FILE"
    exec proot -b "$DNS_FILE:/etc/resolv.conf" "$CF_BIN" "$@"
fi

exec "$CF_BIN" "$@"
EOF_CF_WRAPPER
    chmod +x "$HOME/cloudflared"
fi

DNS_FILE="${PREFIX:-/data/data/com.termux/files/usr}/etc/resolv.conf"
DNS_DIR="$(dirname "$DNS_FILE")"
if [ -d "$DNS_DIR" ] && { [ ! -s "$DNS_FILE" ] || grep -Eq 'nameserver[[:space:]]+(127\.|::1|0\.0\.0\.0)' "$DNS_FILE" 2>/dev/null; }; then
    cat > "$DNS_FILE" <<'EOF_DNS'
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 223.5.5.5
EOF_DNS
    echo "[start] 已修复 Termux DNS: $DNS_FILE"
fi

exec python "$HOME/phone_agent.py" \
    --token "$PIXELLE_TOKEN" \
    --port "$AGENT_PORT" \
    --auto-cloudflare \
    --pixelle-url "$PIXELLE_URL"
EOF
chmod +x "$HOME/start.sh"

# 在 ~/.bashrc 中注入 start 别名（去重）
BASHRC="$HOME/.bashrc"
touch "$BASHRC"
if ! grep -q "alias start=" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# >>> pixelle phone agent >>>" >> "$BASHRC"
    echo "alias start='bash ~/start.sh'" >> "$BASHRC"
    echo "# <<< pixelle phone agent <<<" >> "$BASHRC"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ 灌装完成！正在首次启动并上报 URL ...         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "之后任何时候，只需在 Termux 中输入   start   即可重新挂机。"
echo "如想停止挂机，按 Ctrl+C 即可。"
echo ""

# ---------- 自动首次启动（前台运行，让用户能看到 [report] ✅ 日志） ----------
exec bash "$HOME/start.sh"

