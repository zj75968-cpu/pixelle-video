#!/usr/bin/env python3
"""
Pixelle-Video Phone HTTP Agent
================================
在手机端（Termux）运行此脚本，将手机暴露为 REST 服务，
让云端或本地的 Pixelle-Video 服务器通过 HTTP 控制手机。

依赖安装（Termux）：
    pkg install python
    pip install flask requests

    # 如需更可靠的 UI 自动化（uiautomator2 模式），额外执行：
    pkg install android-tools
    pip install uiautomator2
    adb connect localhost:5555   # 连接本机 ADB daemon（开启无线调试后）
    python -m uiautomator2 init  # 安装 ATX-agent APK（只需一次）

    # 如需中文输入支持（Shell 模式），二选一：
    # 方案 A：安装 Termux:API 插件 → termux-clipboard-set 生效
    # 方案 B：安装 ADBKeyboard APK 并设为默认 IME

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
import uuid
from concurrent.futures import ThreadPoolExecutor
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
# 小红书本地发布（手机端 uiautomator2 自控）
# -------------------------------------------------------------------
_publish_tasks: dict = {}  # task_id -> {status, message}
_publish_executor = ThreadPoolExecutor(max_workers=1)  # 串行执行，防止并发操作 UI


def _u2_connect():
    """连接本机 uiautomator2，优先直连，回退到 localhost:5555。"""
    import uiautomator2 as u2
    try:
        return u2.connect()  # 本机直连
    except Exception:
        return u2.connect("localhost:5555")


def _u2_tap_text(d, candidates: list, timeout: float = 5.0) -> bool:
    """按候选文本列表尝试点击，返回是否成功。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for txt in candidates:
            el = d(text=txt)
            if el.exists(timeout=0.5):
                el.click()
                return True
            el = d(textContains=txt)
            if el.exists(timeout=0.5):
                el.click()
                return True
        time.sleep(0.5)
    return False


