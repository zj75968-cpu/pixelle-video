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


tab_labels = ["🟢 RunningHub 渠道状态", "🧪 API 调试"]
if "devtools_active_tab_index" not in st.session_state:
    st.session_state["devtools_active_tab_index"] = 0
if st.session_state["devtools_active_tab_index"] >= len(tab_labels):
    st.session_state["devtools_active_tab_index"] = 0

# Persistent radio-based tabs (st.tabs resets to first tab on every rerun).
selected_label = st.radio(
    "Developer tools section",
    options=tab_labels,
    index=st.session_state["devtools_active_tab_index"],
    horizontal=True,
    label_visibility="collapsed",
    key="_devtools_section_radio",
)
st.session_state["devtools_active_tab_index"] = tab_labels.index(selected_label)
st.divider()

if st.session_state["devtools_active_tab_index"] == 0:
    _run_subpage(_HERE / "_runninghub.py")
else:
    _run_subpage(_HERE / "_apidebug.py")
