"""基于 LLM 的 RunningHub 低价模型推荐器。

输入：用户提示词 + 任务类型 (text-to-image / text-to-video / image-to-video / image-to-image / start-end-to-video)
输出：按"贴合度 + 性价比 + 稳定性"排序的 Top-N 模型推荐及理由。
"""

from __future__ import annotations

from typing import List, Optional, Literal

from pydantic import BaseModel, Field

TaskKind = Literal[
    "text-to-image",
    "image-to-image",
    "text-to-video",
    "image-to-video",
    "start-end-to-video",
    "video-tools",
]


class Recommendation(BaseModel):
    """LLM 给出的单条模型推荐。"""

    workflow_key: str = Field(description="必须从候选清单的 workflow_key 中精确选取一项")
    score: int = Field(ge=0, le=100, description="0-100 的贴合度评分")
    reason: str = Field(description="一句话说明为什么推荐它（基于亮点/特性匹配）")
    suggested_params: dict = Field(
        default_factory=dict,
        description="建议的可选参数（如 aspectRatio/resolution/duration 等，必须来自该模型 inputs.options.value）",
    )


class RecommendationList(BaseModel):
    """LLM 结构化输出 schema。"""

    picks: List[Recommendation] = Field(description="按贴合度从高到低排序，1~5 条")
    notes: Optional[str] = Field(default=None, description="对用户的总体建议或风险提示")


def _candidates_for(task_kind: TaskKind):
    """根据任务类型筛 registry 候选。"""
    from pixelle_video.services import runninghub_registry as reg

    return [m for m in reg.list_models() if (m.get("category") or "") == task_kind]


def _format_candidate(m: dict) -> str:
    inputs_brief = []
    for i in m.get("inputs", []) or []:
        t = i.get("type")
        k = i["fieldKey"]
        if t == "LIST":
            opts = [o.get("value") for o in (i.get("options") or [])]
            inputs_brief.append(f"{k}(LIST: {opts})")
        elif t in ("STRING", "INT", "BOOLEAN", "IMAGE", "VIDEO"):
            inputs_brief.append(f"{k}({t})")
    return (
        f"- workflow_key: {m['workflow_key']}\n"
        f"  name: {m['name']}\n"
        f"  highlights: {m.get('modelHighlights', '')}\n"
        f"  description: {(m.get('description') or '')[:300]}\n"
        f"  inputs: {'; '.join(inputs_brief)}"
    )


async def recommend(
    llm,
    user_prompt: str,
    task_kind: TaskKind,
    top_n: int = 3,
) -> RecommendationList:
    """调用 LLM 给出 top_n 条模型推荐。

    Args:
        llm: pixelle_video.llm 实例（LLMService）
        user_prompt: 用户的生成提示词 / 需求描述
        task_kind:  任务类型
        top_n: 期望返回的推荐条数（LLM 会自行裁剪）

    Returns:
        ``RecommendationList`` 对象。若 LLM 未配置或调用失败将抛异常。
    """
    candidates = _candidates_for(task_kind)
    if not candidates:
        return RecommendationList(picks=[], notes=f"registry 中没有任何 {task_kind} 类别的模型。")

    candidate_block = "\n".join(_format_candidate(m) for m in candidates)
    sys_prompt = (
        "你是一名 AIGC 模型选型顾问。下面会给你一份 RunningHub 低价渠道模型清单和用户的生成需求。\n"
        "请综合以下因素排序，选出最适合的 Top-N 模型：\n"
        "1) 模型 highlights / description 与用户需求的语义贴合度\n"
        "2) 输入字段是否能覆盖用户描述里的关键约束（如比例、时长、首尾帧等）\n"
        "3) 标记『已下架』的模型应避免推荐\n"
        "4) 同质模型优先选 fast 版本（性价比）\n"
        "对每个推荐给出 1 句话理由，并从该模型 inputs 的 LIST 选项里挑出 1~3 个合理的默认参数。"
    )

    full_prompt = (
        f"{sys_prompt}\n\n"
        f"==== 任务类型 ====\n{task_kind}\n\n"
        f"==== 用户提示词 ====\n{user_prompt}\n\n"
        f"==== 候选模型清单 ====\n{candidate_block}\n\n"
        f"请返回最多 {top_n} 条推荐（picks 数组按贴合度倒序），workflow_key 必须严格来自上方清单。"
    )

    result: RecommendationList = await llm(
        prompt=full_prompt,
        response_type=RecommendationList,
        temperature=0.3,
        max_tokens=1500,
    )
    # 校验 workflow_key 在候选里
    valid_keys = {m["workflow_key"] for m in candidates}
    result.picks = [p for p in result.picks if p.workflow_key in valid_keys][:top_n]
    return result
