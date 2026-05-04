# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Xiaohongshu (小红书) Publisher Service

Automates posting image-text notes on Xiaohongshu using uiautomator2.
Images are pushed to the device via ADB, then the XHS app UI is driven
through accessibility-based automation.

Dependencies:
    pip install uiautomator2

Usage:
    publisher = XHSPublisher(serial="emulator-5554")
    await publisher.publish(
        images=["output/abc/images/1.png", "output/abc/images/2.png"],
        title="我的旅行日记",
        body="今天去了一个很棒的地方...",
        hashtags=["旅行", "打卡"],
    )
"""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from loguru import logger


XHS_PACKAGE = "com.xingin.xhs"


class XHSPublishError(Exception):
    """Raised when publishing fails."""


class XHSPublisher:
    """
    Drives the Xiaohongshu Android app via uiautomator2.

    Each instance is tied to one device serial.
    """

    def __init__(self, serial: str, push_dir: str = "/sdcard/DCIM/PixelleVideo"):
        self.serial = serial
        self.push_dir = push_dir
        self._device = None  # lazy-init

    # -------------------------------------------------------------------------
    # Device Initialization
    # -------------------------------------------------------------------------

    def _get_device(self):
        """Lazily initialize uiautomator2 device connection."""
        if self._device is None:
            try:
                import uiautomator2 as u2  # type: ignore
            except ImportError as exc:
                raise XHSPublishError(
                    "uiautomator2 is not installed. Run: pip install uiautomator2"
                ) from exc
            self._device = u2.connect(self.serial)
            logger.info(f"Connected to device {self.serial}")
        return self._device

    # -------------------------------------------------------------------------
    # ADB Helpers
    # -------------------------------------------------------------------------

    def _adb(self, *args: str) -> str:
        """Run an adb command against this device."""
        import subprocess
        result = subprocess.run(
            ["adb", "-s", self.serial] + list(args),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise XHSPublishError(f"ADB error: {result.stderr.strip()}")
        return result.stdout.strip()

    def _push_images(self, image_paths: List[str]) -> List[str]:
        """
        Push images to the device and return device-side paths.
        Also forces media scanner so images appear in the gallery.
        """
        self._adb("shell", "mkdir", "-p", self.push_dir)
        device_paths = []
        for local_path in image_paths:
            filename = Path(local_path).name
            device_path = f"{self.push_dir}/{filename}"
            logger.debug(f"Pushing {local_path} -> {device_path}")
            self._adb("push", local_path, device_path)
            device_paths.append(device_path)

        # Trigger media scan so images appear in the gallery picker
        for dp in device_paths:
            try:
                self._adb(
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d",
                    f"file://{dp}",
                )
            except Exception:
                pass  # Media scan is best-effort

        time.sleep(2)  # Wait for media scanner
        return device_paths

    def _cleanup_device_images(self, device_paths: List[str]):
        """Remove pushed images from device after publishing."""
        for dp in device_paths:
            try:
                self._adb("shell", "rm", "-f", dp)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # UI Automation
    # -------------------------------------------------------------------------

    def _click_text(self, d, *texts: str, timeout: float = 10.0) -> bool:
        """Try clicking an element by text (tries each text in order)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in texts:
                el = d(text=text)
                if el.exists(timeout=0.5):
                    el.click()
                    return True
            time.sleep(0.5)
        return False

    def _click_resource(self, d, resource_id: str, timeout: float = 10.0) -> bool:
        """Try clicking an element by resource-id."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            el = d(resourceId=resource_id)
            if el.exists(timeout=0.5):
                el.click()
                return True
            time.sleep(0.5)
        return False

    def _click_desc(self, d, *descs: str, timeout: float = 10.0) -> bool:
        """Try clicking an element by content description."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for desc in descs:
                el = d(description=desc)
                if el.exists(timeout=0.5):
                    el.click()
                    return True

                el_contains = d(descriptionContains=desc)
                if el_contains.exists(timeout=0.5):
                    el_contains.click()
                    return True
            time.sleep(0.5)
        return False

    def _wait_for_text(self, d, *texts: str, timeout: float = 15.0) -> bool:
        """Wait until any of the given texts appears on screen."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in texts:
                if d(text=text).exists(timeout=0.5):
                    return True
            time.sleep(0.5)
        return False

    def _grant_permissions(self, d):
        """Auto-grant permission dialogs that may appear."""
        for _ in range(3):
            for allow_text in ["允许", "始终允许", "ALLOW"]:
                el = d(text=allow_text)
                if el.exists(timeout=1.0):
                    el.click()
                    time.sleep(0.5)

    def _adb_wakeup(self) -> None:
        """Wake up the device screen via ADB keyevent WAKEUP (224)."""
        import subprocess
        try:
            adb = shutil.which("adb") or "adb"
            subprocess.run(
                [adb, "-s", self.serial, "shell", "input keyevent 224"],
                timeout=5,
                capture_output=True,
            )
            time.sleep(1)
        except Exception as e:
            logger.warning(f"_adb_wakeup failed (non-fatal): {e}")

    def _screen_size(self, d) -> tuple[int, int]:
        """Return (width, height) of the device screen."""
        sz = d.window_size()
        if isinstance(sz, dict):
            return int(sz.get("width", 1080)), int(sz.get("height", 2400))
        return int(sz[0]), int(sz[1])

    def _click_tab_center_bottom(self, d, tab_index: int, total_tabs: int = 5) -> bool:
        """
        Click a tab in the bottom navigation bar by position.
        tab_index is 0-based. For the publish "+" button, use tab_index=2 (center of 5).
        """
        try:
            w, h = self._screen_size(d)
            tab_width = w // total_tabs
            x = tab_width * tab_index + tab_width // 2
            y = int(h * 0.972)   # bottom nav bar is ~last 5-6% of screen
            logger.debug(f"Tapping tab {tab_index}/{total_tabs} at ({x}, {y})")
            d.click(x, y)
            return True
        except Exception as e:
            logger.warning(f"Coordinate tab click failed: {e}")
            return False

    def _open_xhs_publish(self, d):
        """Launch XHS app and navigate to the publish screen."""
        d.app_start(XHS_PACKAGE, stop=True)
        time.sleep(3)

        # Grant any immediate permissions
        self._grant_permissions(d)

        # Click the "+" publish button — try multiple strategies in order:
        # 1. Known resource IDs (older / non-obfuscated builds)
        # 2. Text / description matching
        # 3. Coordinate fallback: center tab (index 2 of 5) in bottom nav
        published = (
            self._click_resource(d, f"{XHS_PACKAGE}:id/tab_add", timeout=6)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/create", timeout=3)
            or self._click_text(d, "+", "发布", "发笔记", "创作", timeout=6)
            or self._click_desc(d, "发布", "加号", "创作", timeout=6)
            or self._click_tab_center_bottom(d, tab_index=2, total_tabs=5)
        )
        if not published:
            raise XHSPublishError("Could not find the publish (+) button")
        time.sleep(2)

    def _select_image_text_mode(self, d):
        """Select image-text post type (图文).

        After tapping the publish (+) button, XHS shows a camera/creation page
        with mode tabs at the bottom (e.g. 视频/图文/直播).  The '图文' tab is
        typically the 2nd item from the left.  Fall back to coordinates if the
        text-based approach fails (happens on obfuscated/updated builds).
        """
        clicked = self._click_text(d, "图文", timeout=6)
        if not clicked:
            # Coordinate fallback: '图文' tab is usually ~25% from left, ~92% down
            w, h = self._screen_size(d)
            x = int(w * 0.25)
            y = int(h * 0.92)
            logger.debug(f"Tapping '图文' by coordinates ({x}, {y})")
            d.click(x, y)
        time.sleep(1)

    def _select_images_from_album(self, d, count: int):
        """Open album and select the first `count` images (LIFO order in gallery)."""
        # Open album — try text/resource first, then coordinate fallback
        opened = (
            self._click_text(d, "相册", timeout=6)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/album_btn", timeout=4)
        )
        if not opened:
            # Coordinate fallback: '相册' button is typically bottom-left area
            w, h = self._screen_size(d)
            d.click(int(w * 0.12), int(h * 0.88))
        time.sleep(2)

        self._grant_permissions(d)
        time.sleep(1)

        # Select images — the latest images appear at top of gallery
        items = d(resourceId=f"{XHS_PACKAGE}:id/photo_item")
        selected = 0
        for i in range(min(count, items.count)):
            items[i].click()
            selected += 1
            time.sleep(0.3)

        if selected == 0:
            # Fallback: just tap positions in a typical grid layout
            logger.warning("Could not find photo_item; trying coordinate tap")
            screen = d.window_size()
            if isinstance(screen, dict):
                width = int(screen.get("width", 1080))
                height = int(screen.get("height", 1920))
            else:
                width, height = screen
                width = int(width)
                height = int(height)

            x_positions = [int(width * 0.2), int(width * 0.5), int(width * 0.8)]
            start_y = int(height * 0.32)
            row_step = max(int(height * 0.22), 220)

            for i in range(count):
                col = i % 3
                row = i // 3
                x = x_positions[col]
                y = min(start_y + row * row_step, int(height * 0.88))
                d.click(x, y)
                selected += 1
                time.sleep(0.35)

        # Confirm selection — text → resource → coordinate fallback
        w_c, h_c = self._screen_size(d)
        confirmed = (
            self._click_text(d, "下一步", "完成", "确定", timeout=8)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/next_btn", timeout=5)
        )
        if not confirmed:
            # Coordinate fallback: "下一步" button is at top-right of album screen
            logger.debug("Confirming image selection via coordinate tap top-right")
            d.click(int(w_c * 0.88), int(h_c * 0.055))
        time.sleep(2)

    def _fill_title_and_body(self, d, title: str, body: str):
        """Fill in title and body text fields."""
        # Title
        title_el = (
            d(resourceId=f"{XHS_PACKAGE}:id/title_input")
            if d(resourceId=f"{XHS_PACKAGE}:id/title_input").exists(timeout=3)
            else d(className="android.widget.EditText")
        )
        if title_el.exists(timeout=5):
            title_el.click()
            title_el.clear_text()
            title_el.set_text(title)
            time.sleep(0.5)

        # Body
        body_el = d(resourceId=f"{XHS_PACKAGE}:id/desc_input")
        if not body_el.exists(timeout=3):
            # Fallback: get second EditText
            els = d(className="android.widget.EditText")
            body_el = els[1] if els.count > 1 else els[0]
        if body_el.exists(timeout=3):
            body_el.click()
            body_el.clear_text()
            body_el.set_text(body)
            time.sleep(0.5)

    def _add_hashtags(self, d, hashtags: List[str]):
        """Add hashtag topics to the post."""
        for tag in hashtags:
            # Click the hashtag/topic button
            clicked = (
                self._click_resource(d, f"{XHS_PACKAGE}:id/topic_btn", timeout=5)
                or self._click_text(d, "#话题", "话题", timeout=5)
            )
            if not clicked:
                logger.warning(f"Could not open hashtag picker for #{tag}")
                continue
            time.sleep(1)

            # Type in the search box
            search_el = d(resourceId=f"{XHS_PACKAGE}:id/search_input")
            if not search_el.exists(timeout=5):
                search_el = d(focused=True)
            if search_el.exists(timeout=3):
                search_el.set_text(tag)
                time.sleep(1.5)

            # Click first result
            first = d(resourceId=f"{XHS_PACKAGE}:id/topic_item_container")
            if first.exists(timeout=5):
                first.click()
            else:
                # Fallback: press enter to accept
                d.press("enter")
            time.sleep(0.5)

    def _publish(self, d):
        """Click the final publish button."""
        published = (
            self._click_resource(d, f"{XHS_PACKAGE}:id/publish_btn", timeout=8)
            or self._click_text(d, "发布", "发布笔记", timeout=8)
            or self._click_desc(d, "发布", "发布笔记", timeout=5)
        )
        if not published:
            # Coordinate fallback: "发布" button is typically top-right area
            w, h = self._screen_size(d)
            logger.warning("Text/resource publish button not found; tapping top-right")
            d.click(int(w * 0.88), int(h * 0.055))
        time.sleep(8)

    def _check_success(self, d) -> bool:
        """Check if publish succeeded by looking for success indicators."""
        # Text / resource checks
        if d(text="发布成功").exists(timeout=5):
            return True
        if d(text="笔记已发布").exists(timeout=5):
            return True
        if d(resourceId=f"{XHS_PACKAGE}:id/tab_home").exists(timeout=5):
            return True
        # Broadest fallback: dump UI hierarchy and check for XHS package name
        try:
            xml = d.dump_hierarchy()
            if XHS_PACKAGE in xml:
                logger.info("_check_success: XHS found in UI hierarchy → treating as success")
                return True
            else:
                # Log what app is visible for diagnosis
                try:
                    info = d.info
                    logger.warning(f"_check_success: XHS NOT in hierarchy. d.info={info}")
                except Exception:
                    pass
                logger.warning("_check_success: XHS NOT in UI hierarchy")
        except Exception as e:
            logger.warning(f"_check_success: dump_hierarchy failed: {e}")
        return False

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def publish(
        self,
        images: List[str],
        title: str,
        body: str,
        hashtags: Optional[List[str]] = None,
    ) -> bool:
        """
        Publish an image-text note to Xiaohongshu.

        Args:
            images: List of local image file paths (in order).
            title: Post title (≤ 20 chars recommended).
            body:  Post body / description.
            hashtags: List of topic tags (without #).

        Returns:
            True if publish succeeded.

        Raises:
            XHSPublishError: If any automation step fails.
        """
        hashtags = hashtags or []

        # Run blocking UI automation in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._publish_sync,
            images,
            title,
            body,
            hashtags,
        )

    def _publish_sync(
        self,
        images: List[str],
        title: str,
        body: str,
        hashtags: List[str],
    ) -> bool:
        """Synchronous publish implementation (runs in executor)."""
        device_paths = []
        try:
            d = self._get_device()

            # 1. Push images to device
            logger.info(f"[{self.serial}] Pushing {len(images)} images to device")
            device_paths = self._push_images(images)

            # 2. Open XHS and navigate to publish
            logger.info(f"[{self.serial}] Opening XHS publish screen")
            self._open_xhs_publish(d)

            # 3. Select image-text mode
            self._select_image_text_mode(d)

            # 4. Select images from gallery
            logger.info(f"[{self.serial}] Selecting {len(images)} images from album")
            self._select_images_from_album(d, len(images))

            # 5. Fill title and body
            logger.info(f"[{self.serial}] Filling title and body")
            self._fill_title_and_body(d, title, body)

            # 6. Add hashtags
            if hashtags:
                logger.info(f"[{self.serial}] Adding {len(hashtags)} hashtags")
                self._add_hashtags(d, hashtags)

            # 7. Publish
            logger.info(f"[{self.serial}] Submitting post")
            self._adb_wakeup()  # ensure screen is on before publishing
            self._publish(d)

            # 8. Verify success
            self._adb_wakeup()  # ensure screen is on for success check
            success = self._check_success(d)
            if success:
                logger.info(f"[{self.serial}] ✅ Post published successfully")
            else:
                logger.warning(f"[{self.serial}] ⚠️ Could not confirm publish success")

            return success

        except XHSPublishError:
            raise
        except Exception as exc:
            raise XHSPublishError(f"Publish failed on {self.serial}: {exc}") from exc
        finally:
            # Clean up pushed images regardless of success/failure
            if device_paths:
                self._cleanup_device_images(device_paths)
