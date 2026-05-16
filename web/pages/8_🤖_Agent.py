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
from pixelle_video.services.publish_scheduler import PublishScheduler as _PublishScheduler


def get_publish_scheduler() -> _PublishScheduler:
    if "publish_scheduler" not in st.session_state:
        st.session_state["publish_scheduler"] = _PublishScheduler()
    return st.session_state["publish_scheduler"]

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

# ── 图文帖定位单选（仅对 generate_image_text_post 生效）─────────────────────
post_type_choice = st.radio(
    "🎯 图文帖定位（仅图文笔记/图文帖生效）",
    options=["🤖 自动决定", "📚 干货帖（content）", "📢 引流帖（traffic）"],
    horizontal=True,
    index=0,
    key="agent_post_type",
    help=(
        "干货帖：结构化分点、提供真实价值、不带强引导话术；"
        "引流帖：制造钩子 + 必带 CTA（评论/私信/关注）。"
        "选「自动」由 Agent 根据指令措辞自行判断。"
    ),
)
_POST_TYPE_HINT = {
    "📚 干货帖（content）": "【图文帖定位：干货帖，post_type=content】",
    "📢 引流帖（traffic）": "【图文帖定位：引流帖，post_type=traffic】",
}


def _compose_hint() -> str:
    parts = [
        _KIND_HINT.get(publish_kind, ""),
        _POST_TYPE_HINT.get(post_type_choice, ""),
    ]
    return "\n".join(p for p in parts if p)

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

                # ── 拦截：enqueue_publish 且 device_serial 因 picks 为空而为 None ──
                if step.tool == "enqueue_publish":
                    try:
                        _peek = _resolve_placeholders(dict(step.args), prior_results)
                    except Exception:
                        _peek = dict(step.args)
                    _no_serial = _peek.get("device_serial") is None
                    _empty_picks = any(
                        isinstance(r, dict) and r.get("picks") == []
                        for r in prior_results
                    )
                    if _no_serial and _empty_picks:
                        st.session_state["_pending_enqueue"] = _peek
                        st.warning("⚠️ 没有已连接设备，请在下方手动选择设备后入队")
                        prog.progress(i / step_count, text="⚠️ 等待人工选择设备…")
                        _status.update(
                            label=f"⚠️ {plan.summary}（等待选择设备）",
                            state="error", expanded=True,
                        )
                        break

                # Delegate to brain so retry+LLM-repair is exercised here too.
                exec_record = run_async(
                    brain._run_step_with_repair(
                        index=i,
                        step=step,
                        prior_results=prior_results,
                    )
                )
                row = {
                    "index": exec_record.index,
                    "tool": exec_record.tool,
                    "args": exec_record.args,
                    "ok": exec_record.ok,
                    "result": exec_record.result,
                    "error": exec_record.error,
                    "elapsed_ms": exec_record.elapsed_ms,
                    "attempts": exec_record.attempts,
                    "repair_notes": exec_record.repair_notes,
                }
                executions.append(row)

                if exec_record.ok:
                    suffix = (
                        f"（{exec_record.elapsed_ms} ms，重试 {exec_record.attempts - 1} 次"
                        f"，修复：{exec_record.repair_notes}）"
                        if exec_record.attempts > 1 and exec_record.repair_notes
                        else f"（{exec_record.elapsed_ms} ms）"
                    )
                    prior_results.append(exec_record.result)
                    st.write(f"\u3000\u3000✅ 完成{suffix}")
                else:
                    st.error(
                        f"❌ 步骤 {i + 1} 失败（尝试 {exec_record.attempts} 次）："
                        f"{exec_record.error}"
                    )
                    if exec_record.repair_notes:
                        st.caption(f"🛠️ 修复尝试记录：{exec_record.repair_notes}")
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
        hint = _compose_hint()
        final = f"{hint}\n{raw}" if hint else raw
        _run_brain(final_text=final, raw_text=raw, enhanced_meta=None)

