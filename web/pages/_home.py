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
Home Page - Main video generation interface
"""

import sys
from pathlib import Path

# Add project root to sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

# Import state management
from web.state.session import init_session_state, init_i18n, get_pixelle_video

# Import components
from web.components.header import render_header

# Page config
st.set_page_config(
    page_title="Home - AI Video Generator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main():
    """Main UI entry point"""
    # Initialize session state and i18n
    init_session_state()
    init_i18n()
    
    # Render header (title + language selector)
    render_header()
    
    # Initialize Pixelle-Video
    pixelle_video = get_pixelle_video()
    
    # ========================================================================
    # Pipeline Selection & Delegation
    # ========================================================================
    from web.pipelines import get_all_pipeline_uis
    
    # Get all registered pipelines
    pipelines = get_all_pipeline_uis()

    # NOTE: We intentionally do NOT use st.tabs() here because Streamlit's
    # built-in tabs lose their selected state on every rerun (any radio /
    # button click would snap the user back to the first pipeline tab, e.g.
    # 数字人 → 切换"带货/自定义"瞬间被弹回快速创作)。
    # Instead, use st.radio backed by session_state for a persistent
    # tab-like selector.
    tab_labels = [f"{p.icon} {p.display_name}" for p in pipelines]
    if "active_pipeline_index" not in st.session_state:
        st.session_state["active_pipeline_index"] = 0
    # Clamp in case pipeline registry changed between reruns.
    if st.session_state["active_pipeline_index"] >= len(pipelines):
        st.session_state["active_pipeline_index"] = 0

    selected_label = st.radio(
        "Pipeline",
        options=tab_labels,
        index=st.session_state["active_pipeline_index"],
        horizontal=True,
        label_visibility="collapsed",
        key="_home_pipeline_radio",
    )
    st.session_state["active_pipeline_index"] = tab_labels.index(selected_label)
    st.divider()

    active_pipeline = pipelines[st.session_state["active_pipeline_index"]]
    if active_pipeline.description:
        st.caption(active_pipeline.description)
    active_pipeline.render(pixelle_video)


if __name__ == "__main__":
    main()

