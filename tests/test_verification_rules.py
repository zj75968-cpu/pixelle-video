from PIL import Image

from pixelle_video.device_farm.verification.models import NormalizedFrame, VerificationStatus
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
