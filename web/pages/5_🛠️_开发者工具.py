# Copyright (C) 2025 AIDC-AI
"""开发者工具 - RunningHub 渠道状态 / API 调试（合并自原 RunningHub + APIDebug 页）。"""

from __future__ import annotations

import sys
import runpy
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from web.state.session import init_session_state, init_i18n

st.set_page_config(page_title="开发者工具", page_icon="🛠️", layout="wide")
init_session_state()
init_i18n()


def _run_subpage(path: Path) -> None:
    _orig = st.set_page_config
    st.set_page_config = lambda *a, **k: None  # type: ignore[assignment]
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        st.set_page_config = _orig  # type: ignore[assignment]


tab_rh, tab_api = st.tabs(["🟢 RunningHub 渠道状态", "🧪 API 调试"])

with tab_rh:
    _run_subpage(_HERE / "_runninghub.py")

with tab_api:
    _run_subpage(_HERE / "_apidebug.py")
