@echo off
chcp 65001 >nul
echo ========================================
echo   CH9329 可视化调试工作台启动器
echo ========================================
echo.

cd /d "%~dp0\.."

echo [1/2] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

echo [2/2] 启动可视化工作台...
echo.
echo 💡 提示：
echo   - 鼠标悬停在截图上可以看到实时坐标
echo   - 点击截图会物理点击手机对应位置
echo   - 拖拽可以实现滑动手势
echo   - 点击后可以保存为语义点
echo.

python scripts\ch9329_visual_debug.py

if errorlevel 1 (
    echo.
    echo ❌ 启动失败，请检查依赖是否安装完整
    pause
)
