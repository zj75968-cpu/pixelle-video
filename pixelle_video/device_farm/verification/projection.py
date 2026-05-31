# -*- coding: utf-8 -*-
"""Projection mapping between MS2130 raw frames and phone logical coordinates."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class ProjectionCalibration:
    """Projection calibration using supported crop + stretch mapping."""

    projection_id: str
    raw_size: tuple[int, int]
    logical_size: tuple[int, int]
    rotation: int = 0
    crop: tuple[int, int, int, int] | None = None
    scale_mode: str = "stretch"

    def __post_init__(self) -> None:
        if self.rotation != 0:
            raise ValueError(f"unsupported projection rotation: {self.rotation}")
        if self.scale_mode != "stretch":
            raise ValueError(f"unsupported projection scale_mode: {self.scale_mode}")
        if self.crop is not None:
            x, y, width, height = self.crop
            raw_width, raw_height = self.raw_size
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > raw_width or y + height > raw_height:
                raise ValueError(f"projection crop out of bounds: {self.crop}")

    @property
    def _source_size(self) -> tuple[int, int]:
        if self.crop is None:
            return self.raw_size
        return (self.crop[2], self.crop[3])

    def logical_to_ratio(self, x: int, y: int) -> tuple[float, float]:
        width, height = self.logical_size
        return (x / width, y / height)

    def raw_to_logical(self, x: int, y: int) -> tuple[int, int]:
        offset_x = self.crop[0] if self.crop else 0
        offset_y = self.crop[1] if self.crop else 0
        source_width, source_height = self._source_size
        logical_width, logical_height = self.logical_size
        return (
            int((x - offset_x) * logical_width / source_width),
            int((y - offset_y) * logical_height / source_height),
        )

    def logical_to_raw(self, x: int, y: int) -> tuple[int, int]:
        offset_x = self.crop[0] if self.crop else 0
        offset_y = self.crop[1] if self.crop else 0
        source_width, source_height = self._source_size
        logical_width, logical_height = self.logical_size
        return (
            offset_x + int(x * source_width / logical_width),
            offset_y + int(y * source_height / logical_height),
        )

    def normalize_image(self, image: Image.Image) -> Image.Image:
        if image.size != self.raw_size:
            raise ValueError(f"raw image size {image.size} does not match calibration raw_size {self.raw_size}")
        source = image
        if self.crop is not None:
            x, y, width, height = self.crop
            source = image.crop((x, y, x + width, y + height))
        return source.resize(self.logical_size)

    def contains_logical_point(self, x: int, y: int) -> bool:
        width, height = self.logical_size
        return 0 <= x < width and 0 <= y < height
