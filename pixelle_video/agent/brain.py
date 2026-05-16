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
    attempts: int = 1
    repair_notes: Optional[str] = None


class RepairedStep(BaseModel):
    """LLM-corrected version of a failed step."""

    tool: str = Field(description="工具名（通常与失败步骤一致；若需换工具可改）")
    args: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", description="修复思路（中文一句话）")
    give_up: bool = Field(default=False, description="如果无法修复请置 true 让 Agent 停止")


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
3. 当下一步参数依赖上一步结果时，使用占位符字符串。占位符必须**整串**匹配以下格式：
   "${{steps[i].result}}"  整个结果
   "${{steps[i].result.field}}"  顶层字段
   "${{steps[i].result.jobs[0].job_id}}"  嵌套数组取元素再取字段
   - i 从 0 起，对应已执行步骤的下标
   - i 从 0 起，对应已执行步骤的下标
   - 字段名必须**严格**对应该工具实际返回的 JSON key（例如 list_jobs 返回的列表里
     每个对象的主键是 `job_id`，不是 `id`；generate_video 返回的字典里视频路径字段叫
     `video_path`，不是整个 result 字典）
   - 反例（错误，会把整个 dict 当字符串传给下一步）：
       "video_path": "${{steps[0].result}}"
     正例：
       "video_path": "${{steps[0].result.video_path}}"
4. 字段必须严格按 args_schema 的类型；缺省值可省略。
5. summary 用一句中文概括你对用户意图的理解。
6. **设备智能推荐**：当任务涉及把内容发布到小红书（enqueue_publish）时：
   - 如果用户没有明确指定 device_serial：必须在 enqueue_publish 之前**先调用 `recommend_device`**，
     topic 用本次发布的选题/主题（短句即可，如"职场效率""萌宠日常"）。
   - 然后用占位符把推荐结果传给 enqueue_publish：
       `"device_serial": "${{steps[i].result.picks[0].serial}}"`
     （i 是 recommend_device 的步骤下标）。
   - **如果 recommend_device 返回 picks 为空**，说明当前没有已连接设备。此时**仍须将 enqueue_publish 步骤保留在计划中**（正常填写 title/body/hashtags 等参数，device_serial 留空），以便 UI 展示人工选设备界面；在 plan.notes 中写明「没有已连接设备，将由用户手动选择设备后入队」。**不可省略 enqueue_publish 步骤**。
