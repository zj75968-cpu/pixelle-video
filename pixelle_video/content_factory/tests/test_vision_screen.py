from __future__ import annotations

from content_factory.domain.automation.vision.matcher import MatchResult
from content_factory.domain.automation.vision.screen_vision import ScreenVision, VisionOutcome


class _FakeCapture:
    def __init__(self, frames):
        self._frames = list(frames)
        self.available = True
        self.released = False

    def read_frame(self):
        return self._frames.pop(0) if self._frames else None

    def release(self):
        self.released = True


class _FakeMatcher:
    def __init__(self, result):
        self._result = result

    def match(self, frame, template_path, threshold=0.8):
        return self._result


def _vision(result, frames=("frame",), simulate=False):
    return ScreenVision(
        camera_index=0,
        platform="xhs",
        simulate=simulate,
        capture=_FakeCapture(frames),
        matcher=_FakeMatcher(result),
    )


def test_unavailable_when_simulate():
    v = ScreenVision(camera_index=0, platform="xhs", simulate=True)
    assert v.available is False
    out = v.verify("xhs/album_tab")
    assert out.matched is True and out.simulated is True


def test_verify_match_maps_ratio(tmp_path, monkeypatch):
    # template must resolve to an existing file
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    (root / "xhs" / "album_tab.png").write_bytes(b"x")
    monkeypatch.setattr(
        "content_factory.domain.automation.vision.screen_vision.resolve_template",
        lambda ref, root=None: (root and None) or (tmp_path / "templates" / "xhs" / "album_tab.png"),
    )
    result = MatchResult(True, 0.95, center_x=50, center_y=100, frame_w=100, frame_h=200)
    v = _vision(result)
    out = v.verify("xhs/album_tab")
    assert out.matched is True
    assert out.x_ratio == 0.5 and out.y_ratio == 0.5
    assert out.simulated is False


def test_template_missing_reports_reason():
    v = _vision(MatchResult(False, 0.0, 0, 0, 100, 200))
    out = v.verify("xhs/does_not_exist")
    assert out.matched is False and out.reason == "template_missing"


def test_wait_for_times_out(monkeypatch, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    monkeypatch.setattr(
        "content_factory.domain.automation.vision.screen_vision.resolve_template",
        lambda ref, root=None: p,
    )
    v = _vision(MatchResult(False, 0.1, 0, 0, 100, 200), frames=("f1",))
    out = v.wait_for("xhs/x", timeout=0.0, interval=0.0)
    assert out.matched is False and out.reason in ("timeout", "no_frame")
