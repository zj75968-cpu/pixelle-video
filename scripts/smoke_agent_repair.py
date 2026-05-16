"""End-to-end smoke test: agent retry/repair really fixes a bad step.

Strategy: craft an AgentPlan with one step whose args are deliberately wrong
(`list_workflows` takes no args, but we pass `name="x"`). The LLM repair loop
should detect TypeError "unexpected keyword argument" and emit a RepairedStep
with empty args, succeeding on the 2nd attempt.

Run from project root:
    .venv\\Scripts\\python.exe scripts\\smoke_agent_repair.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from pixelle_video.agent.brain import AgentBrain, AgentPlan, AgentStep  # noqa: E402


async def main() -> None:
    brain = AgentBrain()
    plan = AgentPlan(
        summary="冒烟测试：用错误参数调用 list_workflows，验证 LLM 修复路径",
        steps=[
            AgentStep(
                tool="list_workflows",
                args={"name": "bogus_param_should_be_removed"},
                reason="故意传入非法 kwarg，触发 TypeError 让 LLM 修复",
            ),
        ],
        notes="期望：第1次失败 → LLM 删掉 name 字段 → 第2次成功。",
    )

    executions = await brain.execute(plan)

    print("\n========== EXECUTION TRACE ==========")
    for rec in executions:
        print(
            json.dumps(
                {
                    "index": rec.index,
                    "tool": rec.tool,
                    "args": rec.args,
                    "ok": rec.ok,
                    "attempts": rec.attempts,
                    "elapsed_ms": rec.elapsed_ms,
                    "error": rec.error,
                    "repair_notes": rec.repair_notes,
                    "result_preview": (str(rec.result)[:200] if rec.result else None),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    ok = bool(executions) and all(e.ok for e in executions)
    print("\nFINAL:", "PASS" if ok else "FAIL")
    if executions:
        first = executions[0]
        print(
            "Repair path exercised?",
            first.attempts > 1 and bool(first.repair_notes),
        )


if __name__ == "__main__":
    asyncio.run(main())
