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
    </style>
    """,
    unsafe_allow_html=True,
)


def main():
    """Main entry point with navigation"""
    # Define pages using st.Page
    create_page = st.Page(
        "pages/1_🎨_创作.py",
        title="创作",
        icon="🎨",
        default=True,
    )

    history_page = st.Page(
        "pages/2_📚_History.py",
        title="History",
        icon="📚",
    )

    publish_page = st.Page(
        "pages/4_📱_Publish.py",
        title="发布管理",
        icon="📱",
    )

    agent_page = st.Page(
        "pages/8_🤖_Agent.py",
        title="Agent 大脑",
        icon="🤖",
    )

    settings_page = st.Page(
        "pages/9_⚙️_Settings.py",
        title="设置",
        icon="⚙️",
    )

    pg = st.navigation([
        create_page,
        history_page,
        publish_page,
        agent_page,
        settings_page,
    ], position="top")
    pg.run()


if __name__ == "__main__":
    main()
