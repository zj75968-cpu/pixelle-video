"""Dry-run smoke test for XHS video publish.

Pushes a tiny mp4 to /sdcard/DCIM/PixelleVideo, opens XHS, navigates to
publish, picks the video, fills title/body, stops short of the final
publish tap. Cleans up the pushed file in finally.

Usage:
  .venv\\Scripts\\python.exe scripts/smoke_publish_video_dryrun.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure adb on PATH
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ["PATH"] = (
    str(ROOT / "packaging" / "windows" / "platform-tools") + os.pathsep + os.environ.get("PATH", "")
)
sys.path.insert(0, str(ROOT))

from pixelle_video.services.xhs_publisher import XHSPublisher, XHSPublishError  # noqa: E402


VIDEO = ROOT / "output" / "20260512_095535_b90f" / "final.mp4"
SERIAL = "KLXDU20611012075"


async def main() -> int:
    if not VIDEO.exists():
        print(f"[skip] sample video missing: {VIDEO}")
        return 2
    publisher = XHSPublisher(serial=SERIAL)
    print(f"[start] dry-run publish_video on {SERIAL} with {VIDEO.name}")
    try:
        ok = await publisher.publish_video(
            video_path=str(VIDEO),
            title="【dry-run测试】夕阳少女",
            body="自动化冒烟测试，请忽略，不会真实发布。",
            hashtags=[],
            dry_run=True,
        )
    except XHSPublishError as exc:
        print(f"[fail] XHSPublishError: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[fail] unexpected: {type(exc).__name__}: {exc}")
        return 1
    print(f"[done] dry_run result: {ok}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