if enhanced_text_pending:
    raw = st.session_state.get("agent_enhanced_source") or enhanced_text_pending
    meta = st.session_state.get("agent_enhanced_meta") or {}
    hint = _compose_hint()
    final_with_hint = f"{hint}\n{enhanced_text_pending}" if hint else enhanced_text_pending
    _run_brain(final_text=final_with_hint, raw_text=raw, enhanced_meta=meta)
# ---- 人工选择发布设备（当 recommend_device 返回空 picks 时） -----------------
_pending_eq = st.session_state.get("_pending_enqueue")
if _pending_eq:
    st.warning("⚠️ 没有已连接设备，视频/帖子已生成——请手动选择设备后入队。")
    with st.container(border=True):
        st.subheader("📱 手动选择发布设备")
        try:
            from pixelle_video.services.device_manager import device_manager as _dm
            _all_devs = _dm.get_all()
        except Exception:
            _all_devs = []
        if not _all_devs:
            st.error("没有已注册的设备，请先在「发布管理」→「设备管理」页面注册设备。")
        else:
            _dev_options = {
                f"{'🟢' if getattr(d, 'connected', False) else '🔴'} {getattr(d, 'name', '') or d.serial} ({d.serial})": d.serial
                for d in _all_devs
            }
            _chosen_label = st.selectbox(
                "选择发布设备（🔴=当前未连接，发布前请先连接）",
                options=list(_dev_options.keys()),
                key="pending_eq_device",
            )
            _chosen_serial = _dev_options[_chosen_label]

            _c1, _c2 = st.columns(2)
            with _c1:
                _p_title = st.text_input("标题", value=_pending_eq.get("title", ""), key="pending_eq_title")
                _p_body = st.text_area("正文", value=_pending_eq.get("body", ""), height=120, key="pending_eq_body")
            with _c2:
                _p_tags_raw = st.text_input(
                    "话题标签（逗号分隔）",
                    value=",".join(_pending_eq.get("hashtags") or []),
                    key="pending_eq_tags",
                )
            _cb1, _cb2 = st.columns([1, 3])
            with _cb1:
                if st.button("📥 确认入队", type="primary", key="pending_eq_submit"):
                    from pixelle_video.services.publish_scheduler import publish_scheduler as _ps
                    _tags_list = [t.strip() for t in _p_tags_raw.split(",") if t.strip()]
                    _job = _ps.add_job(
                        serial=_chosen_serial,
                        task_id=_pending_eq.get("task_id") or "agent-manual",
                        title=_p_title,
                        body=_p_body,
                        hashtags=_tags_list,
                        images=_pending_eq.get("images") or [],
                        video_path=_pending_eq.get("video_path"),
                        kind=_pending_eq.get("kind", "video"),
                        post_type=_pending_eq.get("post_type", "content"),
                        delete_after_hours=_pending_eq.get("delete_after_hours"),
                    )
                    del st.session_state["_pending_enqueue"]
                    st.success(f"✅ 已入队：{_job.job_id[:8]}…  →  设备 {_chosen_serial}")
                    st.rerun()
            with _cb2:
                if st.button("🚫 放弃入队", key="pending_eq_discard"):
                    del st.session_state["_pending_enqueue"]
                    st.rerun()
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
                        # ── 若是 enqueue_publish，提供快速取消按钮 ────────────
                        if step.get("tool") == "enqueue_publish":
                            _jid = (ex.get("result") or {}).get("job_id")
                            if _jid:
                                _btn_key = f"cancel_job_{idx}_{i}_{_jid[:8]}"
                                if st.button(
                                    "🚫 取消此发布任务",
                                    key=_btn_key,
                                    help=f"job_id: {_jid}",
                                ):
                                    _sched = get_publish_scheduler()
                                    _ok = _sched.cancel_job(_jid)
                                    if _ok:
                                        st.success(f"已取消 {_jid[:8]}…")
                                    else:
                                        st.warning(f"任务 {_jid[:8]}… 已是终态，无需取消")
                                    st.rerun()
                    elif ex:
                        st.error(ex.get("error") or "失败")
                    else:
                        st.write("（未执行）")

            if not ok and run.get("error"):
                st.error(run["error"])
