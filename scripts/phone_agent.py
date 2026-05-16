#!/usr/bin/env python3
"""
Pixelle-Video Phone HTTP Agent
================================
在手机端（Termux）运行此脚本，将手机暴露为 REST 服务，
让云端或本地的 Pixelle-Video 服务器通过 HTTP 控制手机。

依赖安装（Termux）：
    pkg install python
    pip install flask requests

启动方式（手动）：
    python phone_agent.py --token YOUR_SECRET_TOKEN --port 7777

自动启动 cloudflared 并上报 URL（推荐，开机自启使用）：
    python phone_agent.py --token TOKEN --port 7777 \\
        --auto-cloudflare \\
        --pixelle-url http://your-server.com:8000
"""

import argparse
import hmac
import os
import re
import subprocess
import threading
import time
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("请先运行: pip install flask")
    raise

app = Flask(__name__)

# -------------------------------------------------------------------
# 全局配置（通过 CLI 参数设置）
# -------------------------------------------------------------------
_TOKEN: str = ""
_PUSH_DIR: str = "/sdcard/DCIM/PixelleVideo"


def _check_token() -> bool:
    """验证请求头中的 X-Token。"""
    if not _TOKEN:
        return True  # 未配置 token 时跳过验证（仅限本地测试）
    incoming = request.headers.get("X-Token", "")
    # 使用 hmac.compare_digest 防止时序攻击
    return hmac.compare_digest(incoming, _TOKEN)


