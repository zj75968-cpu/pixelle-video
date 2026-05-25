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

# ── 🔍 挂机系统诊断 (Agent Diagnostic Panel) ──
with st.expander("🔍 调试：发布管理模块加载诊断", expanded=True):
    try:
        views_dir = Path(__file__).resolve().parent
        publish_file = views_dir / "4_Publish.py"
        st.write(f"• `4_Publish.py` 物理文件存在: `{publish_file.exists()}` (大小: {publish_file.stat().st_size if publish_file.exists() else 0} 字节)")
        
        import runpy
        # 临时做 mock 防止 set_page_config 报 API 错
        _orig = st.set_page_config
        st.set_page_config = lambda *a, **k: None
        try:
            runpy.run_path(str(publish_file))
            st.success("✅ 4_Publish.py 在 Streamlit 运行时上下文加载成功！")
        except Exception as e:
            st.error(f"❌ 4_Publish.py 顶层代码执行失败: {e}")
            import traceback
            st.code(traceback.format_exc(), language="python")
        finally:
            st.set_page_config = _orig
    except Exception as ex:
        st.write(f"诊断面板自身运行出错: {ex}")



def _run_subpage(path: Path) -> None:
    """Execute a legacy page script inside the current Streamlit container.

    The child scripts also call ``st.set_page_config`` — we no-op it during
    the sub-run because page config has already been set by this parent.
    """
    _orig = st.set_page_config
    st.set_page_config = lambda *a, **k: None  # type: ignore[assignment]
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        st.set_page_config = _orig  # type: ignore[assignment]


tab_labels = ["🎬 视频生成", "📝 图文创作"]
if "create_active_tab_index" not in st.session_state:
    st.session_state["create_active_tab_index"] = 0
if st.session_state["create_active_tab_index"] >= len(tab_labels):
    st.session_state["create_active_tab_index"] = 0

# NOTE: We avoid st.tabs() here because Streamlit's built-in tabs reset to
# the first tab on every rerun (any inner widget change would bounce the
# user back to "视频生成"). Use a horizontal radio backed by session_state
# for a persistent tab-like selector.
selected_label = st.radio(
    "Create section",
    options=tab_labels,
    index=st.session_state["create_active_tab_index"],
    horizontal=True,
    label_visibility="collapsed",
    key="_create_section_radio",
)
st.session_state["create_active_tab_index"] = tab_labels.index(selected_label)
st.divider()

if st.session_state["create_active_tab_index"] == 0:
    _run_subpage(_HERE / "_home.py")
else:
    _run_subpage(_HERE / "_post.py")
