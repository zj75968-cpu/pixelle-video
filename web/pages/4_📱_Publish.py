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

def get_device_manager():
    from pixelle_video.services.device_manager import device_manager
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

                    st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)
                    if st.button("🚀 初始化 Agent", key=f"init_agent_{dev.serial}",
                                 help="一键推送 phone_agent.py 到手机，无需 USB 长期连接"):
                        from pixelle_video.services.phone_agent_setup import (
                            is_termux_installed, push_agent_files, open_termux,
                            try_run_setup_in_termux, _adb, install_termux_via_adb,
                        )

                        # ── 可视化进度 ──────────────────────────────
                        def _step(icon: str, label: str, ok: bool, detail: str = ""):
                            color = "#1a7a1a" if ok else "#a00000"
                            bg = "#e8f5e9" if ok else "#ffebee"
                            bd = "#4caf50" if ok else "#ef9a9a"
                            st.markdown(
                                f'<div style="border:1px solid {bd};border-radius:6px;'
                                f'padding:7px 12px;background:{bg};margin:3px 0">'
                                f'<b style="color:{color}">{icon} {label}</b>'
                                + (f'<br><span style="font-size:.83em;color:#555">{detail}</span>' if detail else "")
                                + "</div>",
                                unsafe_allow_html=True,
                            )

                        steps = st.container()
                        with steps:
                            st.markdown("**初始化进度**")

                            # Step 1: 设备连接
                            rc, out, _ = _adb(dev.serial, "get-state")
                            s1_ok = rc == 0 and "device" in out
                            _step("1️⃣", "ADB 连接验证", s1_ok,
                                  "设备在线" if s1_ok else f"设备未连接或未授权（serial: {dev.serial}）")
                            if not s1_ok:
                                st.stop()

                            # Step 2: Termux 检查 → 自动安装
                            termux_ok = is_termux_installed(dev.serial)
                            if not termux_ok:
                                _step("2️⃣", "Termux 未安装 → 正在自动安装...", True,
                                      "从 GitHub 下载 APK，约 30~60 秒...")
                                install_msgs = []
                                install_result = install_termux_via_adb(
                                    dev.serial,
                                    progress_callback=lambda m: install_msgs.append(m),
                                )
                                termux_ok = install_result["ok"]
                                detail_msg = install_result["message"]
                                if install_msgs:
                                    detail_msg = install_msgs[-1] + " | " + install_result["message"]
                                _step("2️⃣", "Termux 自动安装", termux_ok, detail_msg)
                                if not termux_ok:
                                    st.markdown(
                                        "若自动安装失败，请手动在 **F-Droid** 安装：\n"
                                        "👉 https://f-droid.org/packages/com.termux/"
                                    )
                                    st.stop()
                            else:
                                _step("2️⃣", "Termux 安装检查", True, "已安装")

                            # Step 3: 推送文件
                            push_result = push_agent_files(dev.serial)
                            _step("3️⃣", "脚本文件推送", push_result["ok"],
                                  "已推送: " + ", ".join(push_result["pushed"])
                                  if push_result["ok"] else "失败: " + "; ".join(push_result["errors"]))

                            # Step 4: 打开 Termux
                            termux_opened = open_termux(dev.serial)
                            _step("4️⃣", "打开 Termux", termux_opened,
                                  "Termux 已置于前台" if termux_opened else "打开失败，请手动打开 Termux")

                            # Step 5: 尝试自动执行安装
                            auto_ok = try_run_setup_in_termux(dev.serial)
                            if auto_ok:
                                _step("5️⃣", "自动执行安装脚本", True, "安装进行中，请在手机 Termux 窗口查看进度")
                            else:
                                _step("5️⃣", "手动执行安装脚本", True,
                                      "请在手机 Termux 中输入以下命令（点击可复制）：")
                                st.code("bash /sdcard/pixelle_setup.sh", language="bash")

                            # Step 6: 提示开机自启（可选）
                            _step("6️⃣", "开机自启（可选）", True,
                                  "安装完成后，运行 bash /sdcard/install_termux_boot.sh 启用开机自启")

                            st.success("✅ 初始化完成！完成手机端 Termux 安装后即可在设置页填写 Agent URL。")

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

    _render_auto_refresh_device_list(dm)

    # Add device section
    st.markdown("---")
    st.subheader("➕ 添加设备")

    tab_usb, tab_wifi = st.tabs(["USB 连接", "WiFi 连接"])

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
        with st.form("add_wifi_device"):
            host = st.text_input("手机 IP 地址", placeholder="如：192.168.1.100")
            port = st.number_input("ADB 端口", value=5555, min_value=1, max_value=65535)
            name = st.text_input("设备名称", placeholder="如：副号手机")
            theme = st.text_input("内容主题", placeholder="如：美食探店")
            if st.form_submit_button("连接并注册"):
                if host.strip():
                    serial = f"{host.strip()}:{int(port)}"
                    ok = dm.connect_wifi(host.strip(), int(port))
                    if ok:
                        dm.add_device(serial=serial, name=name.strip(), theme=theme.strip())
                        st.success(f"WiFi 连接成功：{serial}")
                        st.rerun()
                    else:
                        st.error("连接失败，请确认手机已开启 ADB over WiFi")

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


