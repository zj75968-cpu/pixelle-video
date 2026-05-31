# -*- coding: utf-8 -*-
"""Pure image rule evaluators for CH9329 + MS2130 verification."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops

from .models import NormalizedFrame, VerificationResult, VerificationStatus


def evaluate_rule(
    rule_id: str,
    rule: dict[str, Any],
    before: NormalizedFrame,
    after: NormalizedFrame,
) -> VerificationResult:
    """Evaluate one verification rule against before/after frames."""
    rule_type = rule.get("type")
    if rule_type == "region_diff":
        return _evaluate_region_diff(rule_id, rule, before, after)
    if rule_type == "color_probe":
        return _evaluate_color_probe(rule_id, rule, after)
    if rule_type == "touch_feedback":
        return _evaluate_touch_feedback(rule_id, rule, before, after)
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


def _crop(img: Image.Image, region: dict[str, int]) -> Image.Image:
    x = int(region["x"])
    y = int(region["y"])
    width = int(region["width"])
    height = int(region["height"])
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
    ratio = _changed_ratio(_crop(before_img, region), _crop(after_img, region))
    threshold = float(rule.get("threshold", {}).get("min_changed_ratio", 0.01))
    passed = ratio <= threshold if invert else ratio >= threshold
    return VerificationResult(
        status=VerificationStatus.PASS if passed else VerificationStatus.RETRYABLE_FAIL,
        confidence=1.0 if passed else 0.4,
        reason=f"changed_ratio={ratio:.4f}, threshold={threshold:.4f}",
        matched_rules=[rule_id] if passed else [],
        failed_rules=[] if passed else [rule_id],
        metrics={"changed_ratio": ratio, "threshold": threshold},
        suggested_action=None if passed else "retry",
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
        expected = probe.get("expected", {})
        wanted = _hex_to_rgb(str(expected["color_near"]))
        tolerance = int(expected.get("tolerance", 20))
        actual = img.getpixel((x, y))
        distance = max(abs(actual[i] - wanted[i]) for i in range(3))
        if distance > tolerance:
            return VerificationResult(
                status=VerificationStatus.MANUAL_REQUIRED,
                confidence=0.3,
                reason=f"color distance {distance} exceeds tolerance {tolerance}",
                failed_rules=[rule_id],
                metrics={"distance": distance, "tolerance": tolerance},
                suggested_action="manual_check",
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
) -> VerificationResult:
    target = rule.get("target", {})
    x = int(target.get("x", before.logical_width // 2))
    y = int(target.get("y", before.logical_height // 2))
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
