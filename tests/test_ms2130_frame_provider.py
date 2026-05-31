from PIL import Image

from pixelle_video.device_farm.verification.frame_provider import (
    FileFrameProvider,
    MS2130FrameProvider,
)
from pixelle_video.device_farm.verification.projection import ProjectionCalibration


def test_file_frame_provider_returns_normalized_frame(tmp_path):
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (20, 10), (1, 2, 3)).save(image_path)

    provider = FileFrameProvider(image_path=image_path, logical_size=(40, 20), provider_id="file:test")
    provider.open()
    frame = provider.get_frame()
    provider.close()

    assert frame.raw_size == (20, 10)
    assert frame.logical_size == (40, 20)
    assert frame.provider_id == "file:test"
    assert frame.image.size == (40, 20)


def test_ms2130_provider_reports_missing_opencv(monkeypatch):
    import pixelle_video.device_farm.verification.frame_provider as module

    monkeypatch.setattr(module, "cv2", None)
    provider = MS2130FrameProvider(camera_index=1, logical_size=(1080, 2400))

    health = provider.health_check()

    assert health["status"] == "unavailable"
    assert "opencv" in health["reason"].lower()


def test_ms2130_provider_uses_projection_calibration_to_normalize_frame(monkeypatch):
    import pixelle_video.device_farm.verification.frame_provider as module

    class FakeCapture:
        def isOpened(self):
            return True

        def read(self):
            return True, "raw-frame"

        def release(self):
            pass

    class FakeCV2:
        CAP_DSHOW = 700
        COLOR_BGR2RGB = 1

        def VideoCapture(self, camera_index, api_preference):
            return FakeCapture()

        def cvtColor(self, frame, conversion):
            assert frame == "raw-frame"
            assert conversion == self.COLOR_BGR2RGB
            return "rgb-array"

    raw_image = Image.new("RGB", (40, 20), (0, 0, 0))
    raw_image.putpixel((30, 10), (255, 0, 0))
    monkeypatch.setattr(module, "cv2", FakeCV2())
    monkeypatch.setattr(module.Image, "fromarray", lambda array: raw_image)
    calibration = ProjectionCalibration(
        projection_id="calibrated",
        raw_size=(40, 20),
        logical_size=(20, 10),
        crop=(20, 0, 20, 20),
        scale_mode="stretch",
    )
    provider = MS2130FrameProvider(camera_index=1, logical_size=(20, 10), projection=calibration)

    provider.open()
    frame = provider.get_frame()
    provider.close()

    assert frame.projection_id == "calibrated"
    assert frame.image.size == (20, 10)
    assert frame.image.getpixel((10, 5))[0] > 100