# ---- Gallery Upload Tab ------------------------------------------------------

def render_gallery_upload_tab():
    """Upload image files directly to an Android device's gallery."""
    st.subheader("📸 上传图片到手机相册")
    st.caption("选择手机在线设备，上传图片后会通过 ADB 直接推送到手机相册，无需数据线反复插拔。")

    dm = get_device_manager()
    devices = [d for d in dm.get_all() if d.connected]

    if not devices:
        st.warning("没有已连接的设备。请先在“设备管理”中连接手机。")
        return

    device_options = {f"{d.name or d.serial} ({d.serial})": d.serial for d in devices}
    selected_label = st.selectbox(
        "选择目标设备",
        options=list(device_options.keys()),
        key="gallery_upload_device",
    )
    selected_serial = device_options[selected_label]

    uploaded_files = st.file_uploader(
        "选择图片文件",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="gallery_upload_files",
        help="支持 PNG / JPG / JPEG / WEBP，可多选。",
    )

    if uploaded_files:
        st.info(f"已选择 {len(uploaded_files)} 个文件，点击下方按钮推送到手机相册。")

    if st.button(
        "📲 推送到手机相册",
        disabled=not uploaded_files,
        key="gallery_upload_btn",
        type="primary",
    ):
        import tempfile
        import os
        from pixelle_video.services.phone_agent_client import push_images_auto
        from pixelle_video.config import config_manager

        push_cfg = getattr(config_manager.config, "xhs_publish", None)
        push_dir = (
            getattr(push_cfg, "push_dir", "/sdcard/DCIM/PixelleVideo")
            if push_cfg
            else "/sdcard/DCIM/PixelleVideo"
        )

        tmp_paths = []
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                for f in uploaded_files:
                    tmp_path = os.path.join(tmpdir, f.name)
                    with open(tmp_path, "wb") as fh:
                        fh.write(f.getbuffer())
                    tmp_paths.append(tmp_path)

                with st.spinner(f"正在推送 {len(tmp_paths)} 张图片到 {selected_serial}..."):
                    result = push_images_auto(
                        serial=selected_serial,
                        local_paths=tmp_paths,
                        push_dir=push_dir,
                    )

            if result["success"] > 0:
                st.success(f"✅ 成功推送 {result['success']} 张图片到相册 ({push_dir})")
            if result["failed"]:
                st.error(
                    f"❌ {len(result['failed'])} 张推送失败："
                    + ", ".join(Path(p).name for p in result["failed"])
                )
        except Exception as exc:
            st.error(f"推送出错：{exc}")


# ---- Publish Queue Tab -------------------------------------------------------