def _do_xhs_publish_u2(task_id: str, media_path: str, title: str, body: str, hashtags: list):
    """后台线程：用本地 uiautomator2 驱动小红书完成发布。"""

    def _update(status: str, message: str):
        _publish_tasks[task_id] = {"status": status, "message": message}
        print(f"[publish:{task_id[:8]}] {status}: {message}")

    try:
        import uiautomator2 as u2  # noqa: F401
    except ImportError:
        _update("failed", "uiautomator2 未安装，请在 Termux 运行: pip install uiautomator2")
        return

    try:
        _update("running", "连接设备...")
        d = _u2_connect()

        _update("running", "启动小红书...")
        d.app_start("com.xingin.xhs")
        time.sleep(3)

        _update("running", "点击发布/创作按钮...")
        if not _u2_tap_text(d, ["+", "发布", "创作", "新建"], timeout=8):
            # 兜底：点击底部中央
            w, h = d.window_size()
            d.click(w // 2, int(h * 0.95))
        time.sleep(2)

        # 如果有媒体文件则进入图文流程，否则仅文字
        if media_path and Path(media_path).exists():
            _update("running", "选择媒体文件...")
            if not _u2_tap_text(d, ["从相册选择", "相册", "图库", "从相册"], timeout=5):
                _u2_tap_text(d, ["图片", "视频", "照片"], timeout=3)
            time.sleep(2)

            # 尝试按文件名匹配
            media_stem = Path(media_path).stem
            el = d(textContains=media_stem)
            if el.exists(timeout=3):
                el.click()
            else:
                # 点第一项（最新）
                rv = d(className="androidx.recyclerview.widget.RecyclerView")
                if rv.exists(timeout=3):
                    rv.child(index=0).click()
            time.sleep(1)

            # 确认 / 下一步
            _u2_tap_text(d, ["下一步", "确定", "完成", "确认"], timeout=5)
            time.sleep(2)

        _update("running", "填写标题...")
        title_el = None
        for hint in ["填写标题会有更多赞哦～", "填写标题", "标题"]:
            el = d(hint=hint)
            if el.exists(timeout=2):
                title_el = el
                break
        if title_el is None:
            # 按 EditText 顺序找第一个
            title_el = d(className="android.widget.EditText", instance=0)
        if title_el.exists(timeout=3):
            title_el.click()
            title_el.clear_text()
            title_el.set_text(title[:20])
        time.sleep(1)

        _update("running", "填写正文...")
        body_el = None
        for hint in ["添加正文", "正文", "描述"]:
            el = d(hint=hint)
            if el.exists(timeout=2):
                body_el = el
                break
        if body_el is None:
            body_el = d(className="android.widget.EditText", instance=1)
        if body_el and body_el.exists(timeout=2):
            body_el.click()
            body_el.set_text(body)
        time.sleep(1)

        if hashtags:
            _update("running", "添加话题标签...")
            for tag in hashtags[:3]:
                if _u2_tap_text(d, ["#", "话题", "添加话题"], timeout=3):
                    time.sleep(1)
                    tag_clean = tag.lstrip("#")
                    inp = d(className="android.widget.EditText", focused=True)
                    if inp.exists(timeout=2):
                        inp.set_text(tag_clean)
                        time.sleep(1.5)
                        # 点击第一条建议
                        sug = d(resourceId="com.xingin.xhs:id/tv_topic_name")
                        if not sug.exists(timeout=2):
                            sug = d(textContains=tag_clean)
                        if sug.exists(timeout=2):
                            sug.click()
                            time.sleep(0.5)

        _update("running", "点击发布...")
        if not _u2_tap_text(d, ["发布", "立即发布", "确认发布"], timeout=8):
            _update("failed", "未找到发布按钮，请手动完成")
            return
        time.sleep(3)

        _update("success", "✅ 发布成功！")

    except Exception as exc:
        import traceback
        _update("failed", f"发布出错: {exc}\n{traceback.format_exc()}")


# -------------------------------------------------------------------
# Shell 自动化辅助（无需 uiautomator2 / ATX-agent，Termux 原生可用）
# -------------------------------------------------------------------
import xml.etree.ElementTree as _ET  # noqa: E402


def _get_screen_size() -> tuple:
    """获取屏幕分辨率，返回 (width, height)。"""
    _, out, _ = _run_shell("wm", "size")
    m = re.search(r"(\d+)x(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1080, 2400


def _ui_dump_and_tap(candidates: list, timeout: float = 8.0, scroll: bool = False) -> bool:
    """
    用 uiautomator dump 解析 UI 树，找到文字匹配的节点并点击。
    candidates: 候选文本列表（模糊包含匹配）。
    无需 ADB，Termux 内可直接调用 /system/bin/uiautomator。
    """
    dump_path = "/sdcard/uidump_agent.xml"

    def _try_once() -> bool:
        rc, _, _ = _run_shell("uiautomator", "dump", dump_path, timeout=10)
        if rc != 0:
            return False
        try:
            with open(dump_path, "r", encoding="utf-8", errors="ignore") as f:
                xml_content = f.read()
            root = _ET.fromstring(xml_content)
            for node in root.iter("node"):
                combined = node.get("text", "") + " " + node.get("content-desc", "")
                for cand in candidates:
                    if cand in combined:
                        bounds = node.get("bounds", "")
                        bm = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                        if bm:
                            x = (int(bm.group(1)) + int(bm.group(3))) // 2
                            y = (int(bm.group(2)) + int(bm.group(4))) // 2
                            _run_shell("input", "tap", str(x), str(y))
                            return True
        except Exception:
            pass
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _try_once():
            return True
        time.sleep(0.8)

    if scroll:
        w, h = _get_screen_size()
        _run_shell("input", "swipe",
                   str(w // 2), str(int(h * 0.65)),
                   str(w // 2), str(int(h * 0.3)), "400")
        time.sleep(1)
        if _try_once():
            return True

    return False


def _input_text_shell(text: str) -> bool:
    """
    输入文字（支持中文）。尝试顺序：
    1. ADBKeyboard broadcast（需安装 ADBKeyboard 并设为默认 IME）
    2. termux-clipboard + 粘贴（需 Termux:API 插件）
    3. input text（仅 ASCII，中文会乱码，作最后兜底）
    """
    if not text:
        return True
    # 方案 1：ADBKeyboard
    rc, _, _ = _run_shell("am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text, timeout=5)
    if rc == 0:
        return True
    # 方案 2：termux-clipboard
    rc, _, _ = _run_shell("termux-clipboard-set", text, timeout=5)
    if rc == 0:
        time.sleep(0.3)
        _run_shell("input", "keyevent", "279")  # KEYCODE_PASTE
        return True
    # 方案 3：纯 ASCII（中文会乱码，但不崩溃）
    safe = text.replace(" ", "%s")
    _run_shell("input", "text", safe, timeout=5)
    return False


def _do_xhs_publish_shell(task_id: str, media_path: str, title: str, body: str, hashtags: list):
    """纯 Shell 方式发布小红书（uiautomator dump + input 命令，无需 uiautomator2/ATX-agent）。"""

    def _update(status: str, message: str):
        _publish_tasks[task_id] = {"status": status, "message": message}
        print(f"[xhs-shell:{task_id[:8]}] {status}: {message}")

    try:
        _update("running", "启动小红书...")
        _run_shell("am", "start", "-a", "android.intent.action.MAIN",
                   "-c", "android.intent.category.LAUNCHER",
                   "-n", "com.xingin.xhs/.activity.SplashActivity")
        time.sleep(4)

        _update("running", "点击发布/创作按钮...")
        if not _ui_dump_and_tap(["+", "发布", "创作", "新建"], timeout=8):
            w, h = _get_screen_size()
            _run_shell("input", "tap", str(w // 2), str(int(h * 0.96)))
        time.sleep(2)

        if media_path and Path(media_path).exists():
            _update("running", "选择媒体文件...")
            if not _ui_dump_and_tap(["从相册选择", "相册", "图库", "照片"], timeout=5):
                _ui_dump_and_tap(["图片", "视频"], timeout=3)
            time.sleep(2)

            media_stem = Path(media_path).stem
            if not _ui_dump_and_tap([media_stem], timeout=3):
                # 点第一个缩略图（左上区域，约 160,400）
                _run_shell("input", "tap", "160", "400")
            time.sleep(1)

            if not _ui_dump_and_tap(["下一步", "确定", "完成", "确认"], timeout=5):
                _update("running", "未找到确认按钮，尝试继续...")
            time.sleep(2)

        _update("running", "填写标题...")
        if _ui_dump_and_tap(["填写标题会有更多赞哦", "填写标题", "标题"], timeout=5):
            time.sleep(0.5)
            _input_text_shell(title[:20])
        time.sleep(1)

        _update("running", "填写正文...")
        if _ui_dump_and_tap(["添加正文", "正文", "描述"], timeout=3, scroll=True):
            time.sleep(0.5)
            _input_text_shell(body)
        time.sleep(1)

        if hashtags:
            _update("running", "添加话题标签...")
            for tag in hashtags[:2]:
                if _ui_dump_and_tap(["#", "话题", "添加话题"], timeout=3):
                    time.sleep(0.8)
                    _input_text_shell(tag.lstrip("#"))
                    time.sleep(1.5)
                    tag_clean = tag.lstrip("#")
                    if not _ui_dump_and_tap([tag_clean], timeout=2):
                        _run_shell("input", "keyevent", "66")  # Enter
                    time.sleep(0.5)

        _update("running", "点击发布...")
        if not _ui_dump_and_tap(["发布", "立即发布", "确认发布"], timeout=8, scroll=True):
            _update("failed", "未找到发布按钮，请手动完成")
            return
        time.sleep(3)

        _update("success", "✅ 发布成功！")

    except Exception as exc:
        import traceback
        _update("failed", f"Shell 发布失败: {exc}\n{traceback.format_exc()}")


def _do_xhs_publish(task_id: str, media_path: str, title: str, body: str, hashtags: list):
    """
    调度层：优先用 uiautomator2（需先 init），不可用时自动回退到 Shell 方式。
    Shell 方式完全不需要 PC ADB，只需 Termux 环境即可运行。
    """

    def _update(status: str, message: str):
        _publish_tasks[task_id] = {"status": status, "message": message}
        print(f"[publish:{task_id[:8]}] {status}: {message}")

    # 尝试 uiautomator2
    try:
        import uiautomator2  # noqa: F401
        _update("running", "使用 uiautomator2 模式...")
        _do_xhs_publish_u2(task_id, media_path, title, body, hashtags)
        return
    except ImportError:
        _update("running", "uiautomator2 未安装，切换到 Shell 模式（无需 ADB）...")
    except Exception as e:
        _update("running", f"uiautomator2 连接失败（{e}），切换到 Shell 模式...")

    _do_xhs_publish_shell(task_id, media_path, title, body, hashtags)


@app.route("/publish", methods=["POST"])
def publish():
    """发起发布任务（异步，立即返回 task_id）。

    Body JSON:
        media_path  str   手机本地文件路径，如 /sdcard/DCIM/PixelleVideo/xxx.mp4
        title       str   标题（必填）
        body        str   正文（可选）
        hashtags    list  话题列表，如 ["健康", "养生"]（可选）
        platform    str   目前仅支持 "xhs"（默认）
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    if not data or "title" not in data:
        return jsonify({"error": "Missing required field: title"}), 400

    platform = data.get("platform", "xhs")
    if platform != "xhs":
        return jsonify({"error": f"Platform not supported yet: {platform}"}), 400

    task_id = str(uuid.uuid4())
    _publish_tasks[task_id] = {"status": "queued", "message": "等待执行..."}
    _publish_executor.submit(
        _do_xhs_publish,
        task_id,
        data.get("media_path", ""),
        data.get("title", ""),
        data.get("body", ""),
        data.get("hashtags", []),
    )
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/publish-status/<task_id>", methods=["GET"])
def get_publish_status(task_id: str):
    """轮询发布任务状态。返回 status: queued/running/success/failed。"""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    task = _publish_tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"ok": True, "task_id": task_id, **task})


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
