# -*- coding: utf-8 -*-
"""YAML profile loading for MS2130 capture and CH9329 verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .projection import ProjectionCalibration


@dataclass(frozen=True)
class CaptureProfile:
    """Loaded MS2130 capture profile."""

    device_id: str
    provider: str
    camera_index: int
    name_hint: str
    projection: ProjectionCalibration
    ch9329_port: str
    ch9329_baudrate: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class VerificationProfile:
    """Loaded verification rules and bindings."""

    flow_id: str
    defaults: dict[str, Any]
    rules: dict[str, dict[str, Any]]
    bindings: dict[str, dict[str, Any]]
    raw: dict[str, Any]


def _load_yaml(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML profile must be a mapping: {path}")
    return data


def load_capture_profile(path: str | Path) -> CaptureProfile:
    data = _load_yaml(path)
    device = data.get("device", {})
    observation = data.get("observation", {})
    ms2130 = observation.get("ms2130", {})
    expected_raw = ms2130.get("expected_raw_size", {})
    projection_data = data.get("projection", {})
    normalized_size = projection_data.get("normalized_size", device.get("logical_screen", {}))
    ch9329 = data.get("ch9329", {})

    projection = ProjectionCalibration(
        projection_id=str(device["id"]),
        raw_size=(int(expected_raw["width"]), int(expected_raw["height"])),
        logical_size=(int(normalized_size["width"]), int(normalized_size["height"])),
        rotation=int(projection_data.get("rotation", 0)),
        crop=tuple(projection_data["crop"]) if "crop" in projection_data else None,
        scale_mode=str(projection_data.get("scale_mode", "stretch")),
    )

    return CaptureProfile(
        device_id=str(device["id"]),
        provider=str(observation.get("provider", "ms2130_opencv")),
        camera_index=int(ms2130.get("camera_index", 0)),
        name_hint=str(ms2130.get("name_hint", "")),
        projection=projection,
        ch9329_port=str(ch9329.get("port", "COM3")),
        ch9329_baudrate=int(ch9329.get("baudrate", 9600)),
        raw=data,
    )


def load_verification_profile(path: str | Path) -> VerificationProfile:
    data = _load_yaml(path)
    flow = data.get("flow", {})
    return VerificationProfile(
        flow_id=str(flow["id"]),
        defaults=dict(data.get("defaults", {})),
        rules=dict(data.get("rules", {})),
        bindings=dict(data.get("bindings", {})),
        raw=data,
    )
