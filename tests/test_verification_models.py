from pixelle_video.device_farm.verification.models import (
    ActionMetadata,
    NormalizedFrame,
    VerificationResult,
    VerificationStatus,
)


def test_verification_result_defaults_to_empty_evidence():
    result = VerificationResult(
        status=VerificationStatus.PASS,
        confidence=0.9,
        reason="matched",
    )

    assert result.status is VerificationStatus.PASS
    assert result.confidence == 0.9
    assert result.reason == "matched"
    assert result.evidence == {}
    assert result.metrics == {}


def test_normalized_frame_exposes_logical_size():
    frame = NormalizedFrame(
        image=None,
        timestamp=123.4,
        raw_size=(1920, 1080),
        logical_size=(1080, 2400),
        provider_id="ms2130:1",
        projection_id="vivo_v2199a_001",
        quality_flags=["ok"],
    )

    assert frame.logical_width == 1080
    assert frame.logical_height == 2400


def test_action_metadata_records_semantic_point():
    action = ActionMetadata(
        action_type="tap",
        point_name="xhs.home.publish_button",
        x=540,
        y=2160,
        x_ratio=0.5,
        y_ratio=0.9,
        risk="reversible",
    )

    assert action.point_name == "xhs.home.publish_button"
    assert action.risk == "reversible"
