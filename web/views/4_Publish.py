# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Publish Management Page

Manage Android devices and schedule Xiaohongshu posts for publishing.
"""

import sys
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.utils.async_helpers import run_async

st.set_page_config(
    page_title="发布管理 - AI Video Generator",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---- Helpers -----------------------------------------------------------------

def _wifi_connect_hint(adb_msg: str) -> str:
    """Return a user-friendly hint based on the ADB connect output."""
    m = adb_msg.lower()
    if "authenticate" in m or "authentication" in m:
        return (
            "**原因：设备拒绝认证**\n\n"
            "首次连接需要先配对。请切换到「Android 11+ 无线配对」标签页，"
            "完成「第一步：配对」（adb pair + 配对码）后再回来连接。"
        )
    if "refused" in m or "connection refused" in m:
        return (
            "**原因：端口被拒绝**\n\n"
            "- 检查手机「无线调试」主页显示的端口（不是配对端口）\n"
            "- 确认「无线调试」开关处于开启状态"
        )
    if "no route" in m or "timed out" in m or "timeout" in m:
        return (
            "**原因：网络不通**\n\n"
            "- 确认手机与电脑在同一 WiFi\n"
            "- 检查 IP 地址是否正确（手机「无线调试」页显示）"
        )
    return (
        "请检查：无线调试开关已开启 / IP 和端口与手机屏幕一致 / 手机与电脑在同一 WiFi"
    )


def get_device_manager():
    from pixelle_video.services.device_manager import device_manager
    # Apply saved ADB server config on first use
    if not getattr(device_manager, "_adb_server_applied", False):
        try:
            from pixelle_video.config import config_manager
            cfg = getattr(config_manager.config, "xhs_publish", None)
            if cfg:
                h = getattr(cfg, "adb_server_host", "127.0.0.1") or "127.0.0.1"
                p = getattr(cfg, "adb_server_port", 5037) or 5037
                device_manager.configure_adb_server(h, int(p))
        except Exception:
            pass
        device_manager._adb_server_applied = True
    return device_manager


def get_publish_scheduler():
    from pixelle_video.services.publish_scheduler import publish_scheduler
    return publish_scheduler


STATUS_BADGE = {
    "pending":   "🟡 待发布",
    "scheduled": "🕐 已计划",
    "running":   "🔵 发布中",
    "success":   "✅ 成功",
    "done":      "✅ 成功",
    "failed":    "❌ 失败",
    "cancelled": "⛔ 已取消",
    "deleted":   "🗑️ 已删除",
}

PUBLISH_FORM_KEYS = {
    "task_id": "publish_form_task_id",
    "topic": "publish_form_topic",
    "title": "publish_form_title",
    "body": "publish_form_body",
    "hashtags_raw": "publish_form_hashtags_raw",
    "images_raw": "publish_form_images_raw",
}


def _safe_load_json(file_path: Path) -> dict | None:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _init_publish_form_defaults():
    last = st.session_state.get("last_post_result", {})
    defaults = {
        PUBLISH_FORM_KEYS["task_id"]: str(last.get("task_id", "")),
        PUBLISH_FORM_KEYS["topic"]: str(last.get("topic", "")),
        PUBLISH_FORM_KEYS["title"]: str(last.get("title", "")),
        PUBLISH_FORM_KEYS["body"]: str(last.get("body", "")),
        PUBLISH_FORM_KEYS["hashtags_raw"]: ", ".join(last.get("hashtags", [])),
        PUBLISH_FORM_KEYS["images_raw"]: "\n".join(last.get("images", [])),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _load_recent_post_history(limit: int = 20) -> list[dict]:
    output_dir = _project_root / "output"
    if not output_dir.exists():
        return []

    items: list[dict] = []
    task_dirs = sorted([p for p in output_dir.iterdir() if p.is_dir()], reverse=True)
    for task_dir in task_dirs:
        post_path = task_dir / "post.json"
        if not post_path.exists():
            continue

        post_data = _safe_load_json(post_path)
        if not isinstance(post_data, dict):
            continue

        params = _safe_load_json(task_dir / "post_params.json") or {}
        frames = post_data.get("frames") or []
        images: list[str] = []

        for frame in frames:
            if not isinstance(frame, dict):
                continue
            image_file = frame.get("image_file")
            if not image_file:
                continue
            image_path = task_dir / "images" / str(image_file)
            if image_path.exists():
                images.append(str(image_path))

        if not images:
            images_dir = task_dir / "images"
            if images_dir.exists():
                for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    images.extend([str(p) for p in sorted(images_dir.glob(pattern)) if p.exists()])

        title = str(post_data.get("title", "(无标题)"))
        body = str(post_data.get("body", ""))
        hashtags = post_data.get("hashtags") or []
        topic = str(params.get("topic", ""))
        created_at = str(post_data.get("created_at") or params.get("saved_at") or task_dir.name)
        created_label = created_at[:16].replace("T", " ") if "T" in created_at else created_at

        items.append(
            {
                "task_id": task_dir.name,
                "label": f"{created_label} | {title[:22]} | {task_dir.name}",
                "topic": topic,
                "title": title,
                "body": body,
                "hashtags": [str(t).lstrip("#") for t in hashtags if str(t).strip()],
                "images": list(dict.fromkeys(images)),
                "created_at": created_at,
            }
        )

        if len(items) >= limit:
            break

    return items


def _resolve_video_path(task_id: str, task_summary: dict, pixelle_video) -> str:
    candidate = str(task_summary.get("video_path") or "")
    if candidate and Path(candidate).exists():
        return candidate

    detail = run_async(pixelle_video.history.get_task_detail(task_id))
    if not detail:
        return ""

    metadata = detail.get("metadata") or {}
    result = metadata.get("result") or {}
    candidate = str(result.get("video_path") or "")
    if candidate and Path(candidate).exists():
        return candidate

    storyboard = detail.get("storyboard")
    final_video_path = getattr(storyboard, "final_video_path", "") if storyboard else ""
    candidate = str(final_video_path or "")
    if candidate and Path(candidate).exists():
        return candidate

    return ""


def _load_recent_video_history(limit: int = 12) -> list[dict]:
    pixelle_video = get_pixelle_video()
    data = run_async(
        pixelle_video.history.get_task_list(
            page=1,
            page_size=limit * 2,
            status="completed",
            sort_by="created_at",
            sort_order="desc",
        )
    )
    tasks = data.get("tasks", []) if isinstance(data, dict) else []

    items: list[dict] = []
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        if not task_id:
            continue

        video_path = _resolve_video_path(task_id, task, pixelle_video)
        if not video_path:
            continue

        title = str(task.get("title") or task_id)
        created_at = str(task.get("created_at") or task_id)
        created_label = created_at[:16].replace("T", " ") if "T" in created_at else created_at
        items.append(
            {
                "task_id": task_id,
                "label": f"{created_label} | {title[:26]} | {task_id}",
                "title": title,
                "video_path": video_path,
                "created_at": created_at,
            }
        )
        if len(items) >= limit:
            break

    return items


def _media_state_key(prefix: str, path: str) -> str:
    digest = hashlib.md5(path.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _build_image_pool(post_items: list[dict], limit: int = 240) -> list[dict]:
    pool: list[dict] = []
    seen: set[str] = set()
    for item in post_items:
        for img_path in item.get("images", []):
            path = str(img_path)
            if not path or path in seen:
                continue
            seen.add(path)
            pool.append(
                {
                    "path": path,
                    "name": Path(path).name,
                    "exists": Path(path).exists(),
                    "task_id": item.get("task_id", ""),
                    "title": item.get("title", ""),
                    "topic": item.get("topic", ""),
                    "created_at": item.get("created_at", ""),
                }
            )
            if len(pool) >= limit:
                return pool
    return pool


def _build_video_pool(video_items: list[dict], limit: int = 60) -> list[dict]:
    pool: list[dict] = []
    seen: set[str] = set()
    for item in video_items:
        path = str(item.get("video_path", ""))
        if not path or path in seen:
            continue
        seen.add(path)
        pool.append(
            {
                "path": path,
                "name": Path(path).name,
                "exists": Path(path).exists(),
                "task_id": item.get("task_id", ""),
                "title": item.get("title", ""),
                "created_at": item.get("created_at", ""),
            }
        )
        if len(pool) >= limit:
            break
    return pool


def _apply_selected_images_to_form(mode: str, selected_paths: list[str]):
    if not selected_paths:
        st.session_state["publish_history_feedback"] = "请先勾选至少 1 张图片"
        return

    if mode == "replace":
        st.session_state[PUBLISH_FORM_KEYS["images_raw"]] = "\n".join(selected_paths)
        st.session_state["publish_history_feedback"] = f"已覆盖图片路径（{len(selected_paths)} 张）"
        return

    existing = st.session_state.get(PUBLISH_FORM_KEYS["images_raw"], "")
    existing_lines = [line.strip() for line in str(existing).splitlines() if line.strip()]
    merged = list(dict.fromkeys(existing_lines + selected_paths))
    st.session_state[PUBLISH_FORM_KEYS["images_raw"]] = "\n".join(merged)
    st.session_state["publish_history_feedback"] = f"已追加图片路径（{len(selected_paths)} 张）"


def _parse_created_dt(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        pass

    # Task-like pattern: 20260504_150645_xxxx
    try:
        return datetime.strptime(text[:15], "%Y%m%d_%H%M%S")
    except Exception:
        return None


def _in_time_range(created_at: str, days: int | None) -> bool:
    if days is None:
        return True
    dt = _parse_created_dt(created_at)
    if dt is None:
        return True
    return dt >= (datetime.now() - timedelta(days=days))


def _time_group_label(created_at: str) -> str:
    dt = _parse_created_dt(created_at)
    if dt is None:
        return "未知"

    now = datetime.now()
    d = (now.date() - dt.date()).days
    if d == 0:
        return "今天"
    if d == 1:
        return "昨天"
    if d <= 7:
        return "近7天"
    if d <= 30:
        return "近30天"
    return "更早"


def _group_media_by_time(items: list[dict]) -> list[tuple[str, list[dict]]]:
    order = ["今天", "昨天", "近7天", "近30天", "更早", "未知"]
    grouped: dict[str, list[dict]] = {k: [] for k in order}

    for item in items:
        grouped[_time_group_label(str(item.get("created_at", "")))].append(item)

    result: list[tuple[str, list[dict]]] = []
    for key in order:
        if grouped[key]:
            result.append((key, grouped[key]))
    return result


def _keyword_match(media: dict, fields: list[str], keyword: str) -> bool:
    if not keyword:
        return True
    hay = " ".join([str(media.get(f, "")) for f in fields]).lower()
    return keyword in hay


# ---- Device Management Tab ---------------------------------------------------

def _render_device_cards(dm, devices):
    """Render registered device cards."""
    if not devices:
        st.info("暂无设备。请通过 USB 连接手机，或使用下方 WiFi 连接。")
        return

    for dev in devices:
        status_icon = "🟢" if dev.connected else "🔴"
        with st.expander(f"{status_icon} {dev.name or dev.serial}  —  {dev.theme or '未设置主题'}"):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(f"Serial: {dev.serial}")
                st.text(f"状态: {'已连接' if dev.connected else '未连接'}")
                st.text(f"最后在线: {dev.last_seen or '从未'}")

                new_name = st.text_input("设备名称", value=dev.name, key=f"name_{dev.serial}")
                new_theme = st.text_input("内容主题", value=dev.theme, key=f"theme_{dev.serial}")
                if st.button("保存", key=f"save_{dev.serial}"):
                    dm.add_device(serial=dev.serial, name=new_name, theme=new_theme)
                    st.success("已保存")
                    st.rerun()

            with col2:
                if dev.connected:
                    if st.button("📸 截图", key=f"ss_{dev.serial}"):
                        data = dm.screenshot(dev.serial)
                        if data:
                            st.image(data, caption="设备截图", width="stretch")
                        else:
                            st.error("截图失败")


                if st.button("🗑️ 移除", key=f"del_{dev.serial}"):
                    dm.remove_device(dev.serial)
                    st.rerun()


@st.fragment(run_every="8s")
def _render_auto_refresh_device_list(dm):
    """Auto-refresh device list every 8s so users don't need manual refresh."""
    st.caption("设备状态每 8 秒自动检测一次；已保存 WiFi 设备会自动重连。")

    if st.button("🔄 立即刷新连接状态"):
        dm.sync_connected()

    devices = dm.get_all()
    
    # ── 判断是否是 VPS 公网运行环境 ──
    is_vps = False
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        host = headers.get("Host") or ""
        # 如果 Host 不是 localhost / 127.0.0.1 / 192.168.x.x，判定为公网环境
        if host and not any(x in host for x in ("localhost", "127.0.0.1", "192.168.")):
            is_vps = True
    except Exception:
        pass

    if not devices:
        if is_vps:
            st.warning(
                "⚠️ **您当前使用的是公网 VPS 网页后台**\n\n"
                "由于手机是用 USB 数据线插在您的**本地电脑**上，公网 VPS 无法跨越网络直接读取您本地电脑的 USB 接口，因此这里不会显示任何 USB 设备。\n\n"
                "**💡 极简解决方案（推荐）：**\n"
                "- **无需连接电脑**，请直接点击上方 **「📱 手机自治挂机 (免电脑)」** 选项卡。\n"
                f"- 按照说明在手机 Termux 中直接输入 `curl -sSL http://{host or '<你的VPS>'}/api/phone-agent/setup | bash` 命令，"
                "脚本会自动安装环境、拉取 phone_agent、自动注册到 VPS 并立刻挂机上线。\n\n"
                "**💻 如仍需使用电脑 USB 灌装：**\n"
                "1. **请在您的本地电脑上运行本地服务**：双击本地目录下的 `start_web.bat`（启动本地网页端）。\n"
                "2. 在本地电脑的浏览器中打开：[http://localhost:8501](http://localhost:8501)。\n"
                "3. 在本地网页的「📱 设备管理」中，即可看到您插在电脑上的手机并点击「🚀 初始化 Agent」灌装！\n"
                "4. 灌装完成后拔掉 USB，在手机上输入 `start`，设备就会自动同步并显示在当前的公网网页上了！"
            )
        else:
            st.info(
                "💡 **暂无已注册设备。**\n\n"
                "请将手机通过 USB 连接至电脑。如果已连接但仍未显示，请检查：\n"
                "1. 手机是否已开启**「开发者选项」**和**「USB 调试」**。\n"
                "2. 手机下拉通知栏的 USB 连接模式是否已设为**「传输文件」**（MTP）。\n"
                "3. 电脑是否已安装该手机的 **USB 驱动**（特别是华为/OPPO等手机，不装驱动电脑无法识别）。"
            )
    else:
        _render_device_cards(dm, devices)