7. **小红书发布类型**（enqueue_publish 的 `kind` 参数）：
   - 用户说「视频」「纯视频」「视频笔记」或指令含 kind=video → kind="video"（上传 .mp4，默认）
   - 用户说「图文」「图文点评」「图文笔记」「图文视频」或指令含 kind=image_text → kind="image_text"（自动取 frames/*_composed.png 场景合成图，无需手动传 images）
   - 未提及发布类型时默认 kind="video"。
8. **图文帖定位**（generate_image_text_post 的 `post_type` 参数）：
   - 用户说「干货」「教程」「方法」「技巧」「清单」「攻略」「避坑」「知识」「科普」「新手必看」→ post_type="content"（📚 干货帖，结构化分点、不带强引导话术）
   - 用户说「引流」「钩子」「转化」「私信」「评论扣 1」「主页有完整版」「营销」「拉新」「冲粉丝」「悬念」「反差」→ post_type="traffic"（📢 引流帖，制造钩子 + 必带 CTA）
   - 未提到时默认 "content"。
   - 当 post_type="traffic" 且用户提到时效（如「24 小时后删」「发完明天就删」「短效」）→ 同时设置 traffic_ttl_hours=对应小时数；后续 enqueue_publish 时把同样的值传给 delete_after_hours（不要遗漏，否则 TTL 不会生效）。
9. **违禁词**：用户给出「不要出现 X」「禁止 X」「屏蔽 X」类指令时，先调用 add_banned_keywords（mode='append'）写入，再继续后续生成步骤；这样新生成的内容会在 LLM 层就避开这些词。

用户指令："{instruction}"
"""


def _resolve_placeholders(args: Dict[str, Any], prior_results: List[Any]) -> Dict[str, Any]:
    """Replace ${steps[i].result.x.y[0].z} placeholders in args with actual values.

    Supported path syntax after `.result`:
      - dot field: `.foo`
      - array index: `[0]` or `.0`
      - chained: `.jobs[0].job_id` or `.jobs.0.job_id`
    """
    import re

    # Full-string match. The trailing part after .result is captured verbatim and
    # parsed manually so we can support [N] segments.
    pattern = re.compile(r"^\$\{steps\[(\d+)\]\.result((?:\.[\w]+|\[\d+\]|\.\d+)*)\}$")
    seg_re = re.compile(r"\.([A-Za-z_][\w]*)|\[(\d+)\]|\.(\d+)")

    def _walk(cur: Any, raw_path: str) -> Any:
        if not raw_path:
            return cur
        for m in seg_re.finditer(raw_path):
            field, idx_bracket, idx_dot = m.groups()
            if field is not None:
                if isinstance(cur, dict):
                    cur = cur.get(field)
                else:
                    cur = getattr(cur, field, None)
            else:
                i = int(idx_bracket if idx_bracket is not None else idx_dot)
                if isinstance(cur, (list, tuple)) and 0 <= i < len(cur):
                    cur = cur[i]
                else:
                    cur = None
            if cur is None:
                return None
        return cur

    def _resolve_one(value: Any) -> Any:
        if isinstance(value, str):
            m = pattern.match(value.strip())
            if not m:
                return value
            idx = int(m.group(1))
            raw_path = m.group(2) or ""
            if idx >= len(prior_results):
                raise ValueError(f"Placeholder references step {idx} which has not run")
            return _walk(prior_results[idx], raw_path)
        if isinstance(value, list):
            return [_resolve_one(v) for v in value]
        if isinstance(value, dict):
            return {k: _resolve_one(v) for k, v in value.items()}
        return value

    return {k: _resolve_one(v) for k, v in args.items()}


def _classify_error(exc: Exception, tool=None) -> str:
    """Turn a raw exception into an LLM-friendly diagnostic string.

    The goal is to give the repair LLM enough context to fix the args:
    explicitly call out missing / unexpected keyword arguments, validation
    errors, and external resource failures.
    """
    etype = type(exc).__name__
    msg = str(exc) or repr(exc)

    if isinstance(exc, TypeError):
        # e.g. _enqueue_publish() missing 1 required positional argument: 'title'
        #      _enqueue_publish() got an unexpected keyword argument 'devid'
        hint = ""
        if "missing" in msg and "required" in msg:
            hint = "（修复方向：在 args 里补上缺失的字段）"
        elif "unexpected keyword argument" in msg:
            hint = "（修复方向：从 args 中删掉这个非法字段，或改成 schema 里允许的字段名）"
        elif "positional" in msg:
            hint = "（修复方向：检查参数是不是写成了位置参数；agent 调用都用关键字参数）"
        return f"{etype}: {msg}{hint}"

    if isinstance(exc, ValueError):
        return f"{etype}: {msg}（修复方向：值类型/枚举/范围不合法，按 schema 调整）"

    if isinstance(exc, KeyError):
        return f"{etype}: missing key {msg}（修复方向：上一步结果里没有该字段，检查占位符路径）"

    if isinstance(exc, FileNotFoundError):
        return f"{etype}: {msg}（修复方向：路径不存在，确认是否需要先 generate_video 或纠正占位符）"

    if isinstance(exc, RuntimeError):
        # Common for "No Android device connected" / "LLM service not configured".
        return f"{etype}: {msg}（修复方向：运行时前置条件不满足，可能需要换工具或换设备）"

    # Generic fallback.
    return f"{etype}: {msg}"


class AgentBrain:
    """Orchestrates planning + execution for one instruction."""

    # How many LLM-driven repair attempts to allow per failing step before
    # giving up. Total tries per step = 1 (original) + MAX_STEP_REPAIRS.
    MAX_STEP_REPAIRS: int = 2

    def __init__(self, llm=None):
        """`llm` is a LLMService instance; defaults to pixelle_video.llm.

        We do NOT fail here if `llm` is None — the core service may not have
        been initialized yet. `_ensure_llm` will lazy-initialize it before
        the first LLM call.
        """
        self._llm = llm

    async def _ensure_llm(self):
        if self._llm is not None:
            return
        from pixelle_video.service import pixelle_video as core
        if not getattr(core, "_initialized", False):
            await core.initialize()
        self._llm = core.llm
        if self._llm is None:
            raise RuntimeError(
                "LLM service is not configured; cannot run AgentBrain. "
                "Configure LLM in 创作页 / Developer Tools first."
            )

    async def plan(self, instruction: str) -> AgentPlan:
        await self._ensure_llm()
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
            exec_record = await self._run_step_with_repair(
                index=i,
                step=step,
                prior_results=prior_results,
            )
            executions.append(exec_record)
            if not exec_record.ok:
                break
            prior_results.append(exec_record.result)
        return executions

    async def _run_step_with_repair(
        self,
        index: int,
        step: AgentStep,
        prior_results: List[Any],
    ) -> StepExecution:
        """Run a single step, asking the LLM to repair invalid args on failure.

        Total tries = 1 + MAX_STEP_REPAIRS. Returns the final StepExecution
        (success on first/repaired try, or failure after exhausting retries).
        """
        current_tool_name = step.tool
        current_args = step.args
        current_reason = step.reason
        repair_history: List[Dict[str, str]] = []
        attempts = 0
        last_error: Optional[str] = None
        last_resolved_args: Dict[str, Any] = dict(current_args)

        max_tries = 1 + max(0, self.MAX_STEP_REPAIRS)
        for attempt_no in range(1, max_tries + 1):
            attempts = attempt_no
            tool = get_tool(current_tool_name)
            t0 = time.time()
            if tool is None:
                last_error = (
                    f"Unknown tool: {current_tool_name!r}. "
                    f"Available: {[t.name for t in TOOLS]}"
                )
                logger.error(f"[agent] step {index} attempt {attempt_no}: {last_error}")
            else:
                try:
                    resolved = _resolve_placeholders(current_args, prior_results)
                    last_resolved_args = resolved
                    logger.info(
                        f"[agent] step {index} attempt {attempt_no}: "
                        f"{current_tool_name}({resolved})"
                    )
                    result = await tool.handler(**resolved)
                    return StepExecution(
                        index=index,
                        tool=current_tool_name,
                        args=resolved,
                        ok=True,
                        result=result,
                        elapsed_ms=int((time.time() - t0) * 1000),
                        attempts=attempt_no,
                        repair_notes=("; ".join(h["reason"] for h in repair_history) or None),
                    )
                except Exception as e:  # noqa: BLE001
                    last_error = _classify_error(e, tool)
                    logger.warning(
                        f"[agent] step {index} attempt {attempt_no} failed: {last_error}"
                    )

            # If we've used all attempts, stop.
            if attempt_no >= max_tries:
                break

            # Ask LLM for a repaired step.
            try:
                repaired = await self._repair_step(
                    step_index=index,
                    failed_tool=current_tool_name,
                    failed_args=current_args,
                    failed_reason=current_reason,
                    error=last_error or "<unknown>",
                    prior_results=prior_results,
                    history=repair_history,
                )
            except Exception as repair_exc:  # noqa: BLE001
                logger.warning(
                    f"[agent] step {index}: repair LLM call failed: {repair_exc}; aborting"
                )
                break

            if repaired.give_up:
                logger.info(f"[agent] step {index}: LLM gave up repair ({repaired.reason})")
                last_error = f"{last_error} | LLM gave up: {repaired.reason}"
                break

            repair_history.append({
                "from_tool": current_tool_name,
                "from_args": json.dumps(current_args, ensure_ascii=False),
                "error": last_error or "",
                "reason": repaired.reason or "",
            })
            current_tool_name = repaired.tool
            current_args = repaired.args
            current_reason = repaired.reason

        # All attempts exhausted.
        return StepExecution(
            index=index,
            tool=current_tool_name,
            args=last_resolved_args,
            ok=False,
            error=last_error,
            elapsed_ms=0,
            attempts=attempts,
            repair_notes=("; ".join(h["reason"] for h in repair_history) or None),
        )

    async def _repair_step(
        self,
        step_index: int,
        failed_tool: str,
        failed_args: Dict[str, Any],
        failed_reason: str,
        error: str,
        prior_results: List[Any],
        history: List[Dict[str, str]],
    ) -> RepairedStep:
        """Ask the LLM to produce a corrected step given the failure context."""
        await self._ensure_llm()
        tool_spec = get_tool(failed_tool)
        tool_schema_json = (
            json.dumps(
                {
                    "name": tool_spec.name,
                    "description": tool_spec.description,
                    "args_schema": tool_spec.args_schema,
                },
                ensure_ascii=False,
                indent=2,
            )
            if tool_spec is not None
            else json.dumps(tools_manifest(), ensure_ascii=False)
        )

        # Compact prior-result summaries so the LLM can re-target placeholders.
        prior_summary = []
        for i, r in enumerate(prior_results):
            try:
                preview = json.dumps(r, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                preview = str(r)
            if len(preview) > 800:
                preview = preview[:800] + "...<truncated>"
            prior_summary.append({"step": i, "result_preview": preview})

        history_block = (
            "\n以下是之前的修复尝试（最新在最后）：\n"
            + json.dumps(history, ensure_ascii=False, indent=2)
            if history else ""
        )

        repair_prompt = f"""你正在修复 Pixelle-Video Agent 的一个失败步骤。

失败步骤：
  index = {step_index}
  tool  = {failed_tool}
  args  = {json.dumps(failed_args, ensure_ascii=False)}
  reason = {failed_reason!r}

错误信息：
  {error}

该工具完整 schema：
{tool_schema_json}

已执行步骤的返回值预览（用于占位符引用）：
{json.dumps(prior_summary, ensure_ascii=False, indent=2)}
{history_block}

修复规则：
1. 优先**只调整 args**——比如补缺失字段、删多余字段、转换类型、修正占位符路径。
2. 占位符语法： "${{steps[i].result.<field>}}"，i 必须 < {len(prior_results)}。
3. 不要使用 schema 不允许的字段；若不知道某字段值，留空即可。
4. 如果错误来源是"工具不存在"或本步骤根本无法修复，请设 give_up=true 并简要说明。
5. 返回的 tool 通常应等于 {failed_tool}；如确有必要换工具，必须用清单中存在的工具名。

请输出修复后的 RepairedStep（JSON）。"""

        repaired: RepairedStep = await self._llm(
            prompt=repair_prompt,
            response_type=RepairedStep,
            temperature=0.1,
            max_tokens=600,
        )
        return repaired

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
