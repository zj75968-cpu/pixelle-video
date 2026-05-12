# Copyright (C) 2025 AIDC-AI
"""Agent 大脑：使用者一句话指令，自动编排现有工具完成任务。"""

import asyncio
import json
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.utils.async_helpers import run_async

from pixelle_video.agent import AgentBrain, TOOLS, enhance_instruction

st.set_page_config(page_title="Agent 大脑", page_icon="🤖", layout="wide")
init_session_state()
init_i18n()

st.title("🤖 Agent 大脑")
st.caption("用一句话下命令，它自动调用「视频生成 / 设备查询 / 发布入队」等工具完成。")

# ---- 工具盘点 -------------------------------------------------------------
with st.expander("🧰 可用工具清单", expanded=False):
    for t in TOOLS:
        st.markdown(f"**`{t.name}`** — {t.description}")
        st.code(json.dumps(t.args_schema, ensure_ascii=False, indent=2), language="json")

# ---- 初始化 ---------------------------------------------------------------
pixelle_video = get_pixelle_video()
if "agent_history" not in st.session_state:
    st.session_state.agent_history = []  # list[AgentRunResult dict]

# ---- 输入区 ---------------------------------------------------------------
default_examples = [
    "查看一下当前连接的安卓设备",
    "围绕「桃胶如何食用」生成一个3段的视频",
    "围绕「一分钟快速减压」生成视频，然后用「轻舒缓减压」为标题加入小红书发布队列",
]
example = st.selectbox("示例指令", ["（自定义）"] + default_examples, index=0)
default_text = "" if example == "（自定义）" else example
instruction = st.text_area(
    "你想做什么？",
    value=default_text,
    height=100,
    placeholder="例：围绕『睡前十分钟整理法』生成 3 段视频并加入小红书发布队列",
)

col_run, col_clear = st.columns([1, 1])
run_clicked = col_run.button("🚀 开始", type="primary", use_container_width=True)
if col_clear.button("🧹 清空历史", use_container_width=True):
    st.session_state.agent_history = []
    st.rerun()

enhance_toggle = st.toggle(
    "✨ AI 提示词增强（先由 LLM 把你的短句扩写成完整任务描述，再交给 Agent）",
    value=True,
    help="开启后会多花一次 LLM 调用，但能显著提升对模糊/口语化指令的理解。",
)


def _result_to_dict(result) -> dict:
    """Pydantic AgentRunResult -> JSON-safe dict (handles non-serializable result blobs)."""
    try:
        return json.loads(result.model_dump_json())
    except Exception:
        return result.model_dump()


# ---- 执行 -----------------------------------------------------------------
if run_clicked:
    if not instruction.strip():
        st.warning("请先输入指令")
    else:
        brain = AgentBrain(llm=pixelle_video.llm)
        raw_instruction = instruction.strip()
        final_instruction = raw_instruction
        enhanced_payload = None

        if enhance_toggle:
            with st.spinner("✨ 提示词增强中..."):
                try:
                    enhanced = run_async(
                        enhance_instruction(raw_instruction, llm=pixelle_video.llm)
                    )
                except Exception as e:  # noqa: BLE001
                    st.warning(f"提示词增强失败，已回退到原始指令：{type(e).__name__}: {e}")
                    enhanced = None
            if enhanced and enhanced.enhanced_instruction.strip():
                final_instruction = enhanced.enhanced_instruction.strip()
                enhanced_payload = {
                    "inferred_intent": enhanced.inferred_intent,
                    "enhanced_instruction": enhanced.enhanced_instruction,
                    "clarifications": list(enhanced.clarifications),
                }
                with st.expander("✨ 增强后的指令", expanded=True):
                    st.markdown(f"**意图**：{enhanced.inferred_intent}")
                    st.markdown("**改写后**：")
                    st.info(enhanced.enhanced_instruction)
                    if enhanced.clarifications:
                        st.markdown("**LLM 做出的假设**：")
                        for c in enhanced.clarifications:
                            st.markdown(f"- {c}")

        with st.spinner("🧠 规划与执行中..."):
            try:
                result = run_async(brain.run(final_instruction))
            except Exception as e:  # noqa: BLE001
                st.error(f"运行失败: {type(e).__name__}: {e}")
                st.stop()
        run_dict = _result_to_dict(result)
        run_dict["raw_instruction"] = raw_instruction
        if enhanced_payload is not None:
            run_dict["enhanced"] = enhanced_payload
        st.session_state.agent_history.insert(0, run_dict)

# ---- 历史 -----------------------------------------------------------------
st.divider()
st.subheader("📜 执行历史")

if not st.session_state.agent_history:
    st.info("暂无记录。")
else:
    for idx, run in enumerate(st.session_state.agent_history):
        ok = run.get("ok", False)
        icon = "✅" if ok else "❌"
        instr = run.get("instruction", "")
        with st.expander(f"{icon} {instr}", expanded=(idx == 0)):
            raw_instruction = run.get("raw_instruction")
            enhanced_meta = run.get("enhanced")
            if enhanced_meta and raw_instruction and raw_instruction != instr:
                st.caption(f"📥 原始指令：{raw_instruction}")
                st.caption(f"🎯 意图：{enhanced_meta.get('inferred_intent', '')}")
                if enhanced_meta.get("clarifications"):
                    with st.popover("LLM 做出的假设"):
                        for c in enhanced_meta["clarifications"]:
                            st.markdown(f"- {c}")
            plan = run.get("plan", {})
            st.markdown(f"**理解**：{plan.get('summary', '')}")
            if plan.get("notes"):
                st.caption(f"💡 {plan['notes']}")

            steps = plan.get("steps", [])
            executions = run.get("executions", [])
            if not steps:
                st.info("LLM 判断无需调用工具。")
            for i, step in enumerate(steps):
                ex = executions[i] if i < len(executions) else None
                ex_icon = "✅" if (ex and ex.get("ok")) else ("❌" if ex else "⏸")
                st.markdown(
                    f"{ex_icon} **Step {i}: `{step.get('tool')}`** — "
                    f"{step.get('reason', '')}"
                )
                cols = st.columns(2)
                with cols[0]:
                    st.caption("入参")
                    st.code(
                        json.dumps(
                            (ex or {}).get("args", step.get("args", {})),
                            ensure_ascii=False, indent=2,
                        ),
                        language="json",
                    )
                with cols[1]:
                    st.caption("结果")
                    if ex and ex.get("ok"):
                        st.code(
                            json.dumps(ex.get("result"), ensure_ascii=False, indent=2, default=str),
                            language="json",
                        )
                        st.caption(f"耗时 {ex.get('elapsed_ms', 0)} ms")
                    elif ex:
                        st.error(ex.get("error") or "失败")
                    else:
                        st.write("（未执行）")

            if not ok and run.get("error"):
                st.error(run["error"])
