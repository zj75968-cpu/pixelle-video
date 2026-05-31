from PIL import Image

from pixelle_video.device_farm.verification.evidence import EvidenceStore
from pixelle_video.device_farm.verification.models import (
    NormalizedFrame,
    VerificationResult,
    VerificationStatus,
)


def make_frame(color):
    return NormalizedFrame(
        image=Image.new("RGB", (10, 10), color),
        timestamp=1.0,
        raw_size=(10, 10),
        logical_size=(10, 10),
        provider_id="test",
        projection_id="test",
    )


def test_evidence_store_saves_frames_and_result(tmp_path):
    store = EvidenceStore(root_dir=tmp_path)
    result = VerificationResult(
        status=VerificationStatus.PASS,
        confidence=1.0,
        reason="ok",
        metrics={"changed_ratio": 0.5},
    )

    paths = store.save(
        device_id="vivo_v2199a_001",
        run_id="run1",
        step_id="step1",
        before=make_frame((0, 0, 0)),
        after=make_frame((255, 255, 255)),
        result=result,
    )

    assert paths["before"].endswith("before.png")
    assert paths["after"].endswith("after.png")
    assert paths["result"].endswith("result.json")
