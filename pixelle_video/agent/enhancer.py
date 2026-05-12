"""提示词增强器：把用户口语化短指令扩写成 Agent 友好的完整任务描述。

设计要点：
- 不凭空捏造关键事实（如具体话题、设备 serial、计划发布时间）；缺什么如实在 clarifications 列出
  让用户/Agent 知道是补全猜测。
- 输出仍是中文自然语言，再交给 brain.plan() 去拆工具调用。
- 用同一个 LLMService（DeepSeek），pydantic 结构化输出。
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field


class EnhancedInstruction(BaseModel):
    """LLM-produced rewrite of user's raw instruction."""

    inferred_intent: str = Field(description="一句话概括用户的核心意图")
    enhanced_instruction: str = Field(
        description=(
            "改写/扩写后的完整指令（中文自然语言）。要素尽量齐全："
            "主题/镜头数量/标题/标签/目标设备/计划发布时间/是否真实发布等。"
            "缺失信息保持模糊或显式标注「未指定」，不要编造具体数字。"
        )
    )
    clarifications: List[str] = Field(
        default_factory=list,
        description="为补全所做的关键假设（每条一句中文，便于用户复核）",
    )


ENHANCER_SYSTEM_PROMPT = """你是 Pixelle-Video Agent 的「指令润色助手」。\
你的输入是用户的一句口语化短指令（可能很简单，甚至只是关键词），\
你的输出是一份扩写后的指令，要让下游 Agent 大脑能更容易地拆解成工具调用。

可用工具领域（仅供你了解上下文，不要在输出里直接列工具）：
- 列出/登记安卓设备
- 列出可用图像/视频生成 workflow
- 用主题文字生成视频（generate_video）
- 把视频加入小红书发布队列（enqueue_publish），可指定 scheduled_at
- 列出 / 取消发布任务
- 列出 / 删除历史生成任务

改写原则：
1. **不要编造**用户没说的具体事实：例如用户没指定标题，就不要凭空起一个标题，
   而是在 clarifications 里写「未指定标题，建议由系统默认或留空」。
2. 用户原话里**已有的关键词**（主题、风格、数字）必须**原样保留**。
3. 如果指令含糊（如「做一下」），先猜出最可能的意图（如「生成视频」），\
   然后在 enhanced_instruction 末尾加一句「如理解有误请重新下达」。
4. 用户提到「不要真的发布」「测试」「演练」等词时，建议把 scheduled_at 设到很远的未来\
   （例如 2099-01-01T00:00:00），并在 clarifications 里说明。
5. enhanced_instruction 用流畅中文写成一段话或带短点的小段，不要 JSON、不要列工具名。
6. inferred_intent 一句话总结即可，不超过 40 个汉字。
7. clarifications 每条聚焦一个补全假设，不超过 6 条；没必要补全就给空列表。

用户原始指令：
\"\"\"{raw}\"\"\"
"""


async def enhance_instruction(raw: str, llm=None) -> EnhancedInstruction:
    """Rewrite a raw user instruction into a richer Agent-friendly form."""
    raw_stripped = (raw or "").strip()
    if not raw_stripped:
        return EnhancedInstruction(
            inferred_intent="",
            enhanced_instruction="",
            clarifications=["原指令为空，未进行增强"],
        )

    if llm is None:
        from pixelle_video.service import pixelle_video as core
        if not getattr(core, "_initialized", False):
            await core.initialize()
        llm = core.llm

    prompt = ENHANCER_SYSTEM_PROMPT.format(raw=raw_stripped.replace('"', '\\"'))
    logger.info(f"[agent.enhancer] enhancing: {raw_stripped!r}")
    result: EnhancedInstruction = await llm(
        prompt=prompt,
        response_type=EnhancedInstruction,
        temperature=0.3,
        max_tokens=600,
    )
    logger.info(
        f"[agent.enhancer] -> intent={result.inferred_intent!r}; "
        f"+{len(result.clarifications)} clarification(s)"
    )
    return result


__all__ = ["EnhancedInstruction", "enhance_instruction"]
