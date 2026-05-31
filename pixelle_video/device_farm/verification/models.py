# -*- coding: utf-8 -*-
"""Shared data models for CH9329 + MS2130 verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """Structured verification status consumed by UI and pipelines."""

    PASS = "PASS"
    UNKNOWN = "UNKNOWN"
    RETRYABLE_FAIL = "RETRYABLE_FAIL"
    RECOVERABLE_FAIL = "RECOVERABLE_FAIL"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    HARD_FAIL = "HARD_FAIL"


@dataclass(frozen=True)
class CaptureMetadata:
    """Metadata reported by a frame provider."""

    provider: str
    provider_id: str
    raw_size: tuple[int, int]
    fps: float | None = None
    latency_ms: float | None = None
    frame_age_ms: float | None = None
    health: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedFrame:
    """A frame normalized into the configured phone logical coordinate space."""

    image: Any
    timestamp: float
    raw_size: tuple[int, int]
    logical_size: tuple[int, int]
    provider_id: str
    projection_id: str
    quality_flags: list[str] = field(default_factory=list)
    metadata: CaptureMetadata | None = None

    @property
    def logical_width(self) -> int:
        return self.logical_size[0]

    @property
    def logical_height(self) -> int:
        return self.logical_size[1]


@dataclass(frozen=True)
class ActionMetadata:
    """Description of one CH9329 physical action being verified."""

    action_type: str
    point_name: str | None = None
    x: int | None = None
    y: int | None = None
    x_ratio: float | None = None
    y_ratio: float | None = None
    risk: str = "safe"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Result returned by rule evaluation or action verification."""

    status: VerificationStatus
    confidence: float
    reason: str
    matched_rules: list[str] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
