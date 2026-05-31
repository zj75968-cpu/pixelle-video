from PIL import Image

from pixelle_video.device_farm.verification.frame_provider import (
    FileFrameProvider,
    MS2130FrameProvider,
)


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
