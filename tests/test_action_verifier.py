from PIL import Image

from pixelle_video.device_farm.verification.action_verifier import ActionVerifier
from pixelle_video.device_farm.verification.frame_provider import FileFrameProvider
from pixelle_video.device_farm.verification.models import (
    ActionMetadata,
    CaptureMetadata,
    NormalizedFrame,
    VerificationStatus,
)


class FakeCH9329:
    def __init__(self):
        self.clicked = []

    def click(self, x_ratio, y_ratio):
        self.clicked.append((x_ratio, y_ratio))
        return True


class RecordingProvider:
    def __init__(self, frame: NormalizedFrame | None = None, fail_open: bool = False):
        self.frame = frame or NormalizedFrame(
            image=Image.new("RGB", (20, 20), (0, 0, 0)),
            timestamp=1.0,
            raw_size=(20, 20),
            logical_size=(20, 20),
            provider_id="recording",
            projection_id="recording",
        )
        self.fail_open = fail_open
        self.opened = False
        self.closed = False
        self.frame_count = 0

    def open(self) -> None:
        if self.fail_open:
            raise RuntimeError("open failed")
        self.opened = True

    def close(self) -> None:
        self.closed = True
        self.opened = False

    def get_frame(self) -> NormalizedFrame:
        self.frame_count += 1
        return self.frame

    def get_metadata(self) -> CaptureMetadata:
        return CaptureMetadata(provider="recording", provider_id="recording", raw_size=(20, 20))

    def health_check(self) -> dict:
        return {"status": "ok"}


def test_action_verifier_runs_ch9329_and_rule(tmp_path):
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    Image.new("RGB", (20, 20), (0, 0, 0)).save(before_path)
    Image.new("RGB", (20, 20), (255, 255, 255)).save(after_path)

    before_provider = FileFrameProvider(before_path, logical_size=(20, 20), provider_id="before")
    after_provider = FileFrameProvider(after_path, logical_size=(20, 20), provider_id="after")
    ch9329 = FakeCH9329()
    verifier = ActionVerifier(
        ch9329=ch9329,
        before_provider=before_provider,
        after_provider=after_provider,
    )

    result = verifier.verify_tap(
        action=ActionMetadata(action_type="tap", point_name="test", x=10, y=10, x_ratio=0.5, y_ratio=0.5),
        rules={
            "changed": {
                "type": "region_diff",
                "region": {"x": 0, "y": 0, "width": 20, "height": 20},
                "threshold": {"min_changed_ratio": 0.5},
            }
        },
    )

    assert ch9329.clicked == [(0.5, 0.5)]
    assert result.status is VerificationStatus.PASS


def test_action_verifier_closes_before_provider_when_after_provider_open_fails():
    before_provider = RecordingProvider()
    after_provider = RecordingProvider(fail_open=True)
    verifier = ActionVerifier(FakeCH9329(), before_provider=before_provider, after_provider=after_provider)

    try:
        verifier.verify_tap(
            ActionMetadata(action_type="tap", x=10, y=10, x_ratio=0.5, y_ratio=0.5),
            rules={},
        )
    except RuntimeError as exc:
        assert "open failed" in str(exc)
    else:
        raise AssertionError("after_provider.open should fail")

    assert before_provider.closed is True


def test_action_verifier_waits_after_click_before_capturing_after_frame():
    before_provider = RecordingProvider()
    after_provider = RecordingProvider(
        NormalizedFrame(
            image=Image.new("RGB", (20, 20), (255, 255, 255)),
            timestamp=2.0,
            raw_size=(20, 20),
            logical_size=(20, 20),
            provider_id="after",
            projection_id="after",
        )
    )
    calls = []

    verifier = ActionVerifier(
        FakeCH9329(),
        before_provider=before_provider,
        after_provider=after_provider,
        post_action_delay=0.25,
        wait_hook=lambda delay: calls.append(("wait", delay, after_provider.frame_count)),
    )

    result = verifier.verify_tap(
        ActionMetadata(action_type="tap", x=10, y=10, x_ratio=0.5, y_ratio=0.5),
        rules={
            "changed": {
                "type": "region_diff",
                "region": {"x": 0, "y": 0, "width": 20, "height": 20},
                "threshold": {"min_changed_ratio": 0.5},
            }
        },
    )

    assert calls == [("wait", 0.25, 0)]
    assert result.status is VerificationStatus.PASS
