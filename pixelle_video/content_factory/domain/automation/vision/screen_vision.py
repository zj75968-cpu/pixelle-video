from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from content_factory.domain.automation.vision.capture import HDMICapture
from content_factory.domain.automation.vision.matcher import TemplateMatcher
from content_factory.domain.automation.vision.templates import resolve_template


@dataclass
class VisionOutcome:
    matched: bool
    confidence: float = 0.0
    x_ratio: float = 0.0
    y_ratio: float = 0.0
    simulated: bool = False
    reason: str | None = None


class ScreenVision:
    """Facade combining a capture source and a template matcher.

    When ``simulate`` is True or no capture device is available, ``verify`` and
    ``wait_for`` short-circuit to a matched/simulated outcome (degrade-to-pass).
    """

    def __init__(
        self,
        camera_index: int | None,
        platform: str = "xhs",
        simulate: bool = True,
        capture: Any = None,
        matcher: Any = None,
    ):
        self.platform = platform
        self.simulate = simulate
        self._matcher = matcher or TemplateMatcher()
        if capture is not None:
            self._capture = capture
        elif simulate or camera_index is None:
            self._capture = None
        else:
            self._capture = HDMICapture(camera_index)

    @property
    def available(self) -> bool:
        return bool(
            not self.simulate
            and self._capture is not None
            and getattr(self._capture, "available", False)
        )

    def _check_once(self, template_ref: str | None, threshold: float) -> VisionOutcome:
        path = resolve_template(template_ref)
        if path is None:
            return VisionOutcome(matched=False, reason="template_missing")
        frame = self._capture.read_frame()
        if frame is None:
            return VisionOutcome(matched=False, reason="no_frame")
        r = self._matcher.match(frame, path, threshold)
        x_ratio = (r.center_x / r.frame_w) if r.frame_w else 0.0
        y_ratio = (r.center_y / r.frame_h) if r.frame_h else 0.0
        return VisionOutcome(
            matched=r.matched, confidence=r.confidence, x_ratio=x_ratio, y_ratio=y_ratio
        )

    def verify(self, template_ref: str | None, threshold: float = 0.8) -> VisionOutcome:
        if not self.available:
            return VisionOutcome(matched=True, simulated=True)
        return self._check_once(template_ref, threshold)

    def wait_for(
        self,
        template_ref: str | None,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = 0.8,
    ) -> VisionOutcome:
        if not self.available:
            return VisionOutcome(matched=True, simulated=True)
        deadline = time.monotonic() + timeout
        last = VisionOutcome(matched=False, reason="timeout")
        while True:
            last = self._check_once(template_ref, threshold)
            if last.matched:
                return last
            if time.monotonic() >= deadline:
                if last.reason is None:
                    last.reason = "timeout"
                return last
            time.sleep(interval)

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