def render_publish_tab():
    """Render publish queue management UI."""
    st.subheader("📤 发布队列")

    from pixelle_video.config import config_manager as _cm
    _xhs_cfg = _cm.config.xhs_publish

    scheduler = get_publish_scheduler()
    dm = get_device_manager()
    _init_publish_form_defaults()

    # Auto-prefill post_type & delete_after_hours from <task>/post_params.json
    # whenever the form's task_id changes. This honours the TTL set on the
    # generation page so 引流帖 inherits "auto-delete after N hours" by default.
    _current_task_id = str(st.session_state.get(PUBLISH_FORM_KEYS["task_id"], "")).strip()
    if _current_task_id and st.session_state.get("_publish_prefill_task_id") != _current_task_id:
        _params_path = _project_root / "output" / _current_task_id / "post_params.json"
        _params = _safe_load_json(_params_path) if _params_path.exists() else None
        if isinstance(_params, dict):
            _pt = str(_params.get("post_type") or "content")
            if _pt in ("content", "traffic"):
                st.session_state["post_type_select"] = _pt
            try:
                _ttl = float(_params.get("traffic_ttl_hours") or 0.0)
            except (TypeError, ValueError):
                _ttl = 0.0
            if _pt == "traffic" and _ttl > 0:
                st.session_state["delete_after_hours_input"] = max(1.0, min(720.0, _ttl))
        st.session_state["_publish_prefill_task_id"] = _current_task_id

    # ── 每日定时计划配置（行内，无需跳转到设置页）──────────────
    with st.expander("📅 每日发布计划", expanded=False):
        st.caption("设置每天自动发布的时间段（24 小时制 HH:MM，每行一个）。\n选择「按计划自动安排」时，系统自动将任务分配到下一个未被占用的时间槽。")
        _times_val = "\n".join(_xhs_cfg.daily_schedule_times)
        _new_times_raw = st.text_area(
            "发布时间段",
            value=_times_val,
            height=120,
            key="inline_xhs_schedule_times",
            placeholder="09:00\n12:00\n18:00",
        )
        if st.button("💾 保存时间段", key="save_inline_schedule"):
            _parsed = [t.strip() for t in _new_times_raw.splitlines() if t.strip() and ":" in t.strip()]
            if not _parsed:
                st.error("请至少填写一个有效时间（格式 HH:MM）")
            else:
                try:
                    _cm.update({"xhs_publish": {"daily_schedule_times": _parsed}})
                    _cm.save()
                    st.success(f"✅ 已保存 {len(_parsed)} 个时间段：{', '.join(_parsed)}")
                    st.rerun()
                except Exception as _e:
                    st.error(f"保存失败：{_e}")

    # New publish job form
    with st.expander(
        "➕ 新建发布任务",
        expanded=bool(st.session_state.get("last_post_result") or st.session_state.get("publish_history_post_select")),
    ):
        suggested_serials = st.session_state.get("publish_suggested_serials", [])
        all_connected_serials = [d.serial for d in dm.get_all() if d.connected]

        with st.form("new_publish_job"):
            devices = [d for d in dm.get_all() if d.connected]
            if not devices:
                st.warning("没有已连接的设备。请先在“设备管理”中连接手机。")
                fallback_serial = st.text_input("设备 Serial（手动输入）", placeholder="192.168.1.100:5555")
                selected_serials = [fallback_serial.strip()] if fallback_serial.strip() else []
            else:
                device_options = {f"{d.name or d.serial} ({d.serial})": d.serial for d in devices}
                default_labels = [
                    label for label, serial in device_options.items() if serial in suggested_serials
                ]
                selected_labels = st.multiselect(
                    "选择目标设备（可多选）",
                    options=list(device_options.keys()),
                    default=default_labels,
                    help="支持一次创建多台手机的发布任务",
                )
                selected_serials = [device_options[label] for label in selected_labels]

            task_id = st.text_input(
                "关联任务 ID",
                key=PUBLISH_FORM_KEYS["task_id"],
                placeholder="图文生成任务 ID",
            )
            topic = st.text_input("创作主题（用于自动推荐设备）", key=PUBLISH_FORM_KEYS["topic"])
            title = st.text_input("帖子标题", key=PUBLISH_FORM_KEYS["title"])
            body = st.text_area("帖子正文", key=PUBLISH_FORM_KEYS["body"], height=150)
            hashtags_raw = st.text_input(
                "话题标签（逗号分隔，不带 #）",
                key=PUBLISH_FORM_KEYS["hashtags_raw"],
            )
            images_raw = st.text_area(
                "图片路径（每行一条）",
                key=PUBLISH_FORM_KEYS["images_raw"],
                height=100,
            )

            # Post type & TTL
            post_type_col1, post_type_col2 = st.columns([1, 2])
            with post_type_col1:
                post_type = st.selectbox(
                    "帖子类型",
                    options=["content", "traffic"],
                    format_func=lambda x: "📚 干货帖（长期保留）" if x == "content" else "📢 引流帖（可自动删除）",
                    key="post_type_select",
                )
            with post_type_col2:
                delete_after_hours: float | None = None
                if post_type == "traffic":
                    delete_after_hours = st.number_input(
                        "⏱️ 自动删除倒计时（小时）",
                        min_value=1.0,
                        max_value=720.0,
                        value=24.0,
                        step=1.0,
                        help="发布成功后，经过指定小时数自动删除帖子（0 = 不自动删除）",
                        key="delete_after_hours_input",
                    )
                    if delete_after_hours <= 0:
                        delete_after_hours = None
                else:
                    st.caption("干货帖不设自动删除")

            schedule_col1, schedule_col2 = st.columns([1, 2])
            with schedule_col1:
                schedule_mode = st.radio(
                    "发布方式",
                    options=["立即发布", "定时发布", "📅 按计划自动安排"],
                    horizontal=False,
                    key="schedule_mode_radio",
                )
            with schedule_col2:
                scheduled_dt = None
                if schedule_mode == "定时发布":
                    default_dt = datetime.now() + timedelta(hours=1)
                    scheduled_dt = st.datetime_input(
                        "发布时间",
                        value=default_dt,
                        min_value=datetime.now(),
                    )
                elif schedule_mode == "📅 按计划自动安排":
                    _preview_serial = selected_serials[0] if selected_serials else None
                    if _preview_serial:
                        _next_slot = scheduler.next_available_slot(_preview_serial)
                        if _next_slot:
                            st.info(
                                f"**{_preview_serial}** 下一个可用时间：\n\n"
                                f"🕐 {_next_slot.strftime('%m-%d %H:%M')}"
                            )
                        else:
                            st.warning("未找到可用时间段，请在「⚙️ 设置」中配置每日发布计划。")
                    else:
                        _cfg_times = _xhs_cfg.daily_schedule_times
                        if _cfg_times:
                            st.caption(f"已配置时间段：{', '.join(_cfg_times)}")
                        else:
                            st.warning("请先在「⚙️ 设置」中配置每日发布时间段。")

            action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 2])
            with action_col1:
                recommend_clicked = st.form_submit_button("🎯 按主题推荐设备")
            with action_col2:
                select_all_clicked = st.form_submit_button("✅ 全选在线设备")
            with action_col3:
                clear_selection_clicked = st.form_submit_button("🧹 清空选择")
            with action_col4:
                submit_clicked = st.form_submit_button("📤 提交并创建发布任务", type="primary")

            if select_all_clicked:
                st.session_state["publish_suggested_serials"] = all_connected_serials
                st.rerun()

            if clear_selection_clicked:
                st.session_state["publish_suggested_serials"] = []
                st.rerun()

            if recommend_clicked:
                if not topic.strip():
                    st.warning("请先填写创作主题后再推荐设备")
                else:
                    ranked = dm.suggest_devices_by_topic(topic.strip(), connected_only=True)
                    if not ranked:
                        themed_online = [d for d in devices if d.theme]
                        if not themed_online:
                            st.info("当前在线设备都未设置默认主题，请先在设备管理中填写内容主题。")
                        else:
                            st.info("没有找到匹配主题的在线设备，请手动选择设备。")
                        st.session_state["publish_suggested_serials"] = []
                    else:
                        st.session_state["publish_suggested_serials"] = [dev.serial for dev, _, _ in ranked]
                        reasons = "、".join([
                            f"{dev.name or dev.serial}({reason})"
                            for dev, _, reason in ranked[:3]
                        ])
                        st.success(f"已推荐 {len(ranked)} 台设备：{reasons}")
                    st.rerun()

            if submit_clicked:
                images = [p.strip() for p in images_raw.splitlines() if p.strip()]
                hashtags = [t.strip().lstrip("#") for t in hashtags_raw.split(",") if t.strip()]

                if not selected_serials:
                    st.error("请至少选择一台目标设备")
                elif not title.strip():
                    st.error("请填写帖子标题")
                elif not images:
                    st.error("请填写至少一张图片路径")
                elif schedule_mode == "📅 按计划自动安排" and not _xhs_cfg.daily_schedule_times:
                    st.error("请先在「⚙️ 设置」→「小红书发布配置」中添加每日发布时间段。")
                else:
                    created_jobs = []
                    failed_devices = []
                    for serial in selected_serials:
                        try:
                            # Determine scheduled_at per device
                            if schedule_mode == "📅 按计划自动安排":
                                _slot = scheduler.next_available_slot(serial)
                                _scheduled_at = _slot.isoformat() if _slot else None
                            elif schedule_mode == "定时发布":
                                _scheduled_at = scheduled_dt.isoformat() if scheduled_dt else None
                            else:
                                _scheduled_at = None  # 立即发布

                            job = scheduler.add_job(
                                serial=serial,
                                task_id=task_id or "manual",
                                title=title.strip(),
                                body=body.strip(),
                                hashtags=hashtags,
                                images=images,
                                scheduled_at=_scheduled_at,
                                post_type=post_type,
                                delete_after_hours=delete_after_hours,
                            )
                            created_jobs.append(job.job_id)
                        except Exception as e:
                            failed_devices.append(f"{serial}: {e}")

                    if created_jobs:
                        st.success(
                            f"已为 {len(created_jobs)} 台设备创建任务。\n"
                            f"Job IDs: {', '.join(created_jobs[:3])}"
                            + (" ..." if len(created_jobs) > 3 else "")
                        )
                    if failed_devices:
                        st.error("部分设备创建失败：" + " | ".join(failed_devices))
                    st.rerun()

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
    with st.expander(
        f"🛠️ 批量操作  "
        f"(待发布 {counts['pending_active']}  |  已完成 {counts['completed']}  |  失败/取消 {counts['failed']})"
    ):
        bcol1, bcol2, bcol3, bcol4 = st.columns(4)

        with bcol1:
            if st.button(
                "🚀 立即执行待发布",
                key="bulk_exec_pending",
                disabled=counts["pending_active"] == 0,
                help="对所有 pending/scheduled 任务立刻触发执行",
                use_container_width=True,
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
                use_container_width=True,
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
                use_container_width=True,
            ):
                n = scheduler.bulk_remove(["success", "done", "deleted"])
                st.success(f"已清理 {n} 个已完成任务")
                st.rerun()

        with bcol4:
            if st.button(
                "🗑️ 清理失败/取消",
                key="bulk_remove_failed",
                disabled=counts["failed"] == 0,
                use_container_width=True,
            ):
                n = scheduler.bulk_remove(["failed", "cancelled"])
                st.success(f"已清理 {n} 个失败/取消任务")
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
        ttl_tag = f"  |  ⏱️ TTL {delete_after}h" if delete_after else ""
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
                        else:
                            payload["auto_delete_at"] = "已过期（等待下次检查）"
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
                                        st.image(sc_path, caption=Path(sc_path).name, use_container_width=True)
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
                # Delete button for completed posts
                if job.status in ("done", "success") and job.status != "deleted":
                    if st.button("🗑️ 删除帖子", key=f"delete_{job.job_id}"):
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
    # ---------------------------------------------------------------------------

    st.title("📱 发布管理")
    st.caption("管理 Android 设备并将图文帖子发布到小红书")

    tab_devices, tab_publish, tab_gallery = st.tabs(["📱 设备管理", "📤 发布队列", "📸 上传到相册"])

    with tab_devices:
        render_devices_tab()

    with tab_publish:
        render_publish_tab()

    with tab_gallery:
        render_gallery_upload_tab()


if __name__ == "__main__":
    main()




