# Copyright (C) 2025 AIDC-AI
"""
LLM-driven polishing helpers for content_input widgets.

Provides:
- polish_text(raw, kind): one-shot async LLM call returning polished string.
- render_polish_button(label, source_key, target_key, kind): renders a
  small Streamlit button that, when clicked, polishes the current value
  of `st.session_state[source_key]` and writes it back to `target_key`
  (defaulting to the same key) before triggering a rerun.

Falls back gracefully when LLM is not configured (button stays visible
but shows a friendly error toast).
"""

from __future__ import annotations

import asyncio
from typing import Literal

import streamlit as st
from loguru import logger
from pydantic import BaseModel, Field


PolishKind = Literal["title", "body", "topic"]


class _PolishResult(BaseModel):
    polished: str = Field(description="润色后的文本，仅包含正文/标题字符串本身")
    rationale: str = Field(description="一句话说明改动思路", default="")


def _build_prompt(raw: str, kind: PolishKind) -> str:
    if kind == "title":
        return (
            "你是小红书 / 短视频文案润色助手。请把下面的【标题】润色得更具吸引力、更易传播，"
            "保留原意，控制在 20 个汉字以内，不要使用露骨夸张词，不要加引号。\n\n"
            f"原标题：{raw}"
        )
    if kind == "topic":
        return (
            "你是创作助手。请把下面的【视频选题/创作主题】润色得更具体、可拍摄、避免空泛，"
            "保留原意，控制在 80 个汉字以内，不要使用 emoji，不要加引号。\n\n"
            f"原主题：{raw}"
        )
    # default: body
    return (
        "你是小红书 / 短视频文案润色助手。请把下面的【正文/文案】润色得更生动、有节奏感、"
        "保留原意，避免堆砌空话；如果原文是长段落可以适度分段，但不要超过原长度的 1.4 倍。\n\n"
        f"原文：{raw}"
    )


async def _polish_async(raw: str, kind: PolishKind) -> _PolishResult:
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()
    if core.llm is None:
        raise RuntimeError("LLM 未配置")

    prompt = _build_prompt(raw, kind)
    return await core.llm(
        prompt=prompt,
        response_type=_PolishResult,
        temperature=0.4,
        max_tokens=600,
    )


def polish_text(raw: str, kind: PolishKind) -> _PolishResult:
    """Sync wrapper used inside Streamlit callbacks."""
    return asyncio.run(_polish_async(raw, kind))


def render_polish_button(
    *,
    source_key: str,
    kind: PolishKind,
    target_key: str | None = None,
    label: str = "✨ 润色",
    help_text: str = "用 LLM 一键润色当前输入",
    button_key: str | None = None,
) -> None:
    """Render an inline LLM-polish button bound to a Streamlit widget key.

    Usage:
        text = st.text_area("正文", key="post_body")
        render_polish_button(source_key="post_body", kind="body")

    On click:
      1. Reads current value via st.session_state[source_key]
      2. Calls LLM
      3. Writes result to st.session_state[target_key or source_key]
      4. Triggers st.rerun()
    """
    target_key = target_key or source_key
    btn_key = button_key or f"polish_btn_{source_key}_{kind}"

    def _on_click() -> None:
        raw = (st.session_state.get(source_key) or "").strip()
        if not raw:
            st.session_state[f"_polish_msg_{btn_key}"] = ("warning", "先输入一些内容再润色。")
            return
        try:
            res = polish_text(raw, kind)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"polish failed: {exc}")
            st.session_state[f"_polish_msg_{btn_key}"] = ("error", f"润色失败：{exc}")
            return
        polished = (res.polished or "").strip()
        if not polished:
            st.session_state[f"_polish_msg_{btn_key}"] = ("warning", "LLM 返回为空，保留原文。")
            return
        # Safe to assign here: on_click runs before widgets are re-instantiated this run.
        st.session_state[target_key] = polished
        if res.rationale:
            st.session_state[f"_polish_msg_{btn_key}"] = ("toast", f"已润色：{res.rationale}")

    st.button(label, help=help_text, key=btn_key, type="secondary", on_click=_on_click)

    _msg = st.session_state.pop(f"_polish_msg_{btn_key}", None)
    if _msg:
        kind_, text_ = _msg
        if kind_ == "warning":
            st.warning(text_)
        elif kind_ == "error":
            st.error(text_)
        elif kind_ == "toast":
            st.toast(text_, icon="✨")
