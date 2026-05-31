# -*- coding: utf-8 -*-
"""Frame providers for MS2130 and deterministic file-based verification."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from .models import CaptureMetadata, NormalizedFrame

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - depends on optional runtime package
    cv2 = None


class FrameProvider(Protocol):
    """Protocol implemented by observation providers."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def get_frame(self) -> NormalizedFrame: ...
    def get_metadata(self) -> CaptureMetadata: ...
    def health_check(self) -> dict[str, Any]: ...


class FileFrameProvider:
    """Deterministic provider used by tests and replay fixtures."""

    def __init__(self, image_path: str | Path, logical_size: tuple[int, int], provider_id: str = "file"):
        self.image_path = Path(image_path)
        self.logical_size = logical_size
        self.provider_id = provider_id
        self._opened = False

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def get_frame(self) -> NormalizedFrame:
        if not self._opened:
            raise RuntimeError("FileFrameProvider is not open")
        raw = Image.open(self.image_path).convert("RGB")
        normalized = raw.resize(self.logical_size)
        return NormalizedFrame(
            image=normalized,
            timestamp=time.time(),
            raw_size=raw.size,
            logical_size=self.logical_size,
            provider_id=self.provider_id,
            projection_id=self.provider_id,
            quality_flags=["ok"],
            metadata=self.get_metadata(),
        )

    def get_metadata(self) -> CaptureMetadata:
        return CaptureMetadata(
            provider="file",
            provider_id=self.provider_id,
            raw_size=Image.open(self.image_path).size,
            health="ok" if self._opened else "closed",
        )

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok" if self.image_path.exists() else "missing", "path": str(self.image_path)}


class MS2130FrameProvider:
    """OpenCV DirectShow/UVC provider for MS2130 HDMI capture."""

    def __init__(
        self,
        camera_index: int,
        logical_size: tuple[int, int],
        provider_id: str | None = None,
        api: str = "CAP_DSHOW",
    ):
        self.camera_index = camera_index
        self.logical_size = logical_size
        self.provider_id = provider_id or f"ms2130:{camera_index}"
        self.api = api
        self._capture = None
        self._last_raw_size = (0, 0)

    def open(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not installed; install opencv-python to use MS2130FrameProvider")
        api_preference = cv2.CAP_DSHOW if self.api == "CAP_DSHOW" else 0
        self._capture = cv2.VideoCapture(self.camera_index, api_preference)
        if not self._capture or not self._capture.isOpened():
            raise RuntimeError(f"Failed to open MS2130 camera index {self.camera_index}")

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None

    def get_frame(self) -> NormalizedFrame:
        if cv2 is None:
            raise RuntimeError("OpenCV is not installed")
        if self._capture is None or not self._capture.isOpened():
            raise RuntimeError("MS2130FrameProvider is not open")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("MS2130 returned an empty frame")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        self._last_raw_size = image.size
        normalized = image.resize(self.logical_size)
        return NormalizedFrame(
            image=normalized,
            timestamp=time.time(),
            raw_size=image.size,
            logical_size=self.logical_size,
            provider_id=self.provider_id,
            projection_id=self.provider_id,
            quality_flags=["ok"],
            metadata=self.get_metadata(),
        )

    def get_metadata(self) -> CaptureMetadata:
        return CaptureMetadata(
            provider="ms2130_opencv",
            provider_id=self.provider_id,
            raw_size=self._last_raw_size,
            health="open" if self._capture is not None else "closed",
            details={"camera_index": self.camera_index, "api": self.api},
        )

    def health_check(self) -> dict[str, Any]:
        if cv2 is None:
            return {"status": "unavailable", "reason": "OpenCV is not installed"}
        if self._capture is None:
            return {"status": "closed", "camera_index": self.camera_index}
        return {
            "status": "ok" if self._capture.isOpened() else "closed",
            "camera_index": self.camera_index,
            "provider_id": self.provider_id,
        }
