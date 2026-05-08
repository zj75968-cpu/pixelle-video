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
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
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

    def __init__(self, serial: str, push_dir: str | None = None, strict_mode: bool | None = None):
        self.serial = serial

        # Load publish config from config_manager; constructor params take precedence
        try:
            from pixelle_video.config import config_manager
            xhs_cfg = config_manager.config.xhs_publish
        except Exception:
            xhs_cfg = None

        if push_dir is not None:
            self.push_dir = push_dir
        else:
            self.push_dir = xhs_cfg.push_dir if xhs_cfg else "/sdcard/DCIM/PixelleVideo"

        if strict_mode is not None:
            self.strict_mode = strict_mode
        else:
            self.strict_mode = xhs_cfg.strict_mode if xhs_cfg is not None else True

        logger.info(
            f"XHSPublisher initialized: serial={serial}, "
            f"strict_mode={self.strict_mode}, push_dir={self.push_dir}"
        )
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

    def _click_text_contains(self, d, *texts: str, timeout: float = 10.0) -> bool:
        """Try clicking an element by textContains (tries each text in order)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in texts:
                el = d(textContains=text)
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

    def _dismiss_blocking_dialogs(self, d):
        """Dismiss known blocking dialogs before entering publish flow."""
        # Draft resume dialog: "继续编辑图文笔记吗？"
        if d(textContains="继续编辑图文笔记").exists(timeout=0.8):
            logger.info("Found draft resume dialog; dismissing it to start fresh publish flow")
            dismissed = (
                self._click_text(d, "存草稿", timeout=2)
                or self._click_desc(d, "关闭", timeout=2)
                or self._click_text(d, "取消", timeout=2)
            )
            if not dismissed:
                # Last safe action: prefer staying on feed by backing out instead of entering editor
                try:
                    d.press("back")
                except Exception:
                    pass
            time.sleep(1)
    def _is_publish_chooser_screen(self, d) -> bool:
        """Best-effort check that we are on XHS creation chooser/camera page."""
        markers = ["图文", "视频", "直播", "拍摄", "相册", "模板", "下一步", "从相册选择", "写文字"]
        for txt in markers:
            if d(text=txt).exists(timeout=0.5) or d(textContains=txt).exists(timeout=0.5):
                return True
        try:
            xml = d.dump_hierarchy()
            return any(m in xml for m in markers)
        except Exception:
            return False

    def _parse_bounds(self, bounds: str) -> Optional[tuple[int, int, int, int]]:
        """Parse Android bounds string like [0,394][354,748]."""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
        if not m:
            return None
        return tuple(int(x) for x in m.groups())

    def _is_album_grid_screen(self, d) -> bool:
        """Detect album picker screen for newer obfuscated XHS builds."""
        if d(text="草稿箱").exists(timeout=0.5) or d(text="全部").exists(timeout=0.5):
            return True
        try:
            xml = d.dump_hierarchy()
            if "草稿箱" in xml and "照片" in xml:
                return True
            root = ET.fromstring(xml)
            large_clickable_images = 0
            for n in root.iter("node"):
                if n.attrib.get("class") != "android.widget.ImageView":
                    continue
                if n.attrib.get("clickable") != "true":
                    continue
                b = self._parse_bounds(n.attrib.get("bounds", ""))
                if not b:
                    continue
                l, t, r, bt = b
                w = r - l
                h = bt - t
                if w >= 250 and h >= 250 and t >= 350:
                    large_clickable_images += 1
            return large_clickable_images >= 6
        except Exception:
            return False

    def _select_images_from_obfuscated_grid(self, d, count: int) -> int:
        """Select images in newer obfuscated album grids by parsing hierarchy nodes."""
        try:
            xml = d.dump_hierarchy()
            root = ET.fromstring(xml)
        except Exception as e:
            logger.warning(f"Failed to parse hierarchy for obfuscated grid: {e}")
            return 0

        candidates: list[tuple[int, int, int, int]] = []
        for n in root.iter("node"):
            if n.attrib.get("class") != "android.widget.ImageView":
                continue
            if n.attrib.get("clickable") != "true":
                continue
            b = self._parse_bounds(n.attrib.get("bounds", ""))
            if not b:
                continue
            l, t, r, bt = b
            w = r - l
            h = bt - t
            # Filter to gallery cells (large tiles in content area)
            if w >= 250 and h >= 250 and t >= 350 and bt <= 2305:
                candidates.append((l, t, r, bt))

        # Stable selection order: top-to-bottom, left-to-right
        candidates.sort(key=lambda it: (it[1], it[0]))
        selected = 0
        for l, t, r, bt in candidates[:count]:
            cx = (l + r) // 2
            cy = (t + bt) // 2
            d.click(cx, cy)
            selected += 1
            time.sleep(0.3)

        logger.info(f"Selected {selected} images via obfuscated-grid strategy")
        return selected

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
        self._dismiss_blocking_dialogs(d)

        # Strict mode: do not use coordinate fallback.
        # If key selectors are missing, fail fast to avoid mis-clicking arbitrary UI.
        published = (
            self._click_resource(d, f"{XHS_PACKAGE}:id/tab_add", timeout=6)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/create", timeout=3)
            or self._click_desc(d, "发布", "加号", "创作", timeout=6)
            or self._click_text(d, "+", "发笔记", "创作", timeout=6)
        )
        if not published:
            self._screenshot(d, "open_publish_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not find the publish (+) button with known selectors; "
                    "strict mode aborted to avoid random taps"
                )
            logger.warning(
                "Could not find publish (+) button; compatible mode: tapping bottom-center tab"
            )
            w, h = self._screen_size(d)
            d.click(w // 2, int(h * 0.972))
        time.sleep(2)
        if not self._is_publish_chooser_screen(d):
            self._screenshot(d, "open_publish_wrong_screen")
            if self.strict_mode:
                raise XHSPublishError(
                    "Tapped publish entry but did not enter creation screen; "
                    "strict mode aborted"
                )
            logger.warning("Did not enter creation screen; compatible mode: continuing anyway")

    def _select_image_text_mode(self, d):
        """Select image-text post type (图文).

        After tapping the publish (+) button, XHS shows a camera/creation page
        with mode tabs at the bottom (e.g. 视频/图文/直播).  The '图文' tab is
        typically the 2nd item from the left.  Fall back to coordinates if the
        text-based approach fails (happens on obfuscated/updated builds).
        """
        # Newer XHS versions show a creation bottom sheet first, with options like:
        # "从相册选择" / "相机" / "写文字".
        # Prefer entering via album option when present.
        clicked = (
            self._click_text(d, "从相册选择", timeout=4)
            or self._click_text_contains(d, "相册选择", timeout=4)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/image_text_tab", timeout=4)
            or self._click_text(d, "图文", timeout=6)
            or self._click_text_contains(d, "图文", timeout=6)
        )
        if not clicked:
            self._screenshot(d, "image_text_mode_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not find 图文 mode tab; strict mode aborted to avoid random taps"
                )
            logger.warning(
                "Could not find 图文 mode tab; compatible mode: tapping left side of screen"
            )
            w, h = self._screen_size(d)
            # 图文 tab is typically the leftmost option in the bottom sheet
            d.click(w // 10, int(h * 0.15))
        time.sleep(1)

    def _select_images_from_album(self, d, count: int):
        """Open album and select the first `count` images."""
        # If we're already in the image picker, skip album entry clicks.
        items = d(resourceId=f"{XHS_PACKAGE}:id/photo_item")
        already_in_album = items.exists(timeout=1.0) or self._is_album_grid_screen(d)
        if not already_in_album:
            # Strict mode: no coordinate fallback for album entry.
            opened = (
                self._click_text(d, "相册", timeout=6)
                or self._click_text_contains(d, "相册", timeout=6)
                or self._click_resource(d, f"{XHS_PACKAGE}:id/album_btn", timeout=4)
            )
            if not opened:
                self._screenshot(d, "open_album_fail")
                if self.strict_mode:
                    raise XHSPublishError(
                        "Could not open album with known selectors; strict mode aborted"
                    )
                logger.warning(
                    "Could not open album with selectors; compatible mode: tapping album area"
                )
                w, h = self._screen_size(d)
                d.click(w // 10, int(h * 0.22))
            time.sleep(2)

        self._grant_permissions(d)
        time.sleep(1)

        # Strategy A: classic resource-id
        items = d(resourceId=f"{XHS_PACKAGE}:id/photo_item")
        selected = 0
        for i in range(min(count, items.count)):
            items[i].click()
            selected += 1
            time.sleep(0.3)

        # Strategy B: obfuscated newer builds
        if selected == 0 and self._is_album_grid_screen(d):
            selected = self._select_images_from_obfuscated_grid(d, count)

        if selected == 0:
            self._screenshot(d, "select_photo_item_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not select images from album grid; strict mode aborted"
                )
            logger.warning(
                "Could not select images from album grid; compatible mode: tapping top-left grid cells"
            )
            w, h = self._screen_size(d)
            # Grid is 3 columns; tap the first `count` cells from top-left
            cell_w = w // 3
            cell_h = cell_w  # square cells
            top_offset = int(h * 0.15)
            for i in range(count):
                col = i % 3
                row = i // 3
                cx = cell_w * col + cell_w // 2
                cy = top_offset + cell_h * row + cell_h // 2
                d.click(cx, cy)
                time.sleep(0.3)
            selected = count

        # Confirm selection — text/resource only in strict mode
        confirmed = (
            self._click_text(d, "下一步", "完成", "确定", timeout=8)
            or self._click_text_contains(d, "下一步", "完成", "确定", timeout=8)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/next_btn", timeout=5)
        )
        if not confirmed:
            self._screenshot(d, "confirm_selection_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not confirm image selection (next_btn/下一步 missing); strict mode aborted"
                )
            logger.warning(
                "Could not confirm selection with selectors; compatible mode: tapping top-right corner"
            )
            w, h = self._screen_size(d)
            d.click(int(w * 0.92), int(h * 0.14))
        time.sleep(2)

    def _ensure_post_edit_screen(self, d):
        """Ensure we're on the text-edit/publish screen, not media-edit screen."""
        # If edit inputs already exist, we're good.
        if d(resourceId=f"{XHS_PACKAGE}:id/title_input").exists(timeout=1) or d(resourceId=f"{XHS_PACKAGE}:id/desc_input").exists(timeout=1):
            return

        # Some XHS versions have a media editor with a bottom-right "下一步" first.
        moved = (
            self._click_text(d, "下一步", timeout=4)
            or self._click_text_contains(d, "下一步", timeout=4)
            or self._click_text(d, "继续", "去发布", timeout=3)
        )
        if moved:
            time.sleep(2)

    def _fill_title_and_body(self, d, title: str, body: str):
        """Fill in title and body text fields."""
        self._ensure_post_edit_screen(d)

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
            if els.count > 1:
                body_el = els[1]
            elif els.count == 1:
                body_el = els[0]
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

    def _screenshot(self, d, tag: str) -> None:
        """Save a debug screenshot with a given tag to the system temp dir."""
        try:
            import tempfile, datetime
            ts = datetime.datetime.now().strftime("%H%M%S")
            path = os.path.join(tempfile.gettempdir(), f"xhs_{tag}_{ts}.png")
            d.screenshot(path)
            logger.debug(f"[screenshot] {tag} → {path}")
        except Exception as e:
            logger.debug(f"[screenshot] {tag} failed (non-fatal): {e}")

    def _publish(self, d):
        """Click the final publish button and wait for the page to leave edit state."""
        self._screenshot(d, "before_publish")
        published = (
            self._click_resource(d, f"{XHS_PACKAGE}:id/publish_btn", timeout=8)
            or self._click_text(d, "发布", "发布笔记", timeout=8)
            or self._click_text_contains(d, "发布", "发布笔记", timeout=8)
            or self._click_desc(d, "发布", "发布笔记", timeout=5)
        )
        if not published:
            self._screenshot(d, "publish_button_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not find publish button (publish_btn/发布); strict mode aborted"
                )
            logger.warning(
                "Could not find publish button; compatible mode: tapping top-right corner"
            )
            w, h = self._screen_size(d)
            d.click(int(w * 0.92), int(h * 0.052))
        # Wait for success indicator or page change (up to 20s)
        self._wait_for_text(d, "发布成功", "笔记已发布", "发布中", "上传中", timeout=20)
        time.sleep(2)
        self._screenshot(d, "after_publish")

    def _check_success(self, d, expected_title: Optional[str] = None) -> bool:
        """Check if publish succeeded by looking for explicit success indicators."""
        # Most reliable: success toast / confirmation text
        if d(text="发布成功").exists(timeout=5):
            logger.info("_check_success: found '发布成功' toast")
            return True
        if d(text="笔记已发布").exists(timeout=5):
            logger.info("_check_success: found '笔记已发布' text")
            return True

        # Newer XHS builds often return directly to feed without toast.
        # Use "expected title + 刚刚" as a strong post-publish signal.
        if expected_title:
            title_probe = expected_title.strip()[:8]
            if title_probe and (
                d(textContains=title_probe).exists(timeout=2)
                or d(text=title_probe).exists(timeout=2)
            ):
                if d(text="刚刚").exists(timeout=2) or d(textContains="刚刚").exists(timeout=2):
                    logger.info("_check_success: found expected title with '刚刚' in feed")
                    return True

        # Strict mode: do not treat "back to home" as success by itself.
        # Home tab visibility is only an indirect signal and can cause false positives.

        # Log current UI state for diagnosis
        try:
            xml = d.dump_hierarchy()
            # Look for any success-related text in the full hierarchy
            for indicator in ["发布成功", "笔记已发布", "发布中", "上传中"]:
                if indicator in xml:
                    logger.info(f"_check_success: found '{indicator}' in UI hierarchy")
                    return indicator in ["发布成功", "笔记已发布"]

            if expected_title:
                title_probe = expected_title.strip()[:8]
                if title_probe and title_probe in xml and "刚刚" in xml:
                    logger.info("_check_success: hierarchy contains expected title + 刚刚")
                    return True

            # Heuristic fallback for obfuscated builds:
            # feed re-opened + just-now marker + like text.
            # Keep this as the last success path to avoid false positives.
            if (
                "刚刚" in xml
                and "赞" in xml
                and ("首页" in xml or "市集" in xml)
            ):
                logger.info("_check_success: heuristic matched (刚刚 + 赞 + feed tabs)")
                return True

            # Check what's currently on screen
            try:
                info = d.info
                logger.warning(f"_check_success: no success indicator found. current activity info: {info}")
            except Exception:
                pass
            # Save a screenshot for manual inspection
            self._screenshot(d, "check_success_fail")
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
            self._screenshot(d, "01_publish_screen")

            # 3. Select image-text mode
            self._select_image_text_mode(d)
            self._screenshot(d, "02_image_text_mode")

            # 4. Select images from gallery
            logger.info(f"[{self.serial}] Selecting {len(images)} images from album")
            self._select_images_from_album(d, len(images))
            self._screenshot(d, "03_images_selected")

            # 5. Fill title and body
            logger.info(f"[{self.serial}] Filling title and body")
            self._fill_title_and_body(d, title, body)
            self._screenshot(d, "04_content_filled")

            # 6. Add hashtags
            if hashtags:
                logger.info(f"[{self.serial}] Adding {len(hashtags)} hashtags")
                self._add_hashtags(d, hashtags)
                self._screenshot(d, "05_hashtags_added")

            # 7. Publish
            logger.info(f"[{self.serial}] Submitting post")
            self._adb_wakeup()  # ensure screen is on before publishing
            self._publish(d)

            # 8. Verify success
            self._adb_wakeup()  # ensure screen is on for success check
            success = self._check_success(d, expected_title=title)
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
