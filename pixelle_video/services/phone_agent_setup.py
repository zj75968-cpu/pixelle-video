"""
Phone Agent One-Click Setup
============================
通过 ADB 将 phone_agent.py 和 setup_termux.sh 推送到手机，
并引导用户在 Termux 中完成一键安装。

核心功能：
    setup_phone_agent(serial)  → 推送文件 + 打开 Termux + 返回操作指引
"""

from __future__ import annotations

import subprocess
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
