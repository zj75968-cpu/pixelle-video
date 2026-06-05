from __future__ import annotations

from pathlib import Path

# templates live at content_factory/domain/automation/templates/<platform>/<name>.png
TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


def resolve_template(ref: str | None, root: Path | None = None) -> Path | None:
    """Resolve a "<platform>/<name>" template reference to an existing file path.

    Returns None when ref is empty or the file does not exist, so callers can
    apply the degrade-to-pass / template_missing semantics uniformly.
    """
    if not ref:
        return None
    base = root or TEMPLATES_ROOT
    name = ref if ref.endswith(".png") else f"{ref}.png"
    path = base / name
    return path if path.exists() else None
