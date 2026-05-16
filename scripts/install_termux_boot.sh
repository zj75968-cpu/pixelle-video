#!/data/data/com.termux/files/usr/bin/bash
# 将 start_agent.sh 安装为 Termux:Boot 开机自启脚本
# 由 Pixelle-Video 一键初始化功能自动推送并运行

echo "=== 安装开机自启脚本 ==="

BOOT_DIR=~/.termux/boot
mkdir -p "$BOOT_DIR"

# 复制启动脚本
cp /sdcard/termux_boot_start_agent.sh "$BOOT_DIR/start_agent.sh"
chmod +x "$BOOT_DIR/start_agent.sh"

echo "✅ 开机自启脚本已安装到 $BOOT_DIR/start_agent.sh"
echo ""

# 写入环境变量配置（用户下次修改配置时只改这个文件）
ENV_FILE=~/.pixelle_agent_env
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
# Pixelle Phone Agent 环境变量
# 修改后重启 Termux 或执行 source ~/.pixelle_agent_env 生效
export PIXELLE_AGENT_TOKEN="your-secret-token"    # 与 Pixelle-Video 设置页保持一致
export PIXELLE_SERVER_URL="http://your-server:8000"  # Pixelle-Video API 地址（可选）
export AGENT_PORT="7777"
EOF
    echo "📝 环境变量模板已写入 $ENV_FILE"
    echo "   请编辑该文件填写正确的 Token 和服务器地址"
fi

# 将环境变量加载写入 .bashrc
if ! grep -q "pixelle_agent_env" ~/.bashrc 2>/dev/null; then
    echo "[ -f ~/.pixelle_agent_env ] && source ~/.pixelle_agent_env" >> ~/.bashrc
    echo "✅ 已将环境变量加载添加到 ~/.bashrc"
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "接下来："
echo "  1. 编辑 ~/.pixelle_agent_env 填写 Token 和服务器地址"
echo "  2. 重启手机，Pixelle Agent 将自动启动"
echo "  3. 在 Pixelle-Video 设置页查看/更新 Agent URL"