def render_devices_tab():
    """Render device management UI."""
    st.subheader("📱 设备列表")

    dm = get_device_manager()
    adb_ok = dm.check_adb_available()

    if not adb_ok:
        st.error(
            "❌ **ADB 环境问题** — ADB 命令未找到。\n\n"
            "**解决方案：**\n"
            "1. 下载 Android SDK Platform-Tools: https://developer.android.google.cn/studio/releases/platform-tools\n"
            "2. 解压到本地，记下路径\n"
            "3. 将路径添加到系统 PATH 环境变量\n"
            "4. 重启本应用\n\n"
            "**或者临时测试：** 在终端运行以下命令后再重启本应用\n"
            "`$env:PATH = 'C:\\path\\to\\platform-tools;' + $env:PATH`\n\n"
            "需要帮助？查看 [Android 调试官方文档](https://developer.android.google.cn/studio/debug/debug-device)",
            icon="❌",
        )
        if st.button("🔄 重新检查 ADB"):
            st.rerun()
        return

    # ── 实时检测通过 USB/WiFi 连接但未注册的设备 ──
    try:
        live_serials = dm.list_connected_serials()
    except Exception:
        live_serials = []
    
    registered_serials = {d.serial for d in dm.get_all()}
    unregistered = [s for s in live_serials if s not in registered_serials]
    
    if unregistered:
        for s in unregistered:
            st.warning(f"🔌 **检测到新设备已接入（未注册）：`{s}`**")
            col_reg, _ = st.columns([2, 3])
            with col_reg:
                if st.button(f"⚡ 快速注册并启用 `{s}`", key=f"quick_reg_init_{s}"):
                    dm.add_device(serial=s, name="自动添加设备", theme="默认主题")
                    st.success(f"设备 `{s}` 注册成功！")
                    st.rerun()

    _render_auto_refresh_device_list(dm)

    # ── 客户端挂机小助手下载引导 ──
    st.markdown("---")
    st.subheader("🖥️ 挂机节点扩展助手")
    st.info(
        "💡 **分布式多电脑矩阵挂机**：\n"
        "如果你想在其他 Windows 电脑上插手机并连接到本云端，只需在新电脑上运行本助手即可，一键双击直连，无需配置 Python 环境！\n\n"
        "1. 点击下方按钮，下载挂机小助手程序到你的新电脑；\n"
        "2. 将新电脑的手机开启 USB 调试并连入新电脑；\n"
        "3. 双击运行小助手即可立刻在当前网页捕获新接入的设备！"
    )
    
    from pathlib import Path
    exe_path = Path(__file__).resolve().parent.parent.parent / "local_agent.exe"
    if exe_path.exists():
        with open(exe_path, "rb") as f:
            st.download_button(
                label="📥 点击一键下载 Windows 挂机助手 (.exe)",
                data=f.read(),
                file_name="local_agent.exe",
                mime="application/octet-stream",
                key="download_local_agent_exe",
                use_container_width=True
            )
    else:
        st.warning("⏳ 挂机小助手 .exe 后台程序正在云端编译中，稍后刷新页面即可点击下载。")

    # Add device section
    st.markdown("---")
    st.subheader("➕ 添加设备")

    tab_usb, tab_wifi, tab_pair = st.tabs(["USB 连接", "鸿蒙 / 手动 WiFi", "Android 11+ 无线配对"])

    with tab_usb:
        st.info(
            "通过 USB 连接手机后，运行 `adb devices` 获取 Serial，再填入下方。\n"
            "确保手机已开启开发者模式和 USB 调试。"
        )
        with st.form("add_usb_device"):
            serial = st.text_input("设备 Serial", placeholder="如：emulator-5554")
            name = st.text_input("设备名称", placeholder="如：主号手机")
            theme = st.text_input("内容主题", placeholder="如：旅行摄影")
            if st.form_submit_button("注册设备"):
                if serial.strip():
                    dm.add_device(serial=serial.strip(), name=name.strip(), theme=theme.strip())
                    st.success(f"已注册设备 {serial}")
                    st.rerun()

    with tab_wifi:
        st.info(
            "**适用设备**：华为 / 荣耀 鸿蒙系统（HarmonyOS），以及任何可在设置中看到 IP:端口 的无线调试设备。\n\n"
            "鸿蒙无线调试由**手机显示 IP:端口**，电脑主动发起连接，无需配对码。"
        )

        st.markdown("##### 📱 手机端操作步骤")
        st.markdown(
            "1. 打开「设置」→「关于手机」，连续点击「版本号」7 次，开启**开发者选项**\n"
            "2. 进入「设置」→「开发者选项」→「无线调试」→ **打开开关**\n"
            "3. 屏幕上会显示形如 `192.168.x.x:xxxxx` 的 **IP 地址和端口**\n"
            "4. 将上方 IP 和端口填入下方表单，点击「连接并注册」\n"
            "5. 手机弹出授权弹窗，选择「允许」即可 ✅"
        )

        st.markdown("---")
        st.markdown("##### ✍️ 填写 IP 连接")
        with st.form("add_wifi_device"):
            host = st.text_input("手机 IP 地址", placeholder="如：192.168.1.100")
            port = st.number_input("ADB 端口", value=5555, min_value=1, max_value=65535)
            name = st.text_input("设备名称", placeholder="如：鸿蒙主机")
            theme = st.text_input("内容主题", placeholder="如：美食探店")
            if st.form_submit_button("连接并注册"):
                if host.strip():
                    serial = f"{host.strip()}:{int(port)}"
                    ok, adb_msg = dm.connect_wifi(host.strip(), int(port))
                    if ok:
                        dm.add_device(serial=serial, name=name.strip(), theme=theme.strip())
                        st.success(f"WiFi 连接成功：{serial}")
                        st.rerun()
                    else:
                        _hint = _wifi_connect_hint(adb_msg)
                        st.error(f"连接失败 `{serial}`\n\nADB 返回：`{adb_msg}`\n\n{_hint}")

    with tab_pair:
        st.info(
            "**Android 11+ 无线调试（无需 USB）**\n\n"
            "1. 手机：**设置 → 开发者选项 → 无线调试 → 开启**\n"
            "2. 点击「**使用配对码配对设备**」，屏幕会出现 IP、**配对端口**、**6 位配对码**\n"
            "3. 将上述信息填入「**第一步：配对**」并提交\n"
            "4. 配对成功后，回到无线调试主页查看「**IP 地址和端口**」（连接端口），填入「**第二步：连接**」\n\n"
            "> 配对端口和连接端口是**不同**的，注意区分"
        )

        # ── mDNS auto-discovery ────────────────────────────────────────────
        st.markdown("##### 🔍 自动发现（mDNS，Android 11+）")
        st.caption("已开启「无线调试」的设备会通过 mDNS 广播，点击扫描可直接发现，无需手填 IP。")
        if "mdns_scan_results" not in st.session_state:
            st.session_state["mdns_scan_results"] = None

        mdns_col, _ = st.columns([1, 3])
        with mdns_col:
            if st.button("🔍 扫描 mDNS 设备", key="scan_mdns_btn"):
                if not hasattr(dm, "scan_mdns"):
                    st.error("功能需重启 Streamlit 才能加载，请关闭并重新运行 `start_web.bat`")
                else:
                    with st.spinner("正在扫描 mDNS（约 5 秒）…"):
                        mdns_found = dm.scan_mdns(timeout=5.0)
                    st.session_state["mdns_scan_results"] = mdns_found

        mdns_res = st.session_state.get("mdns_scan_results")
        if mdns_res is not None:
            connect_entries = [r for r in mdns_res if r["type"] == "connect"]
            pair_entries    = [r for r in mdns_res if r["type"] == "pair"]
            if not mdns_res:
                st.warning(
                    "未发现 mDNS 设备。请确认：\n"
                    "- 手机与电脑在同一 WiFi\n"
                    "- 手机已开启「无线调试」\n"
                    "- adb 版本 ≥ 30（`adb --version`）"
                )
            if connect_entries:
                st.success(f"发现 {len(connect_entries)} 台可直接连接的设备：")
                for _e in connect_entries:
                    _ec1, _ec2 = st.columns([3, 1])
                    with _ec1:
                        st.code(_e["serial"])
                    with _ec2:
                        if st.button("一键连接", key=f"mdns_connect_{_e['serial']}"):
                            _ok, _msg = dm.connect_wifi(_e["ip"], _e["port"])
                            if _ok:
                                dm.add_device(serial=_e["serial"], name=_e["ip"], theme="")
                                st.success(f"✅ 已连接并注册：{_e['serial']}")
                                st.session_state["mdns_scan_results"] = None
                                st.rerun()
                            else:
                                st.error(f"连接失败：{_e['serial']}")
            if pair_entries:
                st.info(
                    f"发现 {len(pair_entries)} 台待配对设备（下方填入配对码完成配对）："
                )
                for _p in pair_entries:
                    st.code(f"IP: {_p['ip']}  配对端口: {_p['port']}")
                    st.session_state["_pair_host"] = _p["ip"]

        st.markdown("---")

        st.markdown("##### 第一步：配对")
        with st.form("pair_wifi_step1"):
            p_host = st.text_input("手机 IP", placeholder="如：192.168.1.100", key="p_host")
            p_pair_port = st.number_input("配对端口（Pair Port）", min_value=1, max_value=65535, value=40123, key="p_pair_port")
            p_code = st.text_input("配对码（6 位数字）", placeholder="如：123456", key="p_code", max_chars=8)
            if st.form_submit_button("🔗 执行 adb pair"):
                if p_host.strip() and p_code.strip():
                    ok, msg = dm.pair_wireless(p_host.strip(), int(p_pair_port), p_code.strip())
                    if ok:
                        st.success(f"✅ 配对成功！{msg}")
                        st.session_state["_pair_host"] = p_host.strip()
                    else:
                        st.error(f"❌ 配对失败：{msg}")
                else:
                    st.warning("请填写 IP 和配对码")

        st.markdown("##### 第二步：连接并注册")
        pair_host_default = st.session_state.get("_pair_host", "")
        with st.form("pair_wifi_step2"):
            c_host = st.text_input("手机 IP", value=pair_host_default, placeholder="同上", key="c_host")
            c_port = st.number_input("连接端口（无线调试主页的端口）", min_value=1, max_value=65535, value=5555, key="c_port")
            c_name = st.text_input("设备名称", placeholder="如：测试手机", key="c_name")
            c_theme = st.text_input("内容主题", placeholder="如：健身打卡", key="c_theme")
            if st.form_submit_button("📲 连接并注册设备"):
                if c_host.strip():
                    serial = f"{c_host.strip()}:{int(c_port)}"
                    ok, adb_msg = dm.connect_wifi(c_host.strip(), int(c_port))
                    if ok:
                        dm.add_device(serial=serial, name=c_name.strip(), theme=c_theme.strip())
                        st.success(f"✅ 已连接并注册设备：{serial}")
                        st.rerun()
                    else:
                        _hint = _wifi_connect_hint(adb_msg)
                        st.error(f"连接失败 `{serial}`\n\nADB 返回：`{adb_msg}`\n\n{_hint}")

    # Publish automation settings
    st.markdown("---")
    render_publish_settings()


