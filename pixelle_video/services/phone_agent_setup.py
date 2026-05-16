"""
Phone Agent One-Click Setup
============================
通过 ADB 将 phone_agent.py 和 setup_termux.sh 推送到手机，
并引导用户在 Termux 中完成一键安装。

核心功能：
    setup_phone_agent(serial)       → 推送文件 + 打开 Termux + 返回操作指引
    install_termux_via_adb(serial)  → 自动下载 Termux APK 并通过 ADB 安装
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from loguru import logger

# 脚本所在目录（Pixelle-Video/scripts/）
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
_PHONE_AGENT_PY = _SCRIPTS_DIR / "phone_agent.py"
_SETUP_SH = _SCRIPTS_DIR / "setup_termux.sh"
_BOOT_SCRIPT = _SCRIPTS_DIR / "termux_boot_start_agent.sh"
_INSTALL_BOOT_SH = _SCRIPTS_DIR / "install_termux_boot.sh"

# Termux 包名
TERMUX_PACKAGE = "com.termux"

# Termux GitHub releases API（获取最新版本）
_TERMUX_RELEASE_API = "https://api.github.com/repos/termux/termux-app/releases/latest"


def _adb(serial: str, *args: str, timeout: int = 30) -> tuple[int, str, str]:
    """执行 ADB 命令，返回 (returncode, stdout, stderr)。"""
    try:
        from pixelle_video.services.device_manager import device_manager
        adb_cmd = device_manager.get_adb_command()
    except Exception:
        adb_cmd = "adb"

    cmd = [adb_cmd, "-s", serial] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def is_termux_installed(serial: str) -> bool:
    """检查 Termux 是否已安装。"""
    rc, out, _ = _adb(serial, "shell", "pm", "list", "packages", TERMUX_PACKAGE)
    return rc == 0 and TERMUX_PACKAGE in out


def get_device_abi(serial: str) -> str:
    """获取设备 CPU 架构，返回 ABI 字符串，如 arm64-v8a / armeabi-v7a / x86_64。"""
    rc, out, _ = _adb(serial, "shell", "getprop", "ro.product.cpu.abi")
    return out.strip() if rc == 0 else "universal"


def get_termux_apk_url(abi: str) -> tuple[str, str]:
    """
    从 GitHub API 获取最新 Termux APK 下载地址。
    返回 (url, filename)，失败时返回 universal 版本的固定 URL。
    """
    import json

    # ABI 到 APK 文件名关键词映射
    abi_map = {
        "arm64-v8a":    "arm64-v8a",
        "armeabi-v7a":  "armeabi-v7a",
        "x86_64":       "x86_64",
        "x86":          "x86",
    }
    target_abi = abi_map.get(abi, "universal")

    try:
        req = urllib.request.Request(
            _TERMUX_RELEASE_API,
            headers={"User-Agent": "Pixelle-Video/1.0", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        assets = data.get("assets", [])
        # 优先精确匹配 ABI，找不到则用 universal
        for keyword in [target_abi, "universal"]:
            for asset in assets:
                name: str = asset["name"]
                if keyword in name and name.endswith(".apk") and "debug" not in name.lower():
                    return asset["browser_download_url"], name
        # 兜底：用第一个 .apk
        for asset in assets:
            if asset["name"].endswith(".apk"):
                return asset["browser_download_url"], asset["name"]
    except Exception as e:
        logger.warning(f"get_termux_apk_url: GitHub API failed ({e}), using fallback")

    # 兜底固定 URL（universal debug 版，稳定可用）
    fallback = (
        "https://github.com/termux/termux-app/releases/download/"
        "v0.118.1/termux-app_v0.118.1+github-debug_universal.apk"
    )
    return fallback, "termux-universal.apk"


def install_termux_via_adb(
    serial: str,
    progress_callback=None,
) -> dict:
    """
    自动下载 Termux APK 并通过 ADB 安装到手机。

    Args:
        serial:            ADB device serial
        progress_callback: callable(message: str)，用于向 UI 报告进度

    Returns:
        {"ok": bool, "message": str}
    """
    def _report(msg: str):
        logger.info(f"install_termux: {msg}")
        if progress_callback:
            progress_callback(msg)

    # 1. 检测设备架构
    abi = get_device_abi(serial)
    _report(f"设备架构: {abi}")

    # 2. 获取下载地址
    url, filename = get_termux_apk_url(abi)
    _report(f"下载 Termux ({filename})...")

    # 3. 下载 APK 到临时目录
    try:
        tmp_dir = tempfile.mkdtemp(prefix="pixelle_termux_")
        apk_path = os.path.join(tmp_dir, filename)

        def _progress_hook(count, block_size, total_size):
            if total_size > 0 and count % 50 == 0:
                pct = min(100, count * block_size * 100 // total_size)
                _report(f"下载中... {pct}%")

        urllib.request.urlretrieve(url, apk_path, _progress_hook)
        _report(f"下载完成 ({os.path.getsize(apk_path) // 1024 // 1024:.1f} MB)")
    except Exception as e:
        return {"ok": False, "message": f"APK 下载失败: {e}"}

    # 4. ADB 安装
    _report("正在通过 ADB 安装 Termux...")
    try:
        from pixelle_video.services.device_manager import device_manager
        adb_cmd = device_manager.get_adb_command()
    except Exception:
        adb_cmd = "adb"

    result = subprocess.run(
        [adb_cmd, "-s", serial, "install", "-r", apk_path],
        capture_output=True, text=True, timeout=120,
    )

    # 清理临时文件
    try:
        os.remove(apk_path)
        os.rmdir(tmp_dir)
    except Exception:
        pass

    if result.returncode == 0 and "Success" in result.stdout:
        _report("Termux 安装成功！")
        return {"ok": True, "message": "Termux 安装成功"}
    else:
        err = result.stdout.strip() or result.stderr.strip()
        return {"ok": False, "message": f"ADB install 失败: {err}"}


def push_agent_files(serial: str) -> dict:
    """
    将 phone_agent.py 和 setup_termux.sh 推送到手机 /sdcard/。

    Returns:
        {"ok": True/False, "pushed": [...], "errors": [...]}
    """
    files = [
        (_PHONE_AGENT_PY, "/sdcard/phone_agent.py"),
        (_SETUP_SH, "/sdcard/pixelle_setup.sh"),
        (_BOOT_SCRIPT, "/sdcard/termux_boot_start_agent.sh"),
        (_INSTALL_BOOT_SH, "/sdcard/install_termux_boot.sh"),
    ]
    pushed = []
    errors = []

    for local, remote in files:
        if not local.exists():
            errors.append(f"{local.name} not found")
            logger.error(f"push_agent_files: {local} not found")
            continue
        rc, out, err = _adb(serial, "push", str(local), remote, timeout=60)
        if rc == 0:
            pushed.append(remote)
            logger.info(f"push_agent_files: {local.name} → {remote}")
        else:
            errors.append(f"{local.name}: {err}")
            logger.error(f"push_agent_files: failed {local.name}: {err}")

    return {"ok": len(errors) == 0, "pushed": pushed, "errors": errors}


def open_termux(serial: str) -> bool:
    """通过 ADB 打开 Termux。"""
    rc, _, _ = _adb(serial, "shell", "am", "start",
                    "-n", f"{TERMUX_PACKAGE}/.app.TermuxActivity")
    return rc == 0


def try_run_setup_in_termux(serial: str) -> bool:
    """
    尝试通过 Termux RUN_COMMAND 广播自动运行安装脚本。
    需要手机 Termux 中开启「允许外部应用」。
    失败时静默返回 False（不影响主流程，让用户手动操作）。
    """
    rc, _, _ = _adb(
        serial,
        "shell", "am", "broadcast",
        "-a", "com.termux.RUN_COMMAND",
        "--es", "com.termux.RUN_COMMAND_PATH",
        "/data/data/com.termux/files/usr/bin/bash",
        "--esa", "com.termux.RUN_COMMAND_ARGUMENTS",
        "-c,bash /sdcard/pixelle_setup.sh",
        "--ez", "com.termux.RUN_COMMAND_BACKGROUND", "false",
        "-n", f"{TERMUX_PACKAGE}/.app.RunCommandService",
        timeout=15,
    )
    return rc == 0


def setup_phone_agent(serial: str) -> dict:
    """
    一键初始化：
      1. 检查设备连接
      2. 检查 Termux 是否已安装
      3. 推送 phone_agent.py + setup_termux.sh
      4. 打开 Termux
      5. 尝试自动运行安装脚本（需 Termux 开启允许外部应用）

    Returns:
        {
            "ok": bool,
            "termux_installed": bool,
            "pushed": list[str],
            "auto_run": bool,       # 是否自动触发了安装脚本
            "errors": list[str],
            "manual_command": str,  # 用户需要在 Termux 手动运行的命令
        }
    """
    result: dict = {
        "ok": False,
        "termux_installed": False,
        "pushed": [],
        "auto_run": False,
        "errors": [],
        "manual_command": "bash /sdcard/pixelle_setup.sh",
    }

    # 1. 检查设备连接
    rc, out, _ = _adb(serial, "get-state")
    if rc != 0 or "device" not in out:
        result["errors"].append(f"设备 {serial} 未连接或未授权")
        return result

    # 2. 检查 Termux
    result["termux_installed"] = is_termux_installed(serial)
    if not result["termux_installed"]:
        result["errors"].append("Termux 未安装，请先在手机上安装 Termux（F-Droid 或 Google Play）")
        return result

    # 3. 推送文件
    push_result = push_agent_files(serial)
    result["pushed"] = push_result["pushed"]
    result["errors"].extend(push_result["errors"])
    if not push_result["ok"]:
        return result

    # 4. 打开 Termux
    open_termux(serial)

    # 5. 尝试自动运行（可能失败，无所谓）
    result["auto_run"] = try_run_setup_in_termux(serial)

    result["ok"] = True
    return result
