from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .profiles import RunProfile


@dataclass(frozen=True)
class AppContext:
    profile: RunProfile
    project_root: Path
    data_dir: Path
    output_dir: Path
    user: str = "default"