def render_publish_settings():
    """Render XHS publish automation settings panel."""
    with st.expander("⚙️ 发布自动化设置", expanded=False):
        from pixelle_video.config import config_manager

        cfg = getattr(config_manager.config, "xhs_publish", None)
        current_strict = getattr(cfg, "strict_mode", True) if cfg else True
        current_push_dir = (
            getattr(cfg, "push_dir", "/sdcard/DCIM/PixelleVideo")
            if cfg
            else "/sdcard/DCIM/PixelleVideo"
        )

        st.markdown(
            "控制小红书自动发布的行为模式。\n\n"
            "- **严格模式（推荐）**：找不到控件时立即报错，避免误触。\n"
            "- **兼容模式**：找不到控件时回退到坐标点击（可能误触，仅在严格模式下无法正常工作时使用）。"
        )
        if cfg is None:
            st.info("未找到 xhs_publish 配置，当前使用默认值。点击“保存设置”可写回配置文件。")

        col1, col2 = st.columns([2, 1])
        with col1:
            new_strict = st.toggle(
                "严格模式（找不到控件时报错）",
                value=current_strict,
                key="xhs_strict_mode_toggle",
                help="关闭后切换为兼容模式：找不到控件时回退到坐标点击。不推荐长期使用兼容模式。",
            )
            new_push_dir = st.text_input(
                "图片推送目录（设备侧）",
                value=current_push_dir,
                key="xhs_push_dir_input",
                help="图片发布前临时存放在设备上的路径，发布完成后会自动删除。",
            )
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 保存设置", key="save_xhs_settings"):
                config_manager.update(
                    {"xhs_publish": {"strict_mode": new_strict, "push_dir": new_push_dir.strip()}}
                )
                config_manager.save()
                st.success("已保存")
                st.rerun()

        st.markdown("---")
        st.markdown("##### 🔌 ADB Server 设置（代理/远程）")
        st.caption(
            "默认 ADB Server 运行在本机 `127.0.0.1:5037`。"
            "如果手机接在**同局域网其他电脑**上，可将那台电脑以 "
            "`adb -a nodaemon server start` 启动监听，然后在此填写该机 IP。"
        )
        current_adb_host = getattr(cfg, "adb_server_host", "127.0.0.1") if cfg else "127.0.0.1"
        current_adb_port = getattr(cfg, "adb_server_port", 5037) if cfg else 5037
        col_h, col_p, col_abtn = st.columns([3, 1, 1])
        with col_h:
            new_adb_host = st.text_input(
                "ADB Server 地址",
                value=current_adb_host,
                key="adb_server_host_input",
                placeholder="127.0.0.1",
            )
        with col_p:
            new_adb_port = st.number_input(
                "端口",
                value=current_adb_port,
                min_value=1,
                max_value=65535,
                key="adb_server_port_input",
            )
        with col_abtn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 保存 ADB", key="save_adb_server"):
                host_val = new_adb_host.strip() or "127.0.0.1"
                port_val = int(new_adb_port)
                config_manager.update(
                    {"xhs_publish": {"adb_server_host": host_val, "adb_server_port": port_val}}
                )
                config_manager.save()
                get_device_manager().configure_adb_server(host_val, port_val)
                st.success("ADB Server 设置已保存并生效")
                st.rerun()


