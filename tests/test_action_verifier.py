from PIL import Image

from pixelle_video.device_farm.verification.action_verifier import ActionVerifier
from pixelle_video.device_farm.verification.frame_provider import FileFrameProvider
from pixelle_video.device_farm.verification.models import ActionMetadata, VerificationStatus


class FakeCH9329:
    def __init__(self):
        self.clicked = []

    def click(self, x_ratio, y_ratio):
        self.clicked.append((x_ratio, y_ratio))
        return True


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
