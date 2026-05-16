#!/usr/bin/env python
"""
Cleanup script for the `output/` directory.

Removes per-job subfolders whose last-modified time is older than N days
(default 30). By default runs in DRY-RUN mode and only reports what would
be deleted. Pass `--apply` to actually delete.

Usage:
    python scripts/cleanup_output.py                  # dry-run, 30-day threshold
    python scripts/cleanup_output.py --days 14        # dry-run, 14-day threshold
    python scripts/cleanup_output.py --apply          # actually delete
    python scripts/cleanup_output.py --days 7 --apply # delete folders older than 7d

Top-level loose files in output/ (e.g. *.json manifests) are NOT touched —
this script only removes subdirectories.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR = _PROJECT_ROOT / "output"


def _human_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f}{unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f}PB"


def _folder_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="Age threshold in days (default: 30)")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Override output directory path (default: <project>/output)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else _OUTPUT_DIR
    if not output_dir.is_dir():
        print(f"[ERR] Output directory not found: {output_dir}", file=sys.stderr)
        return 2

    cutoff = time.time() - args.days * 86400
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Scanning {output_dir} for subfolders older than {args.days} days...")

    candidates: list[tuple[Path, float, int]] = []
    for child in output_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError as exc:
            print(f"[WARN] cannot stat {child.name}: {exc}", file=sys.stderr)
            continue
        if mtime < cutoff:
            size = _folder_size(child)
            candidates.append((child, mtime, size))

    if not candidates:
        print("Nothing to clean — all subfolders are within the age threshold.")
        return 0

    candidates.sort(key=lambda t: t[1])  # oldest first
    total_size = sum(c[2] for c in candidates)

    print(f"\nFound {len(candidates)} folder(s) to clean (total {_human_size(total_size)}):\n")
    for path, mtime, size in candidates:
        age_days = (time.time() - mtime) / 86400
        print(f"  [{age_days:5.1f}d] {_human_size(size):>9}  {path.name}")

    if not args.apply:
        print(f"\n[DRY-RUN] No files were deleted. Re-run with --apply to delete.")
        return 0

    print(f"\n[APPLY] Deleting {len(candidates)} folder(s)...")
    deleted = 0
    errors = 0
    for path, _, _ in candidates:
        try:
            shutil.rmtree(path)
            deleted += 1
        except Exception as exc:
            print(f"[ERR] failed to remove {path.name}: {exc}", file=sys.stderr)
            errors += 1

    print(f"\nDone. Deleted: {deleted}  |  Errors: {errors}  |  Freed: {_human_size(total_size)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
