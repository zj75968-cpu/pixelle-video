# Copyright (C) 2025 AIDC-AI
"""RunningHub 低价模型 LLM 推荐面板。

用户输入提示词 + 任务类型，由 LLM 从已加载的 18 个低价模型里挑出最适合的 Top-N，并解释为什么。
"""

import asyncio
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video

st.set_page_config(page_title="低价模型推荐", page_icon="🧠", layout="wide")
init_session_state()
init_i18n()

st.title("🧠 RunningHub 低价模型 · 智能推荐")
st.caption(
    "把你的生成需求和任务类型告诉 LLM，它会从 registry 里挑出最贴合的低价渠道模型，"
    "并给出参数建议。"
)

pixelle_video = get_pixelle_video()

col_input, col_meta = st.columns([3, 1])

with col_meta:
    task_kind = st.selectbox(
        "任务类型",
        options=[
            "text-to-image",
            "image-to-image",
            "text-to-video",
            "image-to-video",
            "start-end-to-video",
            "video-tools",
        ],
        index=2,
    )
    top_n = st.slider("Top-N", min_value=1, max_value=5, value=3)

with col_input:
    user_prompt = st.text_area(
        "生成需求（自然语言描述）",
        value="生成一段 8 秒的横屏电影感视频：黄昏时分，一个少女在山顶弹吉他，远处群山被夕阳染红，需要带音效，画面要稳定且唇形同步。",
        height=140,
    )

run = st.button("🚀 让 LLM 推荐", type="primary", width="stretch")


async def _do_recommend():
    from pixelle_video.services.runninghub_recommender import recommend

    return await recommend(
        llm=pixelle_video.llm,
        user_prompt=user_prompt,
        task_kind=task_kind,
        top_n=top_n,
    )


if run:
    if not user_prompt.strip():
        st.error("请输入生成需求。")
        st.stop()

    with st.spinner("LLM 正在分析候选模型..."):
        try:
            try:
                rec = asyncio.run(_do_recommend())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    rec = loop.run_until_complete(_do_recommend())
                finally:
                    loop.close()
        except Exception as e:
            st.error(f"调用 LLM 失败：{e}\n\n请检查 config.yaml 里的 llm.api_key / base_url / model 是否已配置。")
            st.stop()

    if not rec.picks:
        st.warning("LLM 没有给出任何推荐，可能 registry 中没有该任务类型的候选。")
    else:
        st.success(f"得到 {len(rec.picks)} 条推荐：")
        if rec.notes:
            st.info(rec.notes)
        for i, p in enumerate(rec.picks, 1):
            with st.container(border=True):
                cscore, cname = st.columns([1, 4])
                with cscore:
                    st.metric(f"#{i}", f"{p.score}/100")
                with cname:
                    st.markdown(f"**`{p.workflow_key}`**")
                    st.markdown(f"💡 {p.reason}")
                    if p.suggested_params:
                        st.json(p.suggested_params, expanded=False)
