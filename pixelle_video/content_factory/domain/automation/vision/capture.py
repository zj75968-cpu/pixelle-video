from __future__ import annotations

from typing import Any

try:  # pragma: no cover - import guard
    import cv2  # type: ignore
except Exception:  # pragma: no cover - cv2 not installed
    cv2 = None  # type: ignore


class HDMICapture:
    """Read frames from a UVC HDMI capture card via OpenCV.

    Never raises on hardware/dependency problems; failures surface as
    ``available=False`` / ``read_frame()`` returning None.
    """

    def __init__(self, camera_index: int, width: int = 1280, height: int = 720):
        self.camera_index = camera_index
        self._cap: Any = None
        self.available = False
        if cv2 is None:
            return
        try:
            cap = cv2.VideoCapture(camera_index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if cap.isOpened():
                self._cap = cap
                self.available = True
            else:
                cap.release()
        except Exception:
            self._cap = None
            self.available = False

    def read_frame(self) -> Any:
        if not self.available or self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
            return frame if ok else None
        except Exception:
            return None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self.available = False
