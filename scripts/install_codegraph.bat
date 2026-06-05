@echo off
REM CodeGraph 安装脚本 - 自动配置到 Claude Code

echo ==========================================
echo CodeGraph 安装向导
echo ==========================================
echo.
echo CodeGraph 已检测到以下 AI 助手:
echo   [x] Claude Code
echo   [x] Cursor
echo   [x] Codex CLI
echo   [x] Gemini CLI
echo   [x] Antigravity IDE
echo   [x] Kiro
echo.
echo 正在为 Claude Code 和 Kiro 安装 CodeGraph...
echo.

cd "F:\codex project\小红书"
codegraph install

echo.
echo ==========================================
echo 安装完成！
echo ==========================================
echo.
echo CodeGraph 功能:
echo   - 语义代码搜索
echo   - 依赖关系分析
echo   - 调用链追踪
echo   - 影响分析
echo.
echo 重启 Claude Code 后生效
echo.
pause
