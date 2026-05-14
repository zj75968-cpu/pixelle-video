# Copyright (C) 2025 AIDC-AI
"""Agent 大脑：使用者一句话指令，自动编排现有工具完成任务。"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from web.state.session import init_session_state, init_i18n, get_pixelle_video
from web.utils.async_helpers import run_async

from pixelle_video.agent import AgentBrain, TOOLS, enhance_instruction
from pixelle_video.agent.brain import _resolve_placeholders
from pixelle_video.agent.tools import get_tool as _get_tool

st.set_page_config(page_title="Agent 大脑", page_icon="🤖", layout="wide")
init_session_state()
init_i18n()

st.title("🤖 Agent 大脑")
st.caption("用一句话下命令，它自动调用「视频生成 / 设备查询 / 发布入队」等工具完成。")

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

# ── 发布方式单选 ─────────────────────────────────────────────────────────────
publish_kind = st.radio(
    "📤 发布方式（涉及发布时生效）",
    options=["🤖 自动决定", "🎬 视频笔记（纯视频）", "🖼️ 图文笔记（图文点评/图文视频）"],
    horizontal=True,
    index=0,
    key="agent_publish_kind",
    help="视频笔记上传 .mp4；图文笔记自动取每个场景的合成图片上传",
)
_KIND_HINT = {
    "🎬 视频笔记（纯视频）":          "【发布方式：视频笔记，kind=video】",
    "🖼️ 图文笔记（图文点评/图文视频）": "【发布方式：图文笔记，kind=image_text】",
}

instruction = st.text_area(
    "你想做什么？",
    value=default_text,
    height=100,
    placeholder="例：围绕『睡前十分钟整理法』生成 3 段视频并加入小红书发布队列",
    key="agent_raw_instruction",
)

# 三个动作按钮：优化提示词（增强后展示并允许编辑） / 直接执行 / 清空历史
col_enhance, col_run, col_clear = st.columns([1.2, 1, 1])
enhance_clicked = col_enhance.button(
    "✨ 优化提示词", use_container_width=True,
    help="让 LLM 把模糊指令扩写成完整任务描述。优化后可编辑，再点「执行」才会跑。",
)
run_direct_clicked = col_run.button(
    "🚀 直接执行", type="primary", use_container_width=True,
    help="跳过提示词优化，直接把当前指令交给 Agent 编排。",
)
if col_clear.button("🧹 清空历史", use_container_width=True):
    st.session_state.agent_history = []
    st.session_state.pop("agent_enhanced_text", None)
    st.session_state.pop("agent_enhanced_meta", None)
    st.session_state.pop("agent_enhanced_source", None)
    st.rerun()


def _result_to_dict(result) -> dict:
    """Pydantic AgentRunResult -> JSON-safe dict (handles non-serializable result blobs)."""
    try:
        return json.loads(result.model_dump_json())
    except Exception:
        return result.model_dump()


# ---- 第一步：增强（如果用户点了「优化提示词」） ----------------------------
if enhance_clicked:
    raw = (instruction or "").strip()
    if not raw:
        st.warning("请先输入指令再优化。")
    else:
        with st.spinner("✨ 提示词优化中..."):
            try:
                enhanced = run_async(
                    enhance_instruction(raw, llm=pixelle_video.llm)
                )
            except Exception as e:  # noqa: BLE001
                st.error(f"提示词优化失败：{type(e).__name__}: {e}")
                enhanced = None
        if enhanced and enhanced.enhanced_instruction.strip():
            st.session_state["agent_enhanced_text"] = enhanced.enhanced_instruction.strip()
            st.session_state["agent_enhanced_meta"] = {
                "inferred_intent": enhanced.inferred_intent,
                "clarifications": list(enhanced.clarifications),
            }
            st.session_state["agent_enhanced_source"] = raw
            st.rerun()
        else:
            st.warning("LLM 没有返回有效的优化结果，请检查输入或重试。")


# ---- 优化结果显示与编辑区（持久于 session_state） --------------------------
enhanced_text_pending: Optional[str] = None
if "agent_enhanced_text" in st.session_state:
    meta = st.session_state.get("agent_enhanced_meta") or {}
    src = st.session_state.get("agent_enhanced_source", "")
    with st.container(border=True):
        st.markdown("### ✨ 优化后的提示词（可编辑）")
        if src:
            st.caption(f"📥 原始指令：{src}")
        if meta.get("inferred_intent"):
            st.caption(f"🎯 推断意图：{meta['inferred_intent']}")
        if meta.get("clarifications"):
            with st.popover("LLM 做出的假设"):
                for c in meta["clarifications"]:
                    st.markdown(f"- {c}")
        edited = st.text_area(
            "优化后的提示词",
            value=st.session_state["agent_enhanced_text"],
            height=160,
            key="agent_enhanced_editor",
            label_visibility="collapsed",
        )
        c1, c2 = st.columns([1, 1])
        confirm_clicked = c1.button(
            "🚀 用此提示词执行", type="primary", use_container_width=True,
            key="agent_confirm_enhanced",
        )
        discard_clicked = c2.button(
            "❌ 放弃优化", use_container_width=True, key="agent_discard_enhanced",
        )
        if discard_clicked:
            st.session_state.pop("agent_enhanced_text", None)
            st.session_state.pop("agent_enhanced_meta", None)
            st.session_state.pop("agent_enhanced_source", None)
            st.rerun()
        if confirm_clicked:
            enhanced_text_pending = (edited or "").strip()
            # 同步更新 session 里的最新版本
            st.session_state["agent_enhanced_text"] = enhanced_text_pending


# ---- 工具中文名映射 -------------------------------------------------------
_TOOL_LABELS: dict = {
    "list_devices":     "查询连接设备",
    "set_device_info":  "更新设备信息",
    "list_workflows":   "列出工作流",
    "generate_video":   "生成视频",
    "enqueue_publish":  "加入发布队列",
    "list_jobs":        "查看发布队列",
    "cancel_job":       "取消发布任务",
    "list_tasks":       "查看视频任务",
    "delete_task":      "删除任务",
    "cleanup_outputs":  "清理输出目录",
    "recommend_models": "推荐工作流",
    "recommend_device": "推荐发布设备",
}


# ---- 第二步：执行 ----------------------------------------------------------
def _run_brain(final_text: str, raw_text: str, enhanced_meta: Optional[dict]) -> None:
    """Plan + execute via AgentBrain with live step-by-step progress."""
    import time as _time

    brain = AgentBrain(llm=pixelle_video.llm)

    with st.status("🧠 Agent 执行中…", expanded=True) as _status:
        # ── Phase 1: Planning ────────────────────────────────────────────────
        st.write("📋 正在分析指令，生成执行计划…")
        try:
            plan = run_async(brain.plan(final_text))
        except Exception as e:  # noqa: BLE001
            _status.update(label="❌ 规划失败", state="error", expanded=True)
            st.error(f"规划失败：{type(e).__name__}: {e}")
            return

        step_count = len(plan.steps)
        st.write(f"✅ **规划完成**：{plan.summary}（共 {step_count} 步）")
        if plan.notes:
            st.caption(f"💡 {plan.notes}")

        # ── Phase 2: Execution ───────────────────────────────────────────────
        executions: list = []
        prior_results: list = []

        if step_count == 0:
            _status.update(label=f"✅ {plan.summary}", state="complete", expanded=False)
        else:
            prog = st.progress(0, text="准备执行…")
            for i, step in enumerate(plan.steps):
                label = _TOOL_LABELS.get(step.tool, step.tool)
                prog.progress(i / step_count, text=f"步骤 {i + 1}/{step_count}：{label}…")
                st.write(f"⏳ **步骤 {i + 1}**：{label} — {step.reason or ''}")

                tool = _get_tool(step.tool)
                t0 = _time.time()

                if tool is None:
                    err = f"未知工具：{step.tool!r}"
                    executions.append({"index": i, "tool": step.tool, "args": step.args,
                                       "ok": False, "result": None, "error": err, "elapsed_ms": 0})
                    st.error(f"❌ {err}")
                    prog.progress(i / step_count, text=f"❌ 步骤 {i + 1} 失败")
                    break

                try:
                    resolved = _resolve_placeholders(step.args, prior_results)
                    result = run_async(tool.handler(**resolved))
                    elapsed = int((_time.time() - t0) * 1000)
                    prior_results.append(result)
                    executions.append({"index": i, "tool": step.tool, "args": resolved,
                                       "ok": True, "result": result, "error": None,
                                       "elapsed_ms": elapsed})
                    st.write(f"\u3000\u3000✅ 完成（{elapsed} ms）")
                except Exception as exc:  # noqa: BLE001
                    elapsed = int((_time.time() - t0) * 1000)
                    err_msg = f"{type(exc).__name__}: {exc}"
                    executions.append({"index": i, "tool": step.tool, "args": step.args,
                                       "ok": False, "result": None, "error": err_msg,
                                       "elapsed_ms": elapsed})
                    st.error(f"❌ 步骤 {i + 1} 失败：{err_msg}")
                    prog.progress(i / step_count, text=f"❌ 步骤 {i + 1} 失败")
                    break

            all_ok = bool(executions) and all(e.get("ok") for e in executions)
            prog.progress(1.0, text="✅ 全部完成" if all_ok else "⚠️ 执行中止")
            _status.update(
                label=f"{'✅ 完成' if all_ok else '❌ 部分失败'}：{plan.summary}",
                state="complete" if all_ok else "error",
                expanded=not all_ok,
            )

    # ── Save to history ──────────────────────────────────────────────────────
    try:
        plan_dict = json.loads(plan.model_dump_json())
    except Exception:  # noqa: BLE001
        plan_dict = plan.model_dump()

    all_ok_outer = bool(executions) and all(e.get("ok") for e in executions)
    run_dict = {
        "instruction": final_text,
        "plan": plan_dict,
        "executions": executions,
        "ok": all_ok_outer,
        "error": None if all_ok_outer else (executions[-1].get("error") if executions else "无步骤执行"),
        "raw_instruction": raw_text,
    }
    if enhanced_meta is not None:
        run_dict["enhanced"] = {
            "inferred_intent": enhanced_meta.get("inferred_intent", ""),
            "enhanced_instruction": final_text,
            "clarifications": list(enhanced_meta.get("clarifications", [])),
        }
    st.session_state.agent_history.insert(0, run_dict)
    # 执行完毕清空增强缓存，方便下一轮
    st.session_state.pop("agent_enhanced_text", None)
    st.session_state.pop("agent_enhanced_meta", None)
    st.session_state.pop("agent_enhanced_source", None)


if run_direct_clicked:
    raw = (instruction or "").strip()
    if not raw:
        st.warning("请先输入指令")
    else:
        hint = _KIND_HINT.get(publish_kind, "")
        final = f"{hint}\n{raw}" if hint else raw
        _run_brain(final_text=final, raw_text=raw, enhanced_meta=None)

if enhanced_text_pending:
    raw = st.session_state.get("agent_enhanced_source") or enhanced_text_pending
    meta = st.session_state.get("agent_enhanced_meta") or {}
    hint = _KIND_HINT.get(publish_kind, "")
    final_with_hint = f"{hint}\n{enhanced_text_pending}" if hint else enhanced_text_pending
    _run_brain(final_text=final_with_hint, raw_text=raw, enhanced_meta=meta)

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
