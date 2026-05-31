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
        st.info("暂无本地发布设备。请在下方添加 CH9329 串口设备（例如 COM3）。")
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
    st.caption("设备状态每 8 秒自动检测一次；已保存的本地发布设备会自动刷新。")

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
                "本地发布依赖连接在您电脑上的 CH9329 串口控制器，公网 VPS 无法直接访问您本地电脑的 COM 口。\n\n"
                "**推荐方案：**\n"
                "1. 在连接 CH9329 控制器的本地电脑上运行本地网页端。\n"
                "2. 在本地浏览器打开：[http://localhost:8501](http://localhost:8501)。\n"
                "3. 在「设备管理」中添加 CH9329 串口设备（例如 COM3），再执行发布。\n\n"
                "如需多电脑协作，可使用下方客户端代理模式，让本地电脑代理拉取云端任务并控制本地发布设备。"
            )
        else:
            st.info(
                "💡 **暂无已注册的本地发布设备。**\n\n"
                "请在下方添加 CH9329 串口控制器对应的 COM 口（例如 COM3）。"
                "添加后即可通过本地硬件控制手机完成小红书发布。"
            )
    else:
        _render_device_cards(dm, devices)


def render_devices_tab():
    """Render device management UI."""
    st.subheader("📱 设备列表")

    dm = get_device_manager()
    adb_ok = dm.check_adb_available()

    if not adb_ok:
        st.info(
            "ℹ️ **本地发布使用 CH9329 串口模式**\n\n"
            "当前页面使用 CH9329 串口硬件控制。请在下方「CH9329 串口设置」中填写本机 COM 口和波特率，"
            "保存后即可把该串口作为本地发布设备使用。"
        )

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
        "如果你想在其他 Windows 电脑上接入本地发布设备并连接到本云端，只需在新电脑上运行本助手即可，一键双击直连，无需配置 Python 环境！\n\n"
        "1. 点击下方按钮，下载挂机小助手程序到你的新电脑；\n"
        "2. 在新电脑上准备好本地发布设备；\n"
        "3. 双击运行小助手即可立刻在当前网页捕获新接入的本地发布设备！"
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

    st.markdown("##### CH9329 串口设置")
    st.info(
        "CH9329 串口模式是本机发布的主要路径：将 CH9329 控制器接入本机后，"
        "填写系统分配的 COM 口和波特率即可注册为本地发布设备。"
    )
    with st.form("add_ch9329_serial_device"):
        serial = st.text_input("COM 口", placeholder="如：COM3")
        baudrate = st.number_input("波特率", value=9600, min_value=1200, max_value=115200)
        name = st.text_input("设备名称", placeholder="如：主号 CH9329")
        theme = st.text_input("内容主题", placeholder="如：旅行摄影")
        if st.form_submit_button("注册 CH9329 设备"):
            if serial.strip():
                dm.add_device(
                    serial=serial.strip(),
                    name=name.strip() or "CH9329 本地发布设备",
                    theme=theme.strip(),
                    notes=f"CH9329 serial baudrate={int(baudrate)}",
                )
                st.success(f"已注册 CH9329 串口设备 {serial.strip()}（{int(baudrate)} bps）")
                st.rerun()

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
        st.markdown("##### CH9329 串口设置")
        st.caption(
            "本地发布优先使用 CH9329 串口控制器。请确认 COM 口与设备管理中注册的本地发布设备一致。"
        )
        hardware_cfg = getattr(cfg, "hardware", None) if cfg else None
        current_com = getattr(hardware_cfg, "com_port", "COM3") if hardware_cfg else "COM3"
        current_baudrate = getattr(hardware_cfg, "baudrate", 9600) if hardware_cfg else 9600
        col_port, col_baud, col_save = st.columns([2, 1, 1])
        with col_port:
            com_val = st.text_input(
                "COM 口",
                value=current_com,
                key="ch9329_com_port_input",
                placeholder="COM3",
            )
        with col_baud:
            baudrate_val = st.number_input(
                "波特率",
                value=int(current_baudrate),
                min_value=1200,
                max_value=115200,
                key="ch9329_baudrate_input",
            )
        with col_save:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 保存 CH9329", key="save_ch9329_serial_settings"):
                com_val = str(com_val).strip() or "COM3"
                baudrate_val = int(baudrate_val)
                config_manager.update(
                    {"xhs_publish": {"hardware": {"com_port": com_val, "baudrate": baudrate_val}}}
                )
                config_manager.save()
                get_device_manager().add_device(
                    serial=com_val,
                    name="CH9329 发帖机",
                    theme="",
                    notes=f"CH9329 serial baudrate={baudrate_val}",
                )
                st.success("CH9329 串口设置已保存")
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
    st.caption("适合多用户协作：其他发布人员在他们自己的电脑上运行代理，控制自己电脑上连接的本地发布设备进行自动发布。")

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
            "并控制他们的本地发布设备完成小红书发布！"
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
echo Starting agent. Ensure your local publishing device is ready.
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
echo "正在启动客户端代理，请确保本地发布设备已就绪！"
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
        "1. **准备电脑与本地发布设备**：\n"
        "   - 在电脑上接入并确认本地发布设备可用。\n"
        "   - 确保电脑上安装了 Python 环境 (3.9+)。\n"
        "2. **一键运行代理**：\n"
        "   - **Windows**：双击下载的 `start_agent.bat` 脚本即可。脚本会自动下载代理包、解压、安装依赖并运行。\n"
        "   - **macOS / Linux**：打开终端，运行 `chmod +x start_agent.sh` 赋予权限，然后运行 `./start_agent.sh` 即可。\n"
        "3. **自动同步**：运行后，代理会在终端显示连接成功，并在此电脑连接的本地发布设备上自动执行服务器下发的帖子发布、评论或删除任务。"
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
                    st.markdown(f"📱 **检测到本地发布设备数量**: `{len(serials)}` 台")
                    if serials:
                        st.markdown(f"📋 **本地发布设备标识**: `{', '.join(serials)}`")
                    else:
                        st.markdown("⚠️ *未检测到已连接的本地发布设备，请确认客户端代理已完成设备授权并可访问设备*")
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
    st.caption("管理 CH9329 串口发布设备并将图文帖子发布到小红书")

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