# ---- Publish Queue Tab -------------------------------------------------------

def render_publish_tab():
    """Render publish queue management UI."""
    st.subheader("📤 发布队列")

    from pixelle_video.config import config_manager as _cm
    _xhs_cfg = _cm.config.xhs_publish

    scheduler = get_publish_scheduler()
    dm = get_device_manager()
    _init_publish_form_defaults()



    # Job list
    st.markdown("---")
    status_filter = st.selectbox(
        "筛选状态",
        options=["全部", "pending", "scheduled", "running", "success", "done", "failed", "cancelled", "deleted"],
        index=0,
    )
    filter_val = None if status_filter == "全部" else status_filter

    col_refresh, col_bulk = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 刷新队列"):
            get_publish_scheduler()._load()
            st.rerun()

    # ---- Bulk actions ----------------------------------------------------
    scheduler = get_publish_scheduler()
    all_jobs = scheduler.list_jobs()
    counts = {
        "pending_active": sum(1 for j in all_jobs if j.status in ("pending", "scheduled")),
        "completed":      sum(1 for j in all_jobs if j.status in ("success", "done", "deleted")),
        "failed":         sum(1 for j in all_jobs if j.status in ("failed", "cancelled")),
    }
    counts["ttl_expired"] = sum(
        1 for j in all_jobs
        if getattr(j, "delete_after_hours", None)
        and j.finished_at
        and j.status in ("success", "done")
        and (
            datetime.fromisoformat(j.finished_at)
            + timedelta(hours=j.delete_after_hours)
        ) <= datetime.now()
    )

    with st.expander(
        f"🛠️ 批量操作  "
        f"(待发布 {counts['pending_active']}  |  已完成 {counts['completed']}  |  失败/取消 {counts['failed']}"
        + (f"  |  ⚠️ TTL已过期 {counts['ttl_expired']}" if counts["ttl_expired"] else "")
        + ")"
    ):
        bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns(5)

        with bcol1:
            if st.button(
                "🚀 立即执行待发布",
                key="bulk_exec_pending",
                disabled=counts["pending_active"] == 0,
                help="对所有 pending/scheduled 任务立刻触发执行",
                width="stretch",
            ):
                pending_ids = [
                    j.job_id for j in all_jobs if j.status in ("pending", "scheduled")
                ]
                ok = 0
                for jid in pending_ids:
                    if run_async(scheduler.execute_now(jid)):
                        ok += 1
                st.success(f"已触发 {ok}/{len(pending_ids)} 个任务")
                st.rerun()

        with bcol2:
            if st.button(
                "⛔ 取消所有待发布",
                key="bulk_cancel_pending",
                disabled=counts["pending_active"] == 0,
                width="stretch",
            ):
                n = scheduler.bulk_cancel_pending()
                st.success(f"已取消 {n} 个任务")
                st.rerun()

        with bcol3:
            if st.button(
                "🧹 清理已完成",
                key="bulk_remove_done",
                disabled=counts["completed"] == 0,
                help="从队列中移除 success/done/deleted 状态的任务记录",
                width="stretch",
            ):
                n = scheduler.bulk_remove(["success", "done", "deleted"])
                st.success(f"已清理 {n} 个已完成任务")
                st.rerun()

        with bcol4:
            if st.button(
                "🗑️ 清理失败/取消",
                key="bulk_remove_failed",
                disabled=counts["failed"] == 0,
                width="stretch",
            ):
                n = scheduler.bulk_remove(["failed", "cancelled"])
                st.success(f"已清理 {n} 个失败/取消任务")
                st.rerun()

        with bcol5:
            if st.button(
                "🧹 扫清过期 TTL 帖",
                key="bulk_ttl_sweep",
                help="检查所有已完成任务，删除超过 TTL 的帖子（等同后台自动定时扫描）",
                disabled=counts["ttl_expired"] == 0,
                type="primary" if counts["ttl_expired"] > 0 else "secondary",
                width="stretch",
            ):
                import asyncio as _asyncio
                import concurrent.futures
                with st.spinner("删除过期帖子中…"):
                    try:
                        with concurrent.futures.ThreadPoolExecutor() as _pool:
                            _pool.submit(_asyncio.run, scheduler.check_and_delete_expired()).result(timeout=120)
                    except Exception as _e:
                        st.error(f"扫清异常: {_e}")
                st.success(f"扫清完成，已遍历 {counts['ttl_expired']} 个过期帖")
                st.rerun()

    _render_publish_queue_list(filter_val)


