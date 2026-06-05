from __future__ import annotations

from content_factory.domain.automation.vision.templates import resolve_template


def test_resolve_returns_none_for_empty():
    assert resolve_template(None) is None
    assert resolve_template("") is None


def test_resolve_existing_template(tmp_path):
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    target = root / "xhs" / "album_tab.png"
    target.write_bytes(b"x")
    # both "xhs/album_tab" and "xhs/album_tab.png" resolve to the same file
    assert resolve_template("xhs/album_tab", root=root) == target
    assert resolve_template("xhs/album_tab.png", root=root) == target


def test_resolve_missing_returns_none(tmp_path):
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    assert resolve_template("xhs/nope", root=root) is None
