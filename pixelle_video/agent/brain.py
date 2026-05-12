"""Agent Brain：把使用者一句话指令转成一串工具调用并执行。

工作流：
1. 把用户指令 + 工具清单（JSON Schema）塞进 prompt
2. 调用现有 LLMService，要求结构化输出 AgentPlan(pydantic)
3. 顺序执行 plan.steps，把每一步的结果存入 transcript
4. 任一步失败：记录错误并中止
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from pixelle_video.agent.tools import TOOLS, get_tool, tools_manifest


# -----------------------------------------------------------------------------
# Pydantic schemas for structured LLM output
# -----------------------------------------------------------------------------

class AgentStep(BaseModel):
    """One step in the plan."""

    tool: str = Field(description="要调用的工具名，必须是工具清单里的 name 之一")
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="工具入参（JSON 对象）。允许使用 ${steps[i].result.<field>} 引用上一步结果。",
    )
    reason: str = Field(default="", description="为什么要这一步")


class AgentPlan(BaseModel):
    """LLM-produced plan."""

    summary: str = Field(description="对用户意图的一句话理解")
    steps: List[AgentStep] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, description="风险/前置依赖提示")


class StepExecution(BaseModel):
    index: int
    tool: str
    args: Dict[str, Any]
    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    elapsed_ms: int = 0


class AgentRunResult(BaseModel):
    instruction: str
    plan: AgentPlan
    executions: List[StepExecution] = Field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None


# -----------------------------------------------------------------------------
# Brain
# -----------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """你是 Pixelle-Video 项目的总控 Agent。\
用户会用自然语言下达一个任务（例如"做个关于 X 的短视频然后发小红书"），\
你必须把它拆成有序的工具调用并以 JSON 返回。

可用工具清单（name / description / args_schema）：
{tools_json}

规则：
1. 只能使用清单内的工具，工具名拼写必须完全一致。
2. 步骤要尽量少；若不需要调用任何工具（例如用户只是问问题），返回空 steps。
3. 当下一步参数依赖上一步结果时，使用占位符字符串：
   "${{steps[i].result.field_name}}"，i 从 0 起。例如把生成的 video_path 传给 enqueue_publish。
4. 字段必须严格按 args_schema 的类型；缺省值可省略。
5. summary 用一句中文概括你对用户意图的理解。

用户指令："{instruction}"
"""


def _resolve_placeholders(args: Dict[str, Any], prior_results: List[Any]) -> Dict[str, Any]:
    """Replace ${steps[i].result.x.y} placeholders in args with actual values."""
    import re

    pattern = re.compile(r"^\$\{steps\[(\d+)\]\.result(?:\.([\w.]+))?\}$")

    def _resolve_one(value: Any) -> Any:
        if isinstance(value, str):
            m = pattern.match(value.strip())
            if not m:
                return value
            idx = int(m.group(1))
            path = m.group(2)
            if idx >= len(prior_results):
                raise ValueError(f"Placeholder references step {idx} which has not run")
            cur = prior_results[idx]
            if path:
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = getattr(cur, part, None)
            return cur
        if isinstance(value, list):
            return [_resolve_one(v) for v in value]
        if isinstance(value, dict):
            return {k: _resolve_one(v) for k, v in value.items()}
        return value

    return {k: _resolve_one(v) for k, v in args.items()}


class AgentBrain:
    """Orchestrates planning + execution for one instruction."""

    def __init__(self, llm=None):
        """`llm` is a LLMService instance; defaults to pixelle_video.llm."""
        if llm is None:
            from pixelle_video.service import pixelle_video as core
            llm = core.llm
        self._llm = llm

    async def plan(self, instruction: str) -> AgentPlan:
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            tools_json=json.dumps(tools_manifest(), ensure_ascii=False, indent=2),
            instruction=instruction.replace('"', '\\"'),
        )
        logger.info(f"[agent] planning for: {instruction!r}")
        plan: AgentPlan = await self._llm(
            prompt=prompt,
            response_type=AgentPlan,
            temperature=0.2,
            max_tokens=1500,
        )
        logger.info(
            f"[agent] plan ready: {plan.summary} | {len(plan.steps)} step(s)"
        )
        return plan

    async def execute(self, plan: AgentPlan) -> List[StepExecution]:
        executions: List[StepExecution] = []
        prior_results: List[Any] = []
        for i, step in enumerate(plan.steps):
            tool = get_tool(step.tool)
            t0 = time.time()
            if tool is None:
                err = f"Unknown tool: {step.tool!r}"
                logger.error(f"[agent] step {i} {err}")
                executions.append(StepExecution(
                    index=i, tool=step.tool, args=step.args,
                    ok=False, error=err, elapsed_ms=0,
                ))
                break

            try:
                resolved = _resolve_placeholders(step.args, prior_results)
                logger.info(f"[agent] step {i}: {step.tool}({resolved})")
                result = await tool.handler(**resolved)
                prior_results.append(result)
                executions.append(StepExecution(
                    index=i, tool=step.tool, args=resolved,
                    ok=True, result=result,
                    elapsed_ms=int((time.time() - t0) * 1000),
                ))
            except Exception as e:  # noqa: BLE001
                logger.exception(f"[agent] step {i} failed")
                executions.append(StepExecution(
                    index=i, tool=step.tool, args=step.args,
                    ok=False, error=f"{type(e).__name__}: {e}",
                    elapsed_ms=int((time.time() - t0) * 1000),
                ))
                break
        return executions

    async def run(self, instruction: str) -> AgentRunResult:
        try:
            plan = await self.plan(instruction)
        except Exception as e:  # noqa: BLE001
            logger.exception("[agent] planning failed")
            return AgentRunResult(
                instruction=instruction,
                plan=AgentPlan(summary="<planning failed>", steps=[]),
                ok=False,
                error=f"planning failed: {type(e).__name__}: {e}",
            )

        executions = await self.execute(plan)
        all_ok = all(e.ok for e in executions)
        return AgentRunResult(
            instruction=instruction,
            plan=plan,
            executions=executions,
            ok=all_ok,
            error=None if all_ok else (executions[-1].error if executions else None),
        )