@st.fragment(run_every="6s")
def _render_publish_queue_list(filter_val: str | None):
    scheduler = get_publish_scheduler()
    jobs = scheduler.list_jobs(status_filter=filter_val)
    st.caption("发布队列每 6 秒自动刷新一次。")

    if not jobs:
        st.info("队列为空")
        return

    for job in jobs:
        badge = STATUS_BADGE.get(job.status, job.status)
        kind = getattr(job, "kind", "image_text") or "image_text"
        kind_tag = "🎬 视频" if kind == "video" else "🖼️ 图文"
        post_type = getattr(job, "post_type", "content") or "content"
        type_tag = "📢 引流帖" if post_type == "traffic" else "📚 干货帖"
        delete_after = getattr(job, "delete_after_hours", None)
        if delete_after:
            if job.finished_at and job.status in ("success", "done"):
                try:
                    _expire_at = datetime.fromisoformat(job.finished_at) + timedelta(hours=delete_after)
                    _now = datetime.now()
                    if _now >= _expire_at:
                        ttl_tag = "  |  ⚠️ TTL已过期"
                    else:
                        _rem = _expire_at - _now
                        _h, _rem_s = divmod(int(_rem.total_seconds()), 3600)
                        _m = _rem_s // 60
                        ttl_tag = f"  |  ⏱️ 还剩 {_h}h {_m}m"
                except Exception:
                    ttl_tag = f"  |  ⏱️ TTL {delete_after}h"
            else:
                ttl_tag = f"  |  ⏱️ TTL {delete_after}h"
        else:
            ttl_tag = ""
        label = f"{badge}  |  {kind_tag}  |  {type_tag}{ttl_tag}  |  {job.title[:30]}  |  {job.serial}  |  {job.created_at[:16]}"
        with st.expander(label):
            col1, col2 = st.columns([3, 1])
            with col1:
                elapsed = None
                if job.status == "running" and job.started_at:
                    try:
                        started = datetime.fromisoformat(job.started_at)
                        elapsed = int((datetime.now() - started).total_seconds())
                    except Exception:
                        elapsed = None

                payload = {
                    "job_id": job.job_id,
                    "kind": kind,
                    "post_type": post_type,
                    "delete_after_hours": delete_after,
                    "device": job.serial,
                    "task_id": job.task_id,
                    "status": job.status,
                    "scheduled_at": job.scheduled_at,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "error": job.error,
                }
                if kind == "video":
                    payload["video_path"] = getattr(job, "video_path", None)
                else:
                    payload["images"] = job.images
                if elapsed is not None:
                    payload["running_seconds"] = elapsed

                # Show TTL expiry for traffic posts
                if delete_after and job.finished_at:
                    try:
                        expire_at = datetime.fromisoformat(job.finished_at) + timedelta(hours=delete_after)
                        now = datetime.now()
                        if now < expire_at:
                            remaining = expire_at - now
                            h, rem = divmod(int(remaining.total_seconds()), 3600)
                            m = rem // 60
                            payload["auto_delete_at"] = expire_at.strftime("%Y-%m-%d %H:%M")
                            payload["delete_in"] = f"{h}h {m}m"
                            st.info(
                                f"⏱️ TTL 倒计时：帖子将于 **{expire_at.strftime('%Y-%m-%d %H:%M')}** 自动删除"
                                f"（还剩 **{h}h {m}m**）"
                            )
                        else:
                            payload["auto_delete_at"] = "已过期（等待下次检查）"
                            st.warning(
                                f"⚠️ TTL 已过期（设定 {delete_after}h），帖子尚未删除。"
                                "可点击批量操作中的《🧹 扫清过期 TTL 帖》立即删除。"
                            )
                    except Exception:
                        pass

                # Show retry count if any retries occurred
                retry_count = getattr(job, "retry_count", 0)
                if retry_count:
                    st.info(f"🔄 已重试 {retry_count} 次（共 {retry_count + 1} 次尝试）")

                st.json(payload)

                # Real-time progress log (written by XHSPublisher callback)
                progress_log = getattr(job, "progress_log", None) or []
                if progress_log:
                    with st.expander(f"📋 执行日志（{len(progress_log)} 条）", expanded=(job.status == "running")):
                        for entry in progress_log:
                            st.text(entry)
                elif job.status == "running":
                    st.caption("⏳ 正在等待设备回报进度…")

                # Inline preview for video jobs
                if kind == "video":
                    vp = getattr(job, "video_path", None)
                    if vp and Path(vp).exists():
                        try:
                            st.video(vp)
                        except Exception:
                            st.caption(f"无法预览视频：{vp}")
                    elif vp:
                        st.caption(f"⚠️ 视频文件不存在：{vp}")

                # Debug screenshots (saved by XHSPublisher during automation)
                screenshots = getattr(job, "screenshots", []) or []
                if screenshots:
                    existing = [p for p in screenshots if Path(p).exists()]
                    with st.expander(f"📸 调试截图（{len(existing)}/{len(screenshots)} 张可用）"):
                        if existing:
                            cols = st.columns(min(3, len(existing)))
                            for idx, sc_path in enumerate(existing):
                                with cols[idx % 3]:
                                    try:
                                        st.image(sc_path, caption=Path(sc_path).name, width="stretch")
                                    except Exception:
                                        st.caption(f"无法加载：{Path(sc_path).name}")
                        else:
                            st.caption("截图文件已清理或路径变更")

                if elapsed is not None and elapsed > 600:
                    st.warning(f"任务已运行 {elapsed // 60} 分钟，请观察设备侧是否仍在操作")

            with col2:
                if job.status in ("pending", "scheduled"):
                    if st.button("▶️ 立即执行", key=f"run_{job.job_id}"):
                        import concurrent.futures
                        import asyncio as _asyncio
                        with st.spinner("正在发布帖子…"):
                            try:
                                with concurrent.futures.ThreadPoolExecutor() as _pool:
                                    _future = _pool.submit(_asyncio.run, scheduler.execute_now(job.job_id))
                                    _future.result(timeout=300)
                            except Exception as _e:
                                st.error(f"发布异常: {_e}")
                        st.rerun()
                if job.status in ("pending", "scheduled", "running"):
                    if st.button("❌ 取消", key=f"cancel_{job.job_id}"):
                        scheduler.cancel_job(job.job_id)
                        st.rerun()
                # Delete and Comment for completed posts
                if job.status in ("done", "success") and job.status != "deleted":
                    if st.button("🗑️ 删除帖子", key=f"delete_{job.job_id}", use_container_width=True):
                        import concurrent.futures
                        import asyncio as _asyncio
                        with st.spinner("正在删除帖子…"):
                            try:
                                with concurrent.futures.ThreadPoolExecutor() as _pool:
                                    _future = _pool.submit(_asyncio.run, scheduler.delete_post_now(job.job_id))
                                    ok = _future.result(timeout=120)
                            except Exception as _e:
                                ok = False
                                st.error(f"删除异常: {_e}")
                        if ok:
                            st.success("帖子已删除")
                            st.rerun()
                        else:
                            st.error("删除失败，请手动删除或查看日志")
                    
                    st.write("") # spacing
                    comment_text = st.text_input(
                        "💬 评论内容",
                        key=f"cmt_text_{job.job_id}",
                        placeholder="输入要发表的评论...",
                        label_visibility="collapsed"
                    )
                    if st.button("💬 发表评论", key=f"cmt_btn_{job.job_id}", use_container_width=True):
                        if not comment_text.strip():
                            st.warning("请输入评论内容")
                        else:
                            import concurrent.futures
                            import asyncio as _asyncio
                            with st.spinner("正在发表评论…"):
                                try:
                                    with concurrent.futures.ThreadPoolExecutor() as _pool:
                                        _future = _pool.submit(
                                            _asyncio.run,
                                            scheduler.comment_post_now(job.job_id, comment_text.strip())
                                        )
                                        ok = _future.result(timeout=120)
                                except Exception as _e:
                                    ok = False
                                    st.error(f"评论异常: {_e}")
                            if ok:
                                st.success("评论发表成功")
                                st.rerun()
                            else:
                                st.error("评论发表失败")


