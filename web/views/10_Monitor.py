# Copyright (C) 2025 AIDC-AI
"""
群控集中监控墙：多设备局域网 HTTP 实时画面监视与状态中心
"""

import os
import json
import sys
import time
import socket
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n
from pixelle_video.services.device_manager import device_manager, DeviceInfo
from pixelle_video.services.publish_scheduler import publish_scheduler, JobStatus

# Ensure session states are initialized
init_session_state()
init_i18n()

MONITOR_CONFIG_FILE = _project_root / "data" / "devices_monitor.json"

def load_monitor_config() -> dict:
    """从磁盘加载监视配置 (如设备的投屏IP网址)"""
    if MONITOR_CONFIG_FILE.exists():
        try:
            with open(MONITOR_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_monitor_config(config: dict):
    """保存监视配置到磁盘"""
    try:
        MONITOR_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MONITOR_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# Initialize session state for monitor configuration
if "monitor_config" not in st.session_state:
    st.session_state.monitor_config = load_monitor_config()

# Display styling customization (modern dark grid, premium neon highlights)
st.markdown(
    """
    <style>
    .device-card {
        background: rgba(30, 30, 45, 0.6) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        padding: 16px !important;
        margin-bottom: 20px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2) !important;
        backdrop-filter: blur(10px) !important;
    }
    .status-badge {
        padding: 4px 10px !important;
        border-radius: 20px !important;
        font-size: 12px !important;
        font-weight: bold !important;
    }
    .status-online {
        background: rgba(46, 204, 113, 0.15) !important;
        color: #2ecc71 !important;
        border: 1px solid rgba(46, 204, 113, 0.3) !important;
    }
    .status-offline {
        background: rgba(231, 76, 60, 0.15) !important;
        color: #e74c3c !important;
        border: 1px solid rgba(231, 76, 60, 0.3) !important;
    }
    .log-box {
        font-family: monospace !important;
        font-size: 11px !important;
        background: #0d0d16 !important;
        color: #a5a5c5 !important;
        padding: 8px !important;
        border-radius: 6px !important;
        height: 120px !important;
        overflow-y: auto !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📺 集中群控大屏")
st.caption("实时监控局域网内所有物理发帖机画面，监视自动化工作流日志，实现零连线集中控制。")

# Auto-get PC local IP
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80))
    pc_ip = s.getsockname()[0]
except Exception:
    pc_ip = '127.0.0.1'
finally:
    s.close()

# Main actions row
col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
with col_ctrl1:
    view_mode = st.radio(
        "🖥️ 画面显示模式",
        options=["🖼️ 极速投屏流 (MJPEG)", "🌐 交互控制页 (Iframe)", "🚫 隐藏投屏窗口 (仅看日志)"],
        horizontal=True,
        index=0,
        key="monitor_view_mode"
    )
with col_ctrl2:
    st.write("") # Spacer
    if st.button("🔄 刷新全部状态", use_container_width=True):
        st.rerun()
with col_ctrl3:
    st.write("") # Spacer
    st.caption(f"💻 本机局域网IP: `{pc_ip}`")

# Fetch registered devices
devices = [d for d in device_manager.get_all() if d.serial != "phone_agent"] # Filter out deprecated virtual phone_agent

if not devices:
    st.info("💡 当前系统中暂无注册的物理发帖设备，请在「设置」或「发布管理」页面添加 COM 串口设备。")
else:
    # Render layout columns depending on count of devices
    num_cols = min(3, len(devices))
    cols = st.columns(num_cols)
    
    for idx, dev in enumerate(devices):
        col = cols[idx % num_cols]
        serial = dev.serial
        dev_name = dev.name or f"设备 {serial}"
        
        # Load persisted screen stream URL
        default_url = st.session_state.monitor_config.get(serial, f"http://192.168.1.100:8080")
        
        # Get active jobs for this device
        all_jobs = publish_scheduler.list_jobs()
        dev_jobs = [j for j in all_jobs if j.serial == serial]
        active_job = next((j for j in dev_jobs if j.status in (JobStatus.RUNNING, JobStatus.PENDING)), None)
        last_job = dev_jobs[0] if dev_jobs else None
        
        with col:
            st.markdown(f'<div class="device-card">', unsafe_allow_html=True)
            
            # Header
            header_col1, header_col2 = st.columns([3, 1])
            with header_col1:
                st.markdown(f"#### 📱 {dev_name}")
                st.caption(f"串口: `{serial}`")
            with header_col2:
                # Online/Offline badge
                if dev.connected:
                    st.markdown('<span class="status-badge status-online">在线</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="status-badge status-offline">离线</span>', unsafe_allow_html=True)
            
            # Realtime video / screen streaming
            if view_mode == "🖼️ 极速投屏流 (MJPEG)":
                stream_src = f"{default_url}/stream.mjpeg"
                st.markdown(
                    f"""
                    <div style="width:100%; aspect-ratio:9/16; background:#000; border-radius:8px; display:flex; align-items:center; justify-content:center; overflow:hidden; border: 1px solid rgba(255,255,255,0.1);">
                        <img src="{stream_src}" style="width:100%; height:100%; object-fit:contain;" 
                             onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
                        <div style="display:none; flex-direction:column; align-items:center; justify-content:center; color:#555; text-align:center; padding: 20px;">
                            <span style="font-size:3rem; margin-bottom:10px;">📴</span>
                            <span style="font-size:12px;">未检测到投屏流<br>请确保手机已启动 Screen Stream App 广播</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            elif view_mode == "🌐 交互控制页 (Iframe)":
                st.markdown(
                    f"""
                    <iframe src="{default_url}" style="width:100%; aspect-ratio:9/16; border:none; background:#000; border-radius:8px; border: 1px solid rgba(255,255,255,0.1);"></iframe>
                    """,
                    unsafe_allow_html=True
                )
                
            st.write("")
            
            # Config URL for screen streaming
            new_url = st.text_input(
                f"投屏广播网址 ({serial})", 
                value=default_url,
                placeholder="http://192.168.1.X:8080",
                key=f"url_input_{serial}"
            )
            if new_url != default_url:
                st.session_state.monitor_config[serial] = new_url
                save_monitor_config(st.session_state.monitor_config)
                st.toast(f"💾 {dev_name} 投屏配置已更新！")
                time.sleep(0.5)
                st.rerun()
                
            # Current Status & Progress Logs
            st.markdown("---")
            if active_job:
                status_color = "#3498db" if active_job.status == JobStatus.RUNNING else "#f1c40f"
                st.markdown(f"**当前任务状态**: <span style='color:{status_color}; font-weight:bold;'>{active_job.status.upper()}</span>", unsafe_allow_html=True)
                st.markdown(f"任务ID: `{active_job.job_id[:8]}...` (类型: `{active_job.kind}`)")
                
                # Logs
                st.caption("📋 实时执行日志:")
                logs_text = "\n".join(active_job.progress_log) if active_job.progress_log else "等待日志输出..."
                st.markdown(f'<pre class="log-box">{logs_text}</pre>', unsafe_allow_html=True)
                
                # Stop button
                if st.button("🚫 取消此任务", key=f"cancel_{active_job.job_id}"):
                    if publish_scheduler.cancel_job(active_job.job_id):
                        st.toast("✅ 任务取消成功")
                        st.rerun()
            elif last_job:
                status_color = "#2ecc71" if last_job.status == JobStatus.SUCCESS else "#e74c3c"
                st.markdown(f"**上次任务状态**: <span style='color:{status_color}; font-weight:bold;'>{last_job.status.upper()}</span>", unsafe_allow_html=True)
                st.markdown(f"任务ID: `{last_job.job_id[:8]}...` (完成时间: `{last_job.finished_at[:16] if last_job.finished_at else '未知'}`)")
                
                # Logs
                st.caption("📋 历史执行日志:")
                logs_text = "\n".join(last_job.progress_log) if last_job.progress_log else "无日志记录"
                st.markdown(f'<pre class="log-box">{logs_text}</pre>', unsafe_allow_html=True)
            else:
                st.info("💤 该设备当前空闲，暂无执行记录。")
                
            # Trigger Manual Test button
            with st.expander("🛠️ 调试测试"):
                test_title = st.text_input("测试标题", value="物理发布调试测试", key=f"title_{serial}")
                test_body = st.text_area("测试正文", value="这是一次纯物理发帖测试，通过局域网投屏进行调试。\n#CH9329 #自动化", key=f"body_{serial}")
                
                test_col1, test_col2 = st.columns(2)
                with test_col1:
                    test_kind = st.selectbox("发布类型", ["image_text", "video"], key=f"kind_{serial}")
                with test_col2:
                    st.write("") # Alignment spacer
                    st.write("")
                    trigger_test = st.button("🚀 发起单步测试", key=f"btn_test_{serial}", use_container_width=True)
                    
                if trigger_test:
                    # Provide dummy test image/video based on selection
                    dummy_img_dir = _project_root / "runtime" / "test_images"
                    dummy_img_dir.mkdir(parents=True, exist_ok=True)
                    dummy_img_path = dummy_img_dir / "test_monitor_monitor.jpg"
                    
                    if not dummy_img_path.exists():
                        # Create a simple colored placeholder image using PIL
                        try:
                            from PIL import Image, ImageDraw
                            img = Image.new("RGB", (800, 1200), color=(255, 36, 66))
                            draw = ImageDraw.Draw(img)
                            draw.text((200, 500), "Pixelle CH9329 Test", fill="white")
                            img.save(dummy_img_path)
                        except Exception as p_err:
                            st.error(f"无法生成测试图片: {p_err}")
                    
                    if test_kind == "video":
                        # Look for a sample video in output
                        sample_video = None
                        output_dir = _project_root / "output"
                        if output_dir.exists():
                            for f in output_dir.glob("**/*.mp4"):
                                sample_video = str(f)
                                break
                        if not sample_video:
                            st.warning("⚠️ 目录下未找到任何可用测试 .mp4 视频，请先生成一个视频再测视频发布，或者选择发布图文笔记！")
                        else:
                            job = publish_scheduler.add_job(
                                serial=serial,
                                task_id="test-manual-video",
                                title=test_title,
                                body=test_body,
                                hashtags=["CH9329", "监控测试"],
                                images=[],
                                video_path=sample_video,
                                kind="video",
                                dry_run=True # Dry run simulation
                            )
                            st.success(f"📥 测试视频任务 {job.job_id[:8]} 已加入队列并开始执行！")
                            time.sleep(1.0)
                            st.rerun()
                    else:
                        job = publish_scheduler.add_job(
                            serial=serial,
                            task_id="test-manual-img",
                            title=test_title,
                            body=test_body,
                            hashtags=["CH9329", "监控测试"],
                            images=[str(dummy_img_path)],
                            kind="image_text",
                            dry_run=True
                        )
                        st.success(f"📥 测试图文任务 {job.job_id[:8]} 已加入队列并开始执行！")
                        time.sleep(1.0)
                        st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
