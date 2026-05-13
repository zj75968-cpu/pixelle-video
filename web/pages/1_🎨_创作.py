# Copyright (C) 2025 AIDC-AI
"""创作 - 视频生成 / 图文创作（合并自原 Home + Post 页）。

使用 `st.tabs` 把两个原页面的脚本通过 `runpy.run_path` 加载到各自的 tab 容器中。
为了规避「st.set_page_config 只能在脚本顶部调用一次」的限制，在执行子页面前
临时把 `st.set_page_config` 替换为 no-op，结束后恢复。
"""

from __future__ import annotations

import sys
import runpy
from pathlib import Path

_HERE = Path(__file__).resolve().parent          # web/pages
_PROJECT_ROOT = _HERE.parent.parent              # Pixelle-Video
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from web.state.session import init_session_state, init_i18n

st.set_page_config(page_title="创作", page_icon="🎨", layout="wide")
init_session_state()
init_i18n()

# 顶部统一渲染一次系统设置（避免两个 tab 各自渲染导致 widget key 冲突）。
from web.components import settings as _settings_module
_settings_module.render_advanced_settings()
# 子页内部调用的 render_advanced_settings 全部替换为 no-op，保证只渲染一次。
_settings_module.render_advanced_settings = lambda *a, **k: None  # type: ignore[assignment]


def _run_subpage(path: Path) -> None:
    """Execute a legacy page script inside the current Streamlit container."""
    _orig = st.set_page_config
    st.set_page_config = lambda *a, **k: None  # type: ignore[assignment]
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        st.set_page_config = _orig  # type: ignore[assignment]


tab_video, tab_post = st.tabs(["🎬 视频生成", "📝 图文创作"])

with tab_video:
    _run_subpage(_HERE / "_home.py")

with tab_post:
    _run_subpage(_HERE / "_post.py")
