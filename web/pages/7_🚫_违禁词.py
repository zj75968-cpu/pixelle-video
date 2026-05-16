"""
小红书违禁词管理页

- 上传 txt / csv / json 文件批量导入关键词
- 手动追加 / 删除关键词
- 选择遮罩模式（用 *** 替换）或直接删除
- 提供文本预览测试

存储位置：data/banned_keywords.json
所有入队发布任务（add_job）会在保存前自动用该列表清洗 title / body / hashtags。
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pixelle_video.utils import banned_keywords as bk

st.set_page_config(page_title="违禁词 - AI Video Generator", page_icon="🚫", layout="wide")

st.title("🚫 小红书违禁词")
st.caption("发布前自动过滤标题 / 正文 / 标签里出现的关键词。所有任务入队时即生效。")

state = bk.get_state()

col1, col2 = st.columns([1, 1])

# ── 上传 ──────────────────────────────────────────────────────────
with col1:
    st.subheader("📤 上传关键词")
    st.write(
        "支持 `.txt` / `.csv`（一行一个，或用空格/逗号/中文逗号/分号/顿号/竖线分隔）"
        "和 `.json`（数组或 `{\"keywords\": [...]}`）。"
    )
    upload = st.file_uploader(
        "选择文件",
        type=["txt", "csv", "json"],
        accept_multiple_files=False,
        key="bk_upload",
    )
    merge_mode = st.radio(
        "导入方式",
        options=["追加到现有列表", "整体替换现有列表"],
        index=0,
        horizontal=True,
        key="bk_merge_mode",
    )
    if upload is not None:
        try:
            raw = upload.read()
            parsed = bk.parse_upload(raw, upload.name)
        except Exception as exc:
            st.error(f"解析失败：{exc}")
        else:
            st.info(f"解析到 {len(parsed)} 个关键词。点击下方按钮确认导入。")
            with st.expander("预览（最多 50 个）", expanded=False):
                st.write("、".join(parsed[:50]) or "（空）")
            if st.button("✅ 确认导入", key="bk_confirm_import", type="primary"):
                if merge_mode.startswith("整体替换"):
                    new_list = bk.replace_all(parsed)
                else:
                    new_list = bk.add_keywords(parsed)
                st.success(f"已保存，共 {len(new_list)} 个关键词。")
                st.rerun()

# ── 手动管理 ──────────────────────────────────────────────────────
with col2:
    st.subheader("✍️ 手动添加")
    new_word = st.text_input(
        "输入关键词（同一行支持空格/逗号分隔，可一次添加多个）",
        key="bk_new_word",
    )
    cols = st.columns(3)
    if cols[0].button("➕ 添加", key="bk_add_btn"):
        if not new_word.strip():
            st.warning("请输入关键词")
        else:
            words = bk.parse_upload(new_word, "inline.txt")
            new_list = bk.add_keywords(words)
            st.success(f"已添加，共 {len(new_list)} 个关键词。")
            st.rerun()
    if cols[1].button("🗑️ 清空全部", key="bk_clear_btn"):
        bk.clear_all()
        st.warning("已清空。")
        st.rerun()
    if cols[2].button("🔄 重新加载", key="bk_reload_btn"):
        bk.reload()
        st.info("已重新从磁盘加载。")
        st.rerun()

    st.markdown("---")
    st.subheader("⚙️ 过滤策略")
    mode_label = {"mask": "遮罩 (替换为 ***)", "remove": "直接删除"}
    current_mode = state["mode"]
    new_mode_label = st.radio(
        "命中后的处理方式",
        options=list(mode_label.values()),
        index=0 if current_mode == "mask" else 1,
        horizontal=True,
        key="bk_mode_radio",
    )
    new_mode = "mask" if new_mode_label.startswith("遮罩") else "remove"
    new_mask = st.text_input("遮罩符号", value=state["mask"], key="bk_mask_input")
    if st.button("保存策略", key="bk_save_mode"):
        bk.set_mode(new_mode, mask=new_mask)
        st.success("已保存。")
        st.rerun()

st.markdown("---")

# ── 当前列表 ──────────────────────────────────────────────────────
st.subheader(f"📋 当前关键词（{len(state['keywords'])}）")
if state.get("updated_at"):
    st.caption(f"最后更新：{state['updated_at']}")

if not state["keywords"]:
    st.info("暂无关键词。可在上方上传或手动添加。")
else:
    # 5 列展示 + 每个右上角删除按钮
    n_cols = 5
    rows = (len(state["keywords"]) + n_cols - 1) // n_cols
    idx = 0
    for _ in range(rows):
        cols = st.columns(n_cols)
        for c in cols:
            if idx >= len(state["keywords"]):
                break
            word = state["keywords"][idx]
            with c.container(border=True):
                col_a, col_b = st.columns([3, 1])
                col_a.markdown(f"`{word}`")
                if col_b.button("✕", key=f"bk_rm_{idx}_{word}"):
                    bk.remove_keyword(word)
                    st.rerun()
            idx += 1

st.markdown("---")

# ── 预览测试 ──────────────────────────────────────────────────────
st.subheader("🔍 试一段文本看看效果")
sample = st.text_area(
    "粘贴标题 + 正文（也可包含 #话题），点击下方按钮查看清洗结果",
    height=160,
    key="bk_preview_input",
)
if st.button("运行过滤", key="bk_preview_run"):
    cleaned, hits = bk.filter_text(sample)
    if hits:
        st.warning(f"命中 {len(hits)} 处：{'、'.join(sorted(set(hits)))}")
    else:
        st.success("没有命中。")
    st.code(cleaned or "（空）", language="markdown")
