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
Pixelle-Video Web UI - Main Entry Point

This is the entry point for the Streamlit multi-page application.
Uses st.navigation to define pages and set the default page to Home.
"""

import sys
import time
from pathlib import Path

# Add project root to sys.path for module imports
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

# Setup page config (must be first Streamlit command)
st.set_page_config(
    page_title="AI Video Generator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Background TTL watcher: scans successful traffic posts for expired
# delete_after_hours and auto-deletes them via uiautomator2. Started once
# per Streamlit process (FastAPI starts its own APScheduler-based one).
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _start_ttl_watcher_once():
    try:
        from pixelle_video.services.publish_scheduler import publish_scheduler
        started = publish_scheduler.start_ttl_watcher(interval_minutes=15.0)
        return {"started": bool(started)}
    except Exception:  # noqa: BLE001
        # Never block the UI on watcher startup failure.
        return {"started": False}


_start_ttl_watcher_once()

# Streamlit may still cap main content width (e.g. 736px) after reruns.
# Force the main block container to use full available width.
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        display: none !important;
    }
    [data-testid="stMain"] {
        width: 100% !important;
        flex: 1 1 100% !important;
    }
    [data-testid="stMainBlockContainer"] {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    /* 设置页导航入口隐藏，管理员通过 /settings?k=密鑰 访问 */
    a[href*="settings"] {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_login_page():
    # 注入 CSS 给登录页面添加绝美的现代暗色磨砂玻璃微光渐变背景
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at 50% 50%, #1a1a2e 0%, #0f0f1a 100%) !important;
            color: #ffffff !important;
        }
        div.stButton > button {
            background: linear-gradient(135deg, #ff4b4b 0%, #ff7676 100%) !important;
            color: white !important;
            border-radius: 8px !important;
            border: none !important;
            padding: 8px 24px !important;
            font-weight: bold !important;
            box-shadow: 0 4px 15px rgba(255, 75, 75, 0.4) !important;
            transition: all 0.3s ease !important;
        }
        div.stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px rgba(255, 75, 75, 0.6) !important;
        }
        .login-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 30px;
            margin-top: 50px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    st.write("<h1 style='text-align: center; color: #ff4b4b; font-weight: 800; font-size: 2.8rem;'>Pixelle Xiaohongshu</h1>", unsafe_allow_html=True)
    st.write("<p style='text-align: center; color: #888899; margin-bottom: 40px;'>云端多用户智能创作与自动发帖平台</p>", unsafe_allow_html=True)

    _, col_card, _ = st.columns([1, 1.5, 1])
    
    with col_card:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        tab_login, tab_register = st.tabs(["🔑 登录账户", "📝 注册新账号"])
        
        with tab_login:
            login_username = st.text_input("用户名", key="login_username_input", placeholder="输入英文字母、数字或下划线")
            login_password = st.text_input("密码", type="password", key="login_password_input", placeholder="您的账户密码")
            
            if st.button("登录平台", key="login_btn_submit", use_container_width=True):
                from web.utils.auth import auth_service
                if auth_service.authenticate(login_username, login_password):
                    st.session_state.authenticated = True
                    st.session_state.username = login_username.strip().lower()
                    st.success("🎉 登录成功，正在加载工作区...")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误，请重试")
                    
        with tab_register:
            reg_username = st.text_input("设定用户名", key="reg_username_input", placeholder="3-15位字母、数字或下划线")
            reg_password = st.text_input("设定密码", type="password", key="reg_password_input", placeholder="至少 6 位密码")
            reg_password_confirm = st.text_input("确认密码", type="password", key="reg_password_confirm_input", placeholder="重复上面的密码")
            
            if st.button("创建新账号", key="register_btn_submit", use_container_width=True):
                if reg_password != reg_password_confirm:
                    st.error("❌ 两次输入密码不一致")
                else:
                    from web.utils.auth import auth_service
                    success, msg = auth_service.register(reg_username, reg_password)
                    if success:
                        st.success(f"🎉 注册成功！请切换至登录页登录")
                    else:
                        st.error(f"❌ {msg}")
        st.markdown('</div>', unsafe_allow_html=True)


def main():
    """Main entry point with navigation"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = None

    if not st.session_state.authenticated:
        render_login_page()
        return

    # Render User Info and Logout on Top Right
    col_space, col_user = st.columns([8.5, 1.5])
    with col_user:
        st.markdown(
            f"<div style='text-align: right; margin-top: 10px; color: #888899; font-size: 14px; font-weight: bold;'>"
            f"👤 {st.session_state.username}"
            f"</div>",
            unsafe_allow_html=True
        )
        if st.button("退出登录", key="app_logout_btn", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.rerun()

    # Define pages using st.Page
    create_page = st.Page(
        "pages/1_Create.py",
        title="创作",
        icon="🎨",
        default=True,
    )

    history_page = st.Page(
        "pages/2_History.py",
        title="History",
        icon="📚",
    )

    publish_page = st.Page(
        "pages/4_Publish.py",
        title="发布管理",
        icon="📱",
    )

    agent_page = st.Page(
        "pages/8_Agent.py",
        title="Agent 大脑",
        icon="🤖",
    )

    scraper_page = st.Page(
        "pages/9_Scraper.py",
        title="搬运",
        icon="🔄",
    )

    banned_page = st.Page(
        "pages/7_Banned.py",
        title="违禁词",
        icon="🚫",
    )

    settings_page = st.Page(
        "pages/9_Settings.py",
        title="设置",
        icon="⚙️",
        url_path="settings",
    )

    pg = st.navigation(
        [create_page, history_page, publish_page, agent_page, scraper_page, banned_page, settings_page],
        position="top",
    )
    pg.run()


if __name__ == "__main__":
    main()
