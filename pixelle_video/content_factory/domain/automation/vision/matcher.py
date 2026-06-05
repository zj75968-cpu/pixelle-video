from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MatchResult:
    matched: bool
    confidence: float
    center_x: int
    center_y: int
    frame_w: int
    frame_h: int


class TemplateMatcher:
    """Locate a template image inside a captured frame via OpenCV.

    cv2/numpy are imported lazily so importing this module never requires them.
    """

    def match(self, frame: Any, template_path: Path, threshold: float = 0.8) -> MatchResult:
        import cv2  # lazy: only needed for real vision

        h_frame, w_frame = frame.shape[:2]
        template = cv2.imread(str(template_path), 0)
        if template is None:
            return MatchResult(False, 0.0, 0, 0, w_frame, h_frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        th, tw = template.shape[:2]
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            return MatchResult(
                True, float(max_val), max_loc[0] + tw // 2, max_loc[1] + th // 2, w_frame, h_frame
            )
        return MatchResult(False, float(max_val), 0, 0, w_frame, h_frame)