# ---- Client Agent Tab --------------------------------------------------------

def render_client_agent_tab():
    """Render client agent pull-mode management tab."""
    st.subheader("💻 客户端代理模式 (多端拉取)")
    st.caption("适合多用户协作：其他发布人员在他们自己的电脑上运行代理，控制自己电脑上连接的手机进行自动发布。")

    from pixelle_video.config import config_manager
    
    # 1. Distribution Mode Selector
    from pixelle_video.services.android_device_dispatcher import DistributionAdapter
    current_mode = DistributionAdapter.get_mode()
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"当前系统分发模式：**`{current_mode}`**")
        if current_mode == "agent_pull":
            st.success("🟢 客户端代理模式已启用。任务已加入云端队列，等待局域网/公网的客户端代理拉取。")
        else:
            st.warning(f"⚠️ 当前处于 `{current_mode}` 模式下，系统不会把发布任务派发给客户端代理。")
            
        st.info("💡 如果要切换为 agent_pull 模式或配置云端中转，请前往「⚙️ 系统设置」页面。")
                
    with col2:
        st.info(
            "ℹ️ **什么是客户端代理模式？**\n\n"
            "在该模式下，你可以在网页里统一生成并排期帖子，"
            "然后把命令行和脚本分享给别人。他们运行后，代理会自动从你的服务器下载视频/图片，"
            "并控制他们手机上的小红书发布！"
        )

    st.markdown("---")

    # 2. Setup Guide
    st.subheader("💡 快速使用指南 (分享给其他使用者)")
    
    # Resolve local/public server IP
    server_port = 8000
    local_ip = "23.238.47.62"
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        host = headers.get("Host") or ""
        if host:
            host_clean = host.split(":")[0]
            if host_clean not in ("127.0.0.1", "localhost", ""):
                if "23-238-47-62" in host_clean:
                    local_ip = "23.238.47.62"
                else:
                    local_ip = host_clean
            else:
                import socket
                hostname = socket.gethostname()
                ip_list = socket.gethostbyname_ex(hostname)[2]
                lan_ips = [ip for ip in ip_list if ip.startswith("192.168.") or ip.startswith("10.")]
                if lan_ips:
                    local_ip = lan_ips[0]
    except Exception:
        pass
        
    # Batch script content for Windows (Pure ASCII to avoid cmd.exe parsing crashes)
    bat_content = f"""@echo off
echo ======================================================
echo       Pixelle-Video Client Agent Startup Script
echo ======================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on your system!
    echo Please install Python 3.9 or higher and check "Add Python to PATH".
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 2. Set Server URL
set SERVER_URL=http://{local_ip}:{server_port}
echo Server URL: %SERVER_URL%

:: 3. Prepare Directory
set AGENT_DIR=%USERPROFILE%\\PixelleAgent
echo Preparing agent directory: %AGENT_DIR%
if not exist "%AGENT_DIR%" mkdir "%AGENT_DIR%"
cd /d "%AGENT_DIR%"

:: 4. Download Client
echo.
echo Downloading agent package from server...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%SERVER_URL%/api/publish/agent/download-client', 'pixelle_agent.zip')"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Download failed!
    echo Please check:
    echo 1. Is your PC in the same network/LAN as the server?
    echo 2. Is the server running?
    echo 3. Does the server firewall allow port {server_port}?
    echo.
    pause
    exit /b 1
)

:: 5. Unzip
echo.
echo Unzipping package...
powershell -Command "Expand-Archive -Path 'pixelle_agent.zip' -DestinationPath '.' -Force"
if %errorlevel% neq 0 (
    echo [ERROR] Unzip failed!
    pause
    exit /b 1
)
del pixelle_agent.zip

:: 6. Dependencies
echo.
echo Installing dependencies (requests, uiautomator2, loguru, pyyaml)...
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests uiautomator2 loguru pyyaml
if %errorlevel% neq 0 (
    echo [WARNING] Dependency installation failed or had warnings. Trying to run anyway...
)

:: 7. Run Agent
echo.
echo ------------------------------------------------------
echo Starting agent. Ensure USB debugging is enabled on your phone.
echo ------------------------------------------------------
echo.
python scripts/local_agent.py --server %SERVER_URL%
if %errorlevel% neq 0 (
    echo.
    echo [INFO] Agent execution stopped.
    pause
)
"""
    # Normalize line endings to Windows CRLF (\r\n) for batch file compatibility
    bat_content = bat_content.replace("\r\n", "\n").replace("\n", "\r\n")


    # Shell script content for macOS/Linux
    sh_content = f"""#!/bin/bash
echo "======================================================"
echo "      Pixelle-Video 客户端代理一键启动脚本 (Mac/Linux)"
echo "======================================================"
echo

# 1. 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3 环境！"
    echo "请先安装 Python 3 (建议 3.9 或更高版本)。"
    exit 1
fi

# 2. 设置服务器地址
SERVER_URL="http://{local_ip}:{server_port}"
echo "服务器地址: $SERVER_URL"

# 3. 准备工作目录
AGENT_DIR="$HOME/PixelleAgent"
echo "正在准备工作目录: $AGENT_DIR"
mkdir -p "$AGENT_DIR"
cd "$AGENT_DIR" || exit 1

# 4. 下载代理包
echo
echo "正在从服务器下载代理程序包..."
if command -v curl &> /dev/null; then
    curl -L -o pixelle_agent.zip "$SERVER_URL/api/publish/agent/download-client"
elif command -v wget &> /dev/null; then
    wget -O pixelle_agent.zip "$SERVER_URL/api/publish/agent/download-client"
else
    echo "[错误] 未找到 curl 或 wget，无法下载代理包！"
    exit 1
fi

if [ $? -ne 0 ]; then
    echo "[错误] 下载失败！"
    exit 1
fi

# 5. 解压代理包
echo
echo "正在解压缩代理程序包..."
if command -v unzip &> /dev/null; then
    unzip -o pixelle_agent.zip
else
    # 回退到 python 解压
    python3 -c "import zipfile; zipfile.ZipFile('pixelle_agent.zip').extractall('.')"
fi
rm -f pixelle_agent.zip

# 6. 安装依赖
echo
echo "正在检查并安装 Python 依赖项..."
python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests uiautomator2 loguru pyyaml
if [ $? -ne 0 ]; then
    echo "[警告] 依赖项安装可能遇到问题，尝试继续运行..."
fi

# 7. 启动代理
echo
echo "------------------------------------------------------"
echo "正在启动客户端代理，请确保手机已通过 USB 连接并开启 USB 调试！"
echo "------------------------------------------------------"
echo
python3 scripts/local_agent.py --server "$SERVER_URL"
"""

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        st.download_button(
            label="📥 下载 Windows 一键启动脚本 (start_agent.bat)",
            data=bat_content,
            file_name="start_agent.bat",
            mime="application/x-bat",
            type="primary",
            use_container_width=True,
            help="适合 Windows 系统用户，下载后双击即可全自动运行。"
        )
    with col_btn2:
        st.download_button(
            label="📥 下载 macOS / Linux 一键启动脚本 (start_agent.sh)",
            data=sh_content,
            file_name="start_agent.sh",
            mime="text/x-sh",
            use_container_width=True,
            help="适合 macOS / Linux 系统用户。下载后需要在终端运行 chmod +x start_agent.sh 赋予权限，然后运行。"
        )

    st.markdown("#### 🚀 使用步骤（零配置，一步到位）：")
    st.markdown(
        "1. **准备电脑与手机**：\n"
        "   - 使用 USB 数据线连接手机与电脑，确保开启手机的「开发者选项」和「USB 调试」模式。\n"
        "   - 确保电脑上安装了 Python 环境 (3.9+)。\n"
        "2. **一键运行代理**：\n"
        "   - **Windows**：双击下载的 `start_agent.bat` 脚本即可。脚本会自动下载代理包、解压、安装依赖并运行。\n"
        "   - **macOS / Linux**：打开终端，运行 `chmod +x start_agent.sh` 赋予权限，然后运行 `./start_agent.sh` 即可。\n"
        "3. **自动同步**：运行后，代理会在终端显示连接成功，并在此电脑连接的手机上自动执行服务器下发的帖子发布、评论或删除任务。"
    )

    st.caption(f"当前配置的连接服务器地址为：`http://{local_ip}:{server_port}`。如需外网使用，可自行编辑下载的脚本文件，将服务器 IP 修改为您的公网 IP 或域名。")
    st.markdown("---")

    # 3. Active Agents Monitor (using st.fragment for auto-refresh)
    st.subheader("🖥️ 在线代理监控")
    
    @st.fragment(run_every="5s")
    def render_agents_list():
        st.caption("在线代理状态每 5 秒自动更新一次。")
        import requests
        agents = []
        try:
            res = requests.get(f"http://127.0.0.1:{server_port}/api/publish/agent/list", timeout=2)
            if res.status_code == 200:
                agents = res.json().get("agents", [])
        except Exception:
            st.warning("⚠️ 无法获取在线代理列表，请确认 API 服务已在 8000 端口启动。")
            return
            
        if not agents:
            st.info("🔌 当前暂无在线的客户端代理。请在其电脑上运行上述代理命令。")
            return
            
        for idx, agent in enumerate(agents):
            agent_id = agent.get("agent_id") or f"agent_{idx}"
            ip = agent.get("ip") or "未知"
            serials = agent.get("serials") or []
            last_seen_str = agent.get("last_seen", "")
            
            # Format last seen
            try:
                dt = datetime.fromisoformat(last_seen_str)
                if dt.tzinfo is not None:
                    dt = dt.astimezone().replace(tzinfo=None)
                seconds_ago = int((datetime.now() - dt).total_seconds())
                if seconds_ago < 0:
                    seconds_ago = 0
                if seconds_ago < 5:
                    seen_label = "刚刚 (活跃)"
                else:
                    seen_label = f"{seconds_ago} 秒前"
            except Exception:
                seen_label = last_seen_str
                seconds_ago = 999
                
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 1])
                with c1:
                    st.markdown(f"💻 **代理 ID**: `{agent_id}`")
                    st.markdown(f"🌐 **客户端 IP**: `{ip}`")
                with c2:
                    st.markdown(f"📱 **检测到手机数量**: `{len(serials)}` 台")
                    if serials:
                        st.markdown(f"📋 **手机 Serial**: `{', '.join(serials)}`")
                    else:
                        st.markdown("⚠️ *未检测到已连接手机，请确保已运行 adb devices 并授权*")
                with c3:
                    st.markdown(f"⏱️ **最后心跳**: {seen_label}")
                    st.markdown("🟢 **在线**" if "刚刚" in seen_label or seconds_ago <= 15 else "🔴 **离线**")

    render_agents_list()