def _run_shell(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """在手机 shell 上执行命令，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# -------------------------------------------------------------------
# 接口：健康检查
# -------------------------------------------------------------------
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "message": "Pixelle Phone Agent running"})


# -------------------------------------------------------------------
# 接口：推送文件到相册
# POST /push-file
# Body: { "filename": "video.mp4", "content_hex": "...hex..." }
# -------------------------------------------------------------------
@app.route("/push-file", methods=["POST"])
def push_file():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    if not data or "filename" not in data or "content_hex" not in data:
        return jsonify({"error": "Missing filename or content_hex"}), 400

    filename = Path(data["filename"]).name  # 防止路径穿越
    dest_dir = data.get("push_dir", _PUSH_DIR)
    dest_path = f"{dest_dir}/{filename}"

    try:
        content = bytes.fromhex(data["content_hex"])
    except ValueError:
        return jsonify({"error": "Invalid content_hex"}), 400

    # 确保目录存在
    os.makedirs(dest_dir, exist_ok=True)

    # 写入文件
    with open(dest_path, "wb") as f:
        f.write(content)

    # 触发媒体库扫描
    _trigger_media_scan(dest_path)

    return jsonify({"ok": True, "device_path": dest_path, "size": len(content)})


# -------------------------------------------------------------------
# 接口：推送多个文件（分块传输，适合大文件）
# POST /push-file-chunk
# Body: { "filename": "video.mp4", "chunk_index": 0, "total_chunks": 3,
#         "chunk_hex": "...", "push_dir": "/sdcard/..." }
# 最后一块发送后自动触发媒体扫描
# -------------------------------------------------------------------
_chunk_buffers: dict = {}
_chunk_lock = threading.Lock()


@app.route("/push-file-chunk", methods=["POST"])
def push_file_chunk():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    required = ["filename", "chunk_index", "total_chunks", "chunk_hex"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing fields, required: {required}"}), 400

    filename = Path(data["filename"]).name
    dest_dir = data.get("push_dir", _PUSH_DIR)
    idx = int(data["chunk_index"])
    total = int(data["total_chunks"])

    try:
        chunk = bytes.fromhex(data["chunk_hex"])
    except ValueError:
        return jsonify({"error": "Invalid chunk_hex"}), 400

    with _chunk_lock:
        if filename not in _chunk_buffers:
            _chunk_buffers[filename] = {}
        _chunk_buffers[filename][idx] = chunk

        if len(_chunk_buffers[filename]) == total:
            # 所有分块已到，合并写入
            full_content = b"".join(_chunk_buffers[filename][i] for i in range(total))
            del _chunk_buffers[filename]

            os.makedirs(dest_dir, exist_ok=True)
            dest_path = f"{dest_dir}/{filename}"
            with open(dest_path, "wb") as f:
                f.write(full_content)
            _trigger_media_scan(dest_path)
            return jsonify({"ok": True, "completed": True, "device_path": dest_path})

    return jsonify({"ok": True, "completed": False, "received_chunks": idx + 1})


# -------------------------------------------------------------------
# 接口：触发媒体库扫描
# POST /scan-media
# Body: { "device_path": "/sdcard/DCIM/..." }
# -------------------------------------------------------------------
@app.route("/scan-media", methods=["POST"])
def scan_media():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    device_path = data.get("device_path", "")
    if not device_path:
        return jsonify({"error": "Missing device_path"}), 400

    _trigger_media_scan(device_path)
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# 接口：启动 App
# POST /open-app
# Body: { "package": "com.xingin.xhs" }
# -------------------------------------------------------------------
@app.route("/open-app", methods=["POST"])
def open_app():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    package = data.get("package", "")
    if not package:
        return jsonify({"error": "Missing package"}), 400

    # 安全：只允许已知包名
    allowed_packages = {
        "com.xingin.xhs",          # 小红书
        "com.smile.gifmaker",       # 快手
        "com.zhiliaoapp.musically", # 抖音国际版
        "com.ss.android.ugc.aweme", # 抖音
        "com.tencent.mm",           # 微信
        "com.weico.international",  # 微博国际版
    }
    if package not in allowed_packages:
        return jsonify({"error": f"Package not in allowlist: {package}"}), 403

    rc, out, err = _run_shell("am", "start", "-n", f"{package}/.MainActivity")
    if rc != 0:
        # 尝试通用启动方式
        rc, out, err = _run_shell("monkey", "-p", package, "-c",
                                   "android.intent.category.LAUNCHER", "1")

    return jsonify({"ok": rc == 0, "output": out, "error": err})


# -------------------------------------------------------------------
# 接口：列出相册目录文件
# GET /list-files?dir=/sdcard/DCIM/PixelleVideo
# -------------------------------------------------------------------
@app.route("/list-files", methods=["GET"])
def list_files():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    target_dir = request.args.get("dir", _PUSH_DIR)
    try:
        files = []
        p = Path(target_dir)
        if p.exists():
            for f in p.iterdir():
                if f.is_file():
                    files.append({"name": f.name, "size": f.stat().st_size})
        return jsonify({"ok": True, "dir": target_dir, "files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------------------------------------------------
# 内部工具
# -------------------------------------------------------------------
def _trigger_media_scan(device_path: str):
    """通知 Android 媒体库扫描新文件，使其出现在相册中。"""
    try:
        subprocess.run(
            ["am", "broadcast", "-a",
             "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
             "-d", f"file://{device_path}"],
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        print(f"[warn] media scan failed: {e}")


# -------------------------------------------------------------------
# 入口
# -------------------------------------------------------------------
def _start_cloudflared_and_report(port: int, pixelle_url: str, token: str):
    """
    子线程：循环启动 cloudflared（守护模式）。
    - 解析到隧道 URL 后写入 ~/pixelle_agent_url.txt 并上报给 Pixelle-Video。
    - 进程意外退出后自动重启（watchdog）。
    """
    cf_cmd = os.path.expanduser("~/cloudflared")
    if not os.path.exists(cf_cmd):
        cf_cmd = "cloudflared"  # 尝试系统 PATH

    url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    restart_delay = 15  # 重启前等待秒数

    while True:  # watchdog 主循环
        print(f"[cloudflared] 启动中（端口 {port}）...")
        try:
            proc = subprocess.Popen(
                [cf_cmd, "tunnel", "--url", f"http://localhost:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            print(f"[cloudflared] ✗ 找不到 cloudflared，{restart_delay}s 后重试...")
            time.sleep(restart_delay)
            continue
        except Exception as e:
            print(f"[cloudflared] ✗ 启动失败: {e}，{restart_delay}s 后重试...")
            time.sleep(restart_delay)
            continue

        tunnel_url = None
        url_deadline = time.time() + 60  # 最多等 60 秒解析 URL

        for line in iter(proc.stdout.readline, ""):
            print(f"[cloudflared] {line.rstrip()}")

            if tunnel_url is None:
                m = url_pattern.search(line)
                if m:
                    tunnel_url = m.group(0)
                    print(f"[cloudflared] ✅ 隧道 URL: {tunnel_url}")
                    # 写入本地文件
                    url_file = os.path.expanduser("~/pixelle_agent_url.txt")
                    try:
                        with open(url_file, "w") as f:
                            f.write(tunnel_url + "\n")
                        print(f"[cloudflared] URL 已写入 {url_file}")
                    except Exception as e:
                        print(f"[cloudflared] 写入文件失败: {e}")
                    # 上报给 Pixelle-Video
                    if pixelle_url:
                        _report_url_to_pixelle(tunnel_url, token, pixelle_url)
                elif time.time() > url_deadline:
                    print("[cloudflared] ⚠ 超时未获得隧道 URL，请手动填写到 Pixelle-Video 设置页")
                    # 继续读取，但不再尝试解析 URL

        # stdout 关闭 = 进程已退出
        ret = proc.wait()
        print(f"[cloudflared] ⚠ 进程已退出（code={ret}），{restart_delay}s 后自动重启...")
        time.sleep(restart_delay)


def _report_url_to_pixelle(tunnel_url: str, agent_token: str, pixelle_url: str, retries: int = 5):
    """将 cloudflared URL 上报给 Pixelle-Video，支持重试。"""
    try:
        import urllib.request
        import json as _json

        endpoint = pixelle_url.rstrip("/") + "/api/phone-agent/register"
        payload = _json.dumps({"url": tunnel_url, "token": agent_token}).encode()
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "X-Token": agent_token},
            method="POST",
        )
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read().decode()
                    print(f"[report] ✅ URL 已上报到 Pixelle-Video: {body}")
                    return
            except Exception as e:
                print(f"[report] 第 {attempt}/{retries} 次上报失败: {e}")
                time.sleep(5)
    except Exception as e:
        print(f"[report] 上报模块加载失败: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pixelle Phone HTTP Agent")
    parser.add_argument("--token", default=os.getenv("AGENT_TOKEN", ""),
                        help="认证 Token（X-Token 请求头），留空则不验证")
    parser.add_argument("--port", type=int, default=int(os.getenv("AGENT_PORT", "7777")),
                        help="监听端口（默认 7777）")
    parser.add_argument("--push-dir", default=os.getenv("AGENT_PUSH_DIR", "/sdcard/DCIM/PixelleVideo"),
                        help="文件推送目标目录")
    parser.add_argument("--auto-cloudflare", action="store_true",
                        default=os.getenv("AGENT_AUTO_CLOUDFLARE", "").lower() in ("1", "true", "yes"),
                        help="自动启动 cloudflared 并解析隧道 URL")
    parser.add_argument("--pixelle-url", default=os.getenv("PIXELLE_SERVER_URL", ""),
                        help="Pixelle-Video 服务器地址，用于自动上报隧道 URL")
    args = parser.parse_args()

    _TOKEN = args.token
    _PUSH_DIR = args.push_dir

    if not _TOKEN:
        print("[警告] 未设置 --token，任何人均可访问此服务！")
    else:
        print(f"[info] Token 已设置（长度 {len(_TOKEN)}）")

    print(f"[info] 推送目录: {_PUSH_DIR}")
    print(f"[info] 启动服务: http://0.0.0.0:{args.port}")

    # 自动启动 cloudflared（开机自启模式）
    if args.auto_cloudflare:
        cf_thread = threading.Thread(
            target=_start_cloudflared_and_report,
            args=(args.port, args.pixelle_url, args.token),
            daemon=True,
        )
        cf_thread.start()
    else:
        print()
        print("提示：加 --auto-cloudflare 可自动启动 cloudflared 并上报 URL")
        print(f"  cloudflared tunnel --url http://localhost:{args.port}")
        print()

    app.run(host="0.0.0.0", port=args.port, debug=False)
