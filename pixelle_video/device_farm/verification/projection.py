# -*- coding: utf-8 -*-
"""Projection mapping between MS2130 raw frames and phone logical coordinates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectionCalibration:
    """Simple v1 projection calibration using stretch mapping."""

    projection_id: str
    raw_size: tuple[int, int]
    logical_size: tuple[int, int]
    rotation: int = 0
    crop: tuple[int, int, int, int] | None = None
    scale_mode: str = "stretch"

    def logical_to_ratio(self, x: int, y: int) -> tuple[float, float]:
        width, height = self.logical_size
        return (x / width, y / height)

    def raw_to_logical(self, x: int, y: int) -> tuple[int, int]:
        raw_width, raw_height = self.raw_size
        logical_width, logical_height = self.logical_size
        return (
            int(x * logical_width / raw_width),
            int(y * logical_height / raw_height),
        )

    def logical_to_raw(self, x: int, y: int) -> tuple[int, int]:
        raw_width, raw_height = self.raw_size
        logical_width, logical_height = self.logical_size
        return (
            int(x * raw_width / logical_width),
            int(y * raw_height / logical_height),
        )

    def contains_logical_point(self, x: int, y: int) -> bool:
        width, height = self.logical_size
        return 0 <= x < width and 0 <= y < height