# ---- Main --------------------------------------------------------------------

# ---- Main --------------------------------------------------------------------

def main():
    init_session_state()
    init_i18n()

    # ---- 违禁词命中 toast -------------------------------------------------------
    try:
        from pixelle_video.utils.banned_keywords import read_audit as _read_audit
        _audit_all = _read_audit(last_n=100)
        _audit_prev = st.session_state.get("_audit_seen_count", len(_audit_all))
        _audit_new = _audit_all[_audit_prev:]
        if _audit_new:
            st.session_state["_audit_seen_count"] = len(_audit_all)
            for _ae in _audit_new:
                _hits_str = "、".join(_ae.get("hits", []))
                _job_short = (_ae.get("job_id") or "")[:8]
                st.toast(
                    f"🚫 违禁词已过滤（任务 {_ae.get('task_id', '')}）：{_hits_str}  [Job {_job_short}…]",
                    icon="⚠️",
                )
        elif "_audit_seen_count" not in st.session_state:
            st.session_state["_audit_seen_count"] = len(_audit_all)
    except Exception:
        pass

    st.title("📱 发布管理")
    st.caption("管理 Android 设备并将图文帖子发布到小红书")

    tab_devices, tab_publish, tab_agent = st.tabs([
        "📱 设备管理",
        "📤 发布队列",
        "💻 客户端代理 (电脑)",
    ])

    with tab_devices:
        render_devices_tab()

    with tab_publish:
        render_publish_tab()

    with tab_agent:
        render_client_agent_tab()


if __name__ == "__main__":
    main()




