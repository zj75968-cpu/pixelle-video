# -*- coding: utf-8 -*-
"""Evidence artifact persistence for verification runs."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PIL import ImageChops

from .models import NormalizedFrame, VerificationResult


class EvidenceStore:
    """Save before/after/diff/result evidence for one verification step."""

    def __init__(self, root_dir: str | Path = "runtime/verification"):
        self.root_dir = Path(root_dir)

    def save(
        self,
        device_id: str,
        run_id: str,
        step_id: str,
        before: NormalizedFrame,
        after: NormalizedFrame,
        result: VerificationResult,
    ) -> dict[str, str]:
        step_dir = self.root_dir / device_id / run_id / step_id
        step_dir.mkdir(parents=True, exist_ok=True)

        before_path = step_dir / "before.png"
        after_path = step_dir / "after.png"
        diff_path = step_dir / "diff.png"
        result_path = step_dir / "result.json"

        before.image.save(before_path)
        after.image.save(after_path)
        ImageChops.difference(before.image.convert("RGB"), after.image.convert("RGB")).save(diff_path)

        data = asdict(result)
        data["status"] = result.status.value
        result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "before": str(before_path),
            "after": str(after_path),
            "diff": str(diff_path),
            "result": str(result_path),
        }
