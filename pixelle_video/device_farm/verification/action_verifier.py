# -*- coding: utf-8 -*-
"""Action-level orchestration for CH9329 + frame verification."""

from __future__ import annotations

from typing import Any

from .frame_provider import FrameProvider
from .models import ActionMetadata, VerificationResult, VerificationStatus
from .rules import evaluate_rule

_STATUS_PRIORITY = {
    VerificationStatus.HARD_FAIL: 5,
    VerificationStatus.MANUAL_REQUIRED: 4,
    VerificationStatus.RECOVERABLE_FAIL: 3,
    VerificationStatus.RETRYABLE_FAIL: 2,
    VerificationStatus.UNKNOWN: 1,
    VerificationStatus.PASS: 0,
}


class ActionVerifier:
    """Verify CH9329 actions using before/after frames and visual rules."""

    def __init__(self, ch9329: Any, before_provider: FrameProvider, after_provider: FrameProvider | None = None):
        self.ch9329 = ch9329
        self.before_provider = before_provider
        self.after_provider = after_provider or before_provider

    def verify_tap(self, action: ActionMetadata, rules: dict[str, dict[str, Any]]) -> VerificationResult:
        self.before_provider.open()
        if self.after_provider is not self.before_provider:
            self.after_provider.open()
        try:
            before = self.before_provider.get_frame()
            if action.x_ratio is None or action.y_ratio is None:
                return VerificationResult(
                    status=VerificationStatus.MANUAL_REQUIRED,
                    confidence=0.0,
                    reason="tap action is missing ratio coordinates",
                    suggested_action="manual_check",
                )
            if not self.ch9329.click(action.x_ratio, action.y_ratio):
                return VerificationResult(
                    status=VerificationStatus.RETRYABLE_FAIL,
                    confidence=0.0,
                    reason="CH9329 click returned False",
                    suggested_action="retry",
                )
            after = self.after_provider.get_frame()
            return self._evaluate_rules(rules, before, after)
        finally:
            self.before_provider.close()
            if self.after_provider is not self.before_provider:
                self.after_provider.close()

    def _evaluate_rules(self, rules, before, after) -> VerificationResult:
        results = [evaluate_rule(rule_id, rule, before, after) for rule_id, rule in rules.items()]
        if not results:
            return VerificationResult(
                status=VerificationStatus.UNKNOWN,
                confidence=0.0,
                reason="no rules configured",
                suggested_action="manual_check",
            )
        worst = max(results, key=lambda result: _STATUS_PRIORITY[result.status])
        if worst.status is VerificationStatus.PASS:
            return VerificationResult(
                status=VerificationStatus.PASS,
                confidence=min(result.confidence for result in results),
                reason="all rules passed",
                matched_rules=[rule for result in results for rule in result.matched_rules],
                metrics={rule: result.metrics for rule, result in zip(rules, results)},
            )
        return worst
