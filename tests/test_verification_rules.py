from PIL import Image

from pixelle_video.device_farm.verification.models import ActionMetadata, NormalizedFrame, VerificationStatus
from pixelle_video.device_farm.verification.rules import evaluate_rule


def frame(color: tuple[int, int, int], size: tuple[int, int] = (100, 100)) -> NormalizedFrame:
    return NormalizedFrame(
        image=Image.new("RGB", size, color),
        timestamp=1.0,
        raw_size=size,
        logical_size=size,
        provider_id="test",
        projection_id="test",
    )


def test_region_diff_passes_when_region_changes():
    before = frame((0, 0, 0))
    after = frame((255, 255, 255))
    rule = {
        "type": "region_diff",
        "region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "threshold": {"min_changed_ratio": 0.5},
    }

    result = evaluate_rule("screen_changed", rule, before, after)

    assert result.status is VerificationStatus.PASS
    assert result.metrics["changed_ratio"] == 1.0


def test_color_probe_passes_for_near_color():
    current = frame((250, 36, 66))
    rule = {
        "type": "color_probe",
        "probes": [
            {"x": 10, "y": 10, "expected": {"color_near": "#ff2442", "tolerance": 10}}
        ],
    }

    result = evaluate_rule("red_button", rule, current, current)

    assert result.status is VerificationStatus.PASS


def test_touch_feedback_fails_when_local_region_does_not_change():
    before = frame((20, 20, 20))
    after = frame((20, 20, 20))
    rule = {
        "type": "touch_feedback",
        "radius": 20,
        "target": {"x": 50, "y": 50},
        "threshold": {"min_changed_ratio": 0.01},
    }

    result = evaluate_rule("tap_feedback", rule, before, after)

    assert result.status is VerificationStatus.RETRYABLE_FAIL


def test_touch_feedback_uses_action_coordinates_when_rule_has_no_target():
    before = frame((0, 0, 0))
    after_img = Image.new("RGB", (100, 100), (0, 0, 0))
    for x in range(75, 86):
        for y in range(15, 26):
            after_img.putpixel((x, y), (255, 255, 255))
    after = NormalizedFrame(
        image=after_img,
        timestamp=1.0,
        raw_size=(100, 100),
        logical_size=(100, 100),
        provider_id="test",
        projection_id="test",
    )
    rule = {"type": "touch_feedback", "radius": 10, "threshold": {"min_changed_ratio": 0.2}}
    action = ActionMetadata(action_type="tap", x=80, y=20, x_ratio=0.8, y_ratio=0.2)

    result = evaluate_rule("tap_feedback", rule, before, after, action=action)

    assert result.status is VerificationStatus.PASS
    assert result.metrics["region"] == {"x": 70, "y": 10, "width": 20, "height": 20}


def test_touch_feedback_explicit_target_overrides_action_coordinates():
    before = frame((0, 0, 0))
    after_img = Image.new("RGB", (100, 100), (0, 0, 0))
    for x in range(10, 21):
        for y in range(70, 81):
            after_img.putpixel((x, y), (255, 255, 255))
    after = NormalizedFrame(
        image=after_img,
        timestamp=1.0,
        raw_size=(100, 100),
        logical_size=(100, 100),
        provider_id="test",
        projection_id="test",
    )
    rule = {
        "type": "touch_feedback",
        "radius": 10,
        "target": {"x": 15, "y": 75},
        "threshold": {"min_changed_ratio": 0.2},
    }
    action = ActionMetadata(action_type="tap", x=80, y=20, x_ratio=0.8, y_ratio=0.2)

    result = evaluate_rule("tap_feedback", rule, before, after, action=action)

    assert result.status is VerificationStatus.PASS
    assert result.metrics["region"] == {"x": 5, "y": 65, "width": 20, "height": 20}


def test_region_diff_honors_on_fail_policy():
    before = frame((20, 20, 20))
    after = frame((20, 20, 20))
    rule = {
        "type": "region_diff",
        "region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "threshold": {"min_changed_ratio": 0.01},
        "on_fail": "hard_fail",
    }

    result = evaluate_rule("must_change", rule, before, after)

    assert result.status is VerificationStatus.HARD_FAIL
    assert result.suggested_action == "abort"


def test_color_probe_out_of_bounds_returns_structured_failure():
    current = frame((250, 36, 66), size=(20, 20))
    rule = {
        "type": "color_probe",
        "probes": [{"x": 25, "y": 10, "expected": {"color_near": "#ff2442"}}],
    }

    result = evaluate_rule("red_button", rule, current, current)

    assert result.status is VerificationStatus.MANUAL_REQUIRED
    assert result.failed_rules == ["red_button"]
    assert "out of bounds" in result.reason
    assert result.metrics["point"] == {"x": 25, "y": 10}


def test_region_diff_out_of_bounds_returns_structured_failure_without_padded_metrics():
    before = frame((0, 0, 0), size=(20, 20))
    after = frame((255, 255, 255), size=(20, 20))
    rule = {
        "type": "region_diff",
        "region": {"x": 10, "y": 10, "width": 20, "height": 20},
        "threshold": {"min_changed_ratio": 0.5},
    }

    result = evaluate_rule("screen_changed", rule, before, after)

    assert result.status is VerificationStatus.MANUAL_REQUIRED
    assert result.failed_rules == ["screen_changed"]
    assert "out of bounds" in result.reason
    assert "changed_ratio" not in result.metrics
