# -*- coding: utf-8 -*-
"""Pure image rule evaluators for CH9329 + MS2130 verification."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops

from .models import ActionMetadata, NormalizedFrame, VerificationResult, VerificationStatus

_FAIL_POLICIES: dict[str, tuple[VerificationStatus, str]] = {
    "manual_required": (VerificationStatus.MANUAL_REQUIRED, "manual_check"),
    "recoverable": (VerificationStatus.RECOVERABLE_FAIL, "recover"),
    "retryable": (VerificationStatus.RETRYABLE_FAIL, "retry"),
    "hard_fail": (VerificationStatus.HARD_FAIL, "abort"),
}


def _failure_status(rule: dict[str, Any]) -> tuple[VerificationStatus, str]:
    return _FAIL_POLICIES.get(str(rule.get("on_fail", "retryable")), _FAIL_POLICIES["retryable"])


def _failure_result(
    rule_id: str,
    rule: dict[str, Any],
    reason: str,
    confidence: float = 0.0,
    metrics: dict[str, Any] | None = None,
) -> VerificationResult:
    status, suggested_action = _failure_status(rule)
    return VerificationResult(
        status=status,
        confidence=confidence,
        reason=reason,
        failed_rules=[rule_id],
        metrics=metrics or {},
        suggested_action=suggested_action,
    )


def evaluate_rule(
    rule_id: str,
    rule: dict[str, Any],
    before: NormalizedFrame,
    after: NormalizedFrame,
    action: ActionMetadata | None = None,
) -> VerificationResult:
    """Evaluate one verification rule against before/after frames."""
    rule_type = rule.get("type")
    if rule_type == "region_diff":
        return _evaluate_region_diff(rule_id, rule, before, after)
    if rule_type == "color_probe":
        return _evaluate_color_probe(rule_id, rule, after)
    if rule_type == "touch_feedback":
        return _evaluate_touch_feedback(rule_id, rule, before, after, action)
    if rule_type == "stable_screen":
        return _evaluate_region_diff(rule_id, rule, before, after, invert=True)
    return VerificationResult(
        status=VerificationStatus.UNKNOWN,
        confidence=0.0,
        reason=f"Unsupported rule type: {rule_type}",
        failed_rules=[rule_id],
        suggested_action="manual_check",
    )


def _as_image(frame: NormalizedFrame) -> Image.Image:
    if isinstance(frame.image, Image.Image):
        return frame.image.convert("RGB")
    raise TypeError("NormalizedFrame.image must be a PIL.Image.Image for v1 rule evaluation")


def _validate_region(region: dict[str, Any], img: Image.Image) -> tuple[dict[str, int] | None, str | None]:
    try:
        x = int(region["x"])
        y = int(region["y"])
        width = int(region["width"])
        height = int(region["height"])
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"invalid region: {exc}"
    normalized = {"x": x, "y": y, "width": width, "height": height}
    if width <= 0 or height <= 0:
        return normalized, "region width and height must be positive"
    if x < 0 or y < 0 or x + width > img.width or y + height > img.height:
        return normalized, f"region out of bounds for image {img.width}x{img.height}"
    return normalized, None


def _crop(img: Image.Image, region: dict[str, int]) -> Image.Image:
    x = region["x"]
    y = region["y"]
    width = region["width"]
    height = region["height"]
    return img.crop((x, y, x + width, y + height))


def _changed_ratio(before_img: Image.Image, after_img: Image.Image) -> float:
    diff = ImageChops.difference(before_img, after_img).convert("L")
    changed = sum(1 for value in diff.getdata() if value > 10)
    total = diff.width * diff.height
    return changed / total if total else 0.0


def _evaluate_region_diff(
    rule_id: str,
    rule: dict[str, Any],
    before: NormalizedFrame,
    after: NormalizedFrame,
    invert: bool = False,
) -> VerificationResult:
    before_img = _as_image(before)
    after_img = _as_image(after)
    region = rule.get("region") or {"x": 0, "y": 0, "width": before_img.width, "height": before_img.height}
    valid_region, region_error = _validate_region(region, before_img)
    if region_error or valid_region is None:
        return _failure_result(rule_id, {**rule, "on_fail": rule.get("on_fail", "manual_required")}, region_error or "invalid region", metrics={"region": valid_region or region})
    after_region, after_error = _validate_region(valid_region, after_img)
    if after_error or after_region is None:
        return _failure_result(rule_id, {**rule, "on_fail": rule.get("on_fail", "manual_required")}, after_error or "invalid region", metrics={"region": valid_region})
    ratio = _changed_ratio(_crop(before_img, valid_region), _crop(after_img, valid_region))
    threshold = float(rule.get("threshold", {}).get("min_changed_ratio", 0.01))
    passed = ratio <= threshold if invert else ratio >= threshold
    if not passed:
        return _failure_result(
            rule_id,
            rule,
            f"changed_ratio={ratio:.4f}, threshold={threshold:.4f}",
            confidence=0.4,
            metrics={"changed_ratio": ratio, "threshold": threshold, "region": valid_region},
        )
    return VerificationResult(
        status=VerificationStatus.PASS,
        confidence=1.0,
        reason=f"changed_ratio={ratio:.4f}, threshold={threshold:.4f}",
        matched_rules=[rule_id],
        metrics={"changed_ratio": ratio, "threshold": threshold, "region": valid_region},
    )


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _evaluate_color_probe(
    rule_id: str,
    rule: dict[str, Any],
    frame: NormalizedFrame,
) -> VerificationResult:
    img = _as_image(frame)
    for probe in rule.get("probes", []):
        x = int(probe["x"])
        y = int(probe["y"])
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            return _failure_result(
                rule_id,
                {**rule, "on_fail": rule.get("on_fail", "manual_required")},
                f"probe point out of bounds for image {img.width}x{img.height}",
                metrics={"point": {"x": x, "y": y}, "image_size": {"width": img.width, "height": img.height}},
            )
        expected = probe.get("expected", {})
        wanted = _hex_to_rgb(str(expected["color_near"]))
        tolerance = int(expected.get("tolerance", 20))
        actual = img.getpixel((x, y))
        distance = max(abs(actual[i] - wanted[i]) for i in range(3))
        if distance > tolerance:
            return _failure_result(
                rule_id,
                {**rule, "on_fail": rule.get("on_fail", "manual_required")},
                f"color distance {distance} exceeds tolerance {tolerance}",
                confidence=0.3,
                metrics={"distance": distance, "tolerance": tolerance},
            )
    return VerificationResult(
        status=VerificationStatus.PASS,
        confidence=1.0,
        reason="all color probes matched",
        matched_rules=[rule_id],
    )


def _evaluate_touch_feedback(
    rule_id: str,
    rule: dict[str, Any],
    before: NormalizedFrame,
    after: NormalizedFrame,
    action: ActionMetadata | None = None,
) -> VerificationResult:
    target = rule.get("target") or {}
    x = target.get("x", action.x if action else before.logical_width // 2)
    y = target.get("y", action.y if action else before.logical_height // 2)
    x = int(x if x is not None else before.logical_width // 2)
    y = int(y if y is not None else before.logical_height // 2)
    radius = int(rule.get("radius", 80))
    region = {
        "x": max(0, x - radius),
        "y": max(0, y - radius),
        "width": min(radius * 2, before.logical_width - max(0, x - radius)),
        "height": min(radius * 2, before.logical_height - max(0, y - radius)),
    }
    merged = dict(rule)
    merged["region"] = region
    return _evaluate_region_diff(rule_id, merged, before, after)
