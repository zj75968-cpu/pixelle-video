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
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n

st.set_page_config(
    page_title="发布管理 - Pixelle-Video",
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
    "failed":    "❌ 失败",
    "cancelled": "⛔ 已取消",
}


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

                # Inline edit name / theme
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
                            st.image(data, caption="设备截图", use_container_width=True)
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


# ---- Publish Queue Tab -------------------------------------------------------

def render_publish_tab():
    """Render publish queue management UI."""
    st.subheader("📤 发布队列")

    scheduler = get_publish_scheduler()
    dm = get_device_manager()

    # New publish job form
    with st.expander("➕ 新建发布任务", expanded=bool(st.session_state.get("last_post_result"))):
        last = st.session_state.get("last_post_result", {})
        suggested_serials = st.session_state.get("publish_suggested_serials", [])
        all_connected_serials = [d.serial for d in dm.get_all() if d.connected]

        with st.form("new_publish_job"):
            devices = [d for d in dm.get_all() if d.connected]
            if not devices:
                st.warning("没有已连接的设备。请先在「设备管理」中连接手机。")
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

            task_id = st.text_input("关联任务 ID", value=last.get("task_id", ""), placeholder="图文生成任务 ID")
            topic = st.text_input("创作主题（用于自动推荐设备）", value=last.get("topic", ""))
            title = st.text_input("帖子标题", value=last.get("title", ""))
            body = st.text_area("帖子正文", value=last.get("body", ""), height=150)
            hashtags_raw = st.text_input(
                "话题标签（逗号分隔，不含#）",
                value=", ".join(last.get("hashtags", [])),
            )
            images_raw = st.text_area(
                "图片路径（每行一个）",
                value="\n".join(last.get("images", [])),
                height=100,
            )

            schedule_col1, schedule_col2 = st.columns([1, 2])
            with schedule_col1:
                use_schedule = st.checkbox("定时发布")
            with schedule_col2:
                scheduled_dt = None
                if use_schedule:
                    default_dt = datetime.now() + timedelta(hours=1)
                    scheduled_dt = st.datetime_input(
                        "发布时间",
                        value=default_dt,
                        min_value=datetime.now(),
                    )

            action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 2])
            with action_col1:
                recommend_clicked = st.form_submit_button("🎯 按主题推荐设备")
            with action_col2:
                select_all_clicked = st.form_submit_button("✅ 全选在线设备")
            with action_col3:
                clear_selection_clicked = st.form_submit_button("🧹 清空选择")
            with action_col4:
                submit_clicked = st.form_submit_button("📤 一键创建发布任务", type="primary")

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
                            st.info("当前在线设备都未设置默认主题，请先在设备管理中填写“内容主题”")
                        else:
                            st.info("没有找到匹配主题的在线设备，请手动选择设备")
                        st.session_state["publish_suggested_serials"] = []
                    else:
                        st.session_state["publish_suggested_serials"] = [dev.serial for dev, _, _ in ranked]
                        reasons = "；".join([
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
                else:
                    created_jobs = []
                    failed_devices = []
                    for serial in selected_serials:
                        try:
                            job = scheduler.add_job(
                                serial=serial,
                                task_id=task_id or "manual",
                                title=title.strip(),
                                body=body.strip(),
                                hashtags=hashtags,
                                images=images,
                                scheduled_at=scheduled_dt.isoformat() if scheduled_dt else None,
                            )
                            created_jobs.append(job.job_id)
                        except Exception as e:
                            failed_devices.append(f"{serial}: {e}")

                    if created_jobs:
                        st.success(
                            f"已为 {len(created_jobs)} 台设备创建任务。"
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
        options=["全部", "pending", "scheduled", "running", "success", "failed", "cancelled"],
        index=0,
    )
    filter_val = None if status_filter == "全部" else status_filter

    if st.button("🔄 刷新队列"):
        st.rerun()

    _render_publish_queue_list(filter_val)


@st.fragment(run_every="6s")
def _render_publish_queue_list(filter_val: str | None):
    scheduler = get_publish_scheduler()
    jobs = scheduler.list_jobs(status_filter=filter_val)
    st.caption("发布队列每 6 秒自动刷新一次")

    if not jobs:
        st.info("队列为空")
        return

    for job in jobs:
        badge = STATUS_BADGE.get(job.status, job.status)
        label = f"{badge}  |  {job.title[:30]}  →  {job.serial}  |  {job.created_at[:16]}"
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
                    "device": job.serial,
                    "task_id": job.task_id,
                    "status": job.status,
                    "scheduled_at": job.scheduled_at,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "error": job.error,
                    "images": job.images,
                }
                if elapsed is not None:
                    payload["running_seconds"] = elapsed
                st.json(payload)

                if elapsed is not None and elapsed > 600:
                    st.warning(f"任务已运行 {elapsed // 60} 分钟，请观察设备是否仍在操作")

            with col2:
                if job.status in ("pending", "scheduled"):
                    if st.button("▶️ 立即执行", key=f"run_{job.job_id}"):
                        import asyncio
                        asyncio.run(scheduler.execute_now(job.job_id))
                        st.rerun()
                if job.status in ("pending", "scheduled", "running"):
                    if st.button("⛔ 取消", key=f"cancel_{job.job_id}"):
                        scheduler.cancel_job(job.job_id)
                        st.rerun()


# ---- Main --------------------------------------------------------------------

def main():
    init_session_state()
    init_i18n()

    st.title("📱 发布管理")
    st.caption("管理 Android 设备并将图文帖子发布到小红书")

    tab_devices, tab_publish = st.tabs(["📱 设备管理", "📤 发布队列"])

    with tab_devices:
        render_devices_tab()

    with tab_publish:
        render_publish_tab()


if __name__ == "__main__":
    main()
