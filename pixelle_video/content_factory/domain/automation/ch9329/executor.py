from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from content_factory.domain.automation.ch9329.controller import CH9329Controller
from content_factory.domain.automation.vision.screen_vision import ScreenVision  # noqa: F401


@dataclass
class StepResult:
    step_index: int
    step_name: str
    action_type: str
    status: str
    error_message: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class CH9329Executor:
    """Execute a coordinate flow over a CH9329 channel.

    Simulation mode interprets each step and records the action without
    touching hardware, producing a deterministic step-by-step result that the
    publish worker turns into PublishJobLog rows.
    """

    def __init__(
        self,
        controller: CH9329Controller | None = None,
        simulate: bool = True,
        phone_ip: str | None = None,
        vision: "ScreenVision | None" = None,
    ):
        self.simulate = simulate
        self.controller = controller or CH9329Controller(
            simulate=simulate, phone_ip=phone_ip
        )
        self.vision = vision

    def execute_flow(
        self,
        steps: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        *,
        start_step: int = 0,
        end_step: int | None = None,
        stop_on_failure: bool = True,
    ) -> list[StepResult]:
        context = context or {}
        results: list[StepResult] = []
        try:
            self.controller.connect()
        except Exception as exc:  # noqa: BLE001 - record connection failure
            return [
                StepResult(
                    step_index=start_step,
                    step_name="connect_ch9329",
                    action_type="connect",
                    status="failed",
                    error_message=str(exc),
                )
            ]
        try:
            selected = steps[start_step : end_step + 1 if end_step is not None else None]
            for offset, step in enumerate(selected):
                index = start_step + offset
                result = self._run_step(index, step, context)
                results.append(result)
                if result.status == "failed" and stop_on_failure:
                    break
        finally:
            self.controller.disconnect()
            if self.vision is not None:
                self.vision.release()
        return results

    def dry_run(self, flow_name: str, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        results = self.execute_flow(steps or [], {})
        return {
            "flow_name": flow_name,
            "status": "dry_run",
            "steps": [r.__dict__ for r in results],
        }

    def _run_step(self, index: int, step: dict[str, Any], context: dict[str, Any]) -> StepResult:
        action_type = step.get("type", "unknown")
        step_name = step.get("note") or step.get("field") or action_type
        try:
            if action_type == "tap":
                detail = self.controller.tap(int(step.get("x", 0)), int(step.get("y", 0)))
            elif action_type == "input_text":
                text = self._resolve_source(step.get("source"), context)
                detail = self.controller.input_text(text)
            elif action_type == "wait":
                detail = self.controller.wait(float(step.get("seconds", 0)))
            elif action_type in ("wait_for_element", "verify_screen", "click_on_match"):
                detail = self._run_vision_step(action_type, step)
            elif action_type in ("checkpoint", "manual_pause", "select_media", "set_cover", "preview"):
                detail = {
                    "action": action_type,
                    "note": step.get("note"),
                    "simulated": self.simulate,
                }
            elif action_type == "open_app":
                detail = {
                    "action": "open_app",
                    "app": step.get("app") or step.get("package") or "unknown",
                    "simulated": self.simulate,
                }
            else:
                return StepResult(
                    step_index=index,
                    step_name=step_name,
                    action_type=action_type,
                    status="skipped",
                    error_message=f"unsupported_action:{action_type}",
                )
            if detail.get("ok") is False:
                raise RuntimeError(f"{action_type}_failed")
            return StepResult(
                step_index=index,
                step_name=step_name,
                action_type=action_type,
                status="succeeded",
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - record any step failure
            return StepResult(
                step_index=index,
                step_name=step_name,
                action_type=action_type,
                status="failed",
                error_message=str(exc),
            )

    def _run_vision_step(self, action_type: str, step: dict[str, Any]) -> dict[str, Any]:
        template = step.get("template")
        threshold = float(step.get("threshold", 0.8))
        if self.simulate or self.vision is None or not self.vision.available:
            return {"action": action_type, "template": template, "simulated": True}

        if action_type == "wait_for_element":
            timeout = float(step.get("timeout", 10.0))
            outcome = self.vision.wait_for(template, timeout=timeout, threshold=threshold)
        else:  # verify_screen / click_on_match
            outcome = self.vision.verify(template, threshold=threshold)

        detail: dict[str, Any] = {
            "action": action_type,
            "template": template,
            "simulated": False,
            "matched": outcome.matched,
            "confidence": outcome.confidence,
            "reason": outcome.reason,
        }
        if not outcome.matched:
            detail["ok"] = False
            return detail
        if action_type == "click_on_match":
            detail["x_ratio"] = outcome.x_ratio
            detail["y_ratio"] = outcome.y_ratio
            detail["ok"] = self.controller.click(outcome.x_ratio, outcome.y_ratio)
        return detail

    @staticmethod
    def _resolve_source(source: str | None, context: dict[str, Any]) -> str:
        if not source:
            return ""
        # Supports dotted lookups like "publish_package.title".
        node: Any = context
        for part in source.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = getattr(node, part, None)
            if node is None:
                return ""
        return str(node)
