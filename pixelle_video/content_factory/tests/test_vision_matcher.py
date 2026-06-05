from __future__ import annotations

from content_factory.domain.automation.vision.matcher import MatchResult, TemplateMatcher


def test_match_result_dataclass_fields():
    r = MatchResult(matched=True, confidence=0.9, center_x=10, center_y=20, frame_w=100, frame_h=200)
    assert r.matched and r.center_x == 10 and r.frame_h == 200


def test_match_finds_template_when_cv2_available(tmp_path):
    cv2 = __import__("pytest").importorskip("cv2")
    np = __import__("pytest").importorskip("numpy")
    # white frame with a black 20x20 square at (40,60)
    frame = np.full((200, 100, 3), 255, dtype=np.uint8)
    frame[60:80, 40:60] = 0
    tpl_path = tmp_path / "sq.png"
    cv2.imwrite(str(tpl_path), frame[60:80, 40:60])
    r = TemplateMatcher().match(frame, tpl_path, threshold=0.8)
    assert r.matched is True
    assert 40 <= r.center_x <= 60
    assert 60 <= r.center_y <= 80
    assert r.frame_w == 100 and r.frame_h == 200
