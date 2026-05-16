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

    def __init__(self, serial: str, push_dir: str | None = None, strict_mode: bool | None = None, job_id: str | None = None):
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

        self.lock_pin: str = xhs_cfg.lock_pin if xhs_cfg and hasattr(xhs_cfg, "lock_pin") else ""
        self.job_id: Optional[str] = job_id
        self.screenshots: List[str] = []  # paths of all screenshots taken in this session

        # Load UI selectors from config/xhs_ui_selectors.yaml (allows operator-level tuning)
        self._selectors: dict = self._load_selectors()

        logger.info(
            f"XHSPublisher initialized: serial={serial}, "
            f"strict_mode={self.strict_mode}, push_dir={self.push_dir}"
        )
        self._device = None  # lazy-init

    # -------------------------------------------------------------------------
    # Device Initialization
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_selectors() -> dict:
        """Load UI selectors from config/xhs_ui_selectors.yaml.

        Returns an empty dict if the file is missing or unreadable.
        Each value is a dict with optional keys: resource_id, text, description, fallback_texts.
        """
        yaml_path = Path(__file__).resolve().parent.parent.parent / "config" / "xhs_ui_selectors.yaml"
        try:
            import yaml  # pyyaml is in requirements
            with open(yaml_path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except FileNotFoundError:
            logger.debug("xhs_ui_selectors.yaml not found, using hardcoded fallbacks")
        except Exception as exc:
            logger.warning(f"Could not load xhs_ui_selectors.yaml: {exc}")
        return {}

    def _click_by_selector_key(
        self,
        d,
        key: str,
        timeout: float = 10.0,
        scroll_to_find: bool = False,
    ) -> bool:
        """Try clicking an element by a named selector key from xhs_ui_selectors.yaml.

        Strategy order: resource_id → text (exact) → text (contains) → description →
                        description (contains) → fallback_texts (exact + contains).
        If scroll_to_find is True (or YAML entry has scroll_to_find: true), after the
        initial timeout the method performs two gentle swipes (up then down) and
        retries each strategy once before giving up.
        Returns True on first successful click, False otherwise.
        On failure, saves a debug screenshot to output/xhs_debug_<key>_<ts>.png.
        """
        sel = self._selectors.get(key, {})
        if not sel:
            return False

        rid = sel.get("resource_id")
        text = sel.get("text")
        desc = sel.get("description")
        fallback_texts: list = sel.get("fallback_texts") or []
        _scroll = scroll_to_find or bool(sel.get("scroll_to_find", False))

        def _try_once() -> bool:
            if rid:
                el = d(resourceId=rid)
                if el.exists(timeout=0.5):
                    el.click()
                    return True
            if text:
                el = d(text=text)
                if el.exists(timeout=0.5):
                    el.click()
                    return True
                # Contains fallback for minor text changes
                el = d(textContains=text)
                if el.exists(timeout=0.3):
                    el.click()
                    return True
            if desc:
                el = d(description=desc)
                if el.exists(timeout=0.5):
                    el.click()
                    return True
                el = d(descriptionContains=desc)
                if el.exists(timeout=0.3):
                    el.click()
                    return True
            for ft in fallback_texts:
                el = d(text=ft)
                if el.exists(timeout=0.3):
                    el.click()
                    return True
                el = d(textContains=ft)
                if el.exists(timeout=0.3):
                    el.click()
                    return True
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _try_once():
                return True
            time.sleep(0.5)

        # Scroll-and-retry: gentle swipe up then down, try once each
        if _scroll:
            for _direction in ("up", "down"):
                try:
                    d.swipe_ext(_direction, scale=0.4)
                    time.sleep(0.5)
                except Exception:  # noqa: BLE001
                    pass
                if _try_once():
                    return True

        # Save debug screenshot on failure via instance method (tracks path in self.screenshots)
        self._screenshot(d, f"selector_{key}_fail")

        return False

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

    @staticmethod
    def _resolve_adb() -> str:
        """Return the path to adb, preferring project-local copy over PATH."""
        import shutil as _shutil
        adb_in_path = _shutil.which("adb")
        if adb_in_path:
            return adb_in_path
        # Try project-local platform-tools (same search as DeviceManager)
        _project_local = (
            Path(__file__).resolve().parent.parent.parent
            / "packaging" / "windows" / "platform-tools" / "adb.exe"
        )
        if _project_local.exists():
            return str(_project_local)
        return "adb"  # fallback – will raise [WinError 2] if missing

    def _adb(self, *args: str) -> str:
        """Run an adb command against this device."""
        import subprocess
        result = subprocess.run(
            [self._resolve_adb(), "-s", self.serial] + list(args),
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

    def _push_video(self, video_path: str) -> str:
        """Push a single video file to the device and trigger media scan."""
        self._adb("shell", "mkdir", "-p", self.push_dir)
        filename = Path(video_path).name
        device_path = f"{self.push_dir}/{filename}"
        logger.debug(f"Pushing video {video_path} -> {device_path}")
        self._adb("push", video_path, device_path)
        # Trigger media scan so video appears in the gallery picker
        try:
            self._adb(
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{device_path}",
            )
        except Exception:
            pass
        time.sleep(3)  # Videos may take a moment longer to be indexed
        return device_path

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
            adb = self._resolve_adb()
            subprocess.run(
                [adb, "-s", self.serial, "shell", "input keyevent 224"],
                timeout=5,
                capture_output=True,
            )
            time.sleep(1)
        except Exception as e:
            logger.warning(f"_adb_wakeup failed (non-fatal): {e}")

    def _get_screen_timeout(self) -> int:
        """Return current screen_off_timeout in ms (default 30000 on error)."""
        import subprocess
        try:
            adb = self._resolve_adb()
            r = subprocess.run(
                [adb, "-s", self.serial, "shell", "settings get system screen_off_timeout"],
                timeout=5, capture_output=True, text=True,
            )
            return int(r.stdout.strip())
        except Exception:
            return 30000

    def _set_screen_timeout(self, ms: int) -> None:
        """Set screen_off_timeout in ms via ADB settings."""
        import subprocess
        try:
            adb = self._resolve_adb()
            subprocess.run(
                [adb, "-s", self.serial, "shell", f"settings put system screen_off_timeout {ms}"],
                timeout=5, capture_output=True,
            )
            logger.debug(f"[{self.serial}] screen_off_timeout set to {ms} ms")
        except Exception as e:
            logger.warning(f"_set_screen_timeout failed (non-fatal): {e}")

    def _unlock_screen(self) -> None:
        """Wake up and unlock the device screen.

        Always safe to call. Works for no-password (sleep-only) phones:
        1. Check if screen is already awake — skip entirely if so.
        2. Send WAKEUP keyevent.
        3. Swipe up from the bottom third of the screen.
        4. Send KEYCODE_MENU (82) as backup dismiss (works on Huawei/HarmonyOS).
        5. Enter PIN digits if ``lock_pin`` is configured.
        """
        import subprocess
        adb = self._resolve_adb()

        def _run(*args: str) -> None:
            subprocess.run(
                [adb, "-s", self.serial, "shell"] + list(args),
                timeout=5, capture_output=True,
            )

        def _adb_output(*args: str) -> str:
            r = subprocess.run(
                [adb, "-s", self.serial, "shell"] + list(args),
                timeout=5, capture_output=True, text=True,
            )
            return r.stdout

        try:
            # 0. Check if keyguard (lock screen) is active via window manager.
            #    mState=ON can be true on the lock screen, so we MUST check keyguard separately.
            km_output = _adb_output("dumpsys", "window")
            is_locked = (
                "isKeyguardShowing=true" in km_output
                or "mKeyguardShowing=true" in km_output
                or "mShowingLockscreen=true" in km_output
            )
            display_state = _adb_output("dumpsys", "display")
            screen_on = "mState=ON" in display_state or "mState=2" in display_state or "state=ON" in display_state

            if screen_on and not is_locked:
                logger.info(f"[{self.serial}] Screen on and unlocked, skipping unlock")
                return

            # 1. Wake up screen: WAKEUP keyevent first, then check display
            _run("input", "keyevent", "224")
            time.sleep(1.0)
            # Re-check: if still off, use POWER toggle once
            display_state2 = _adb_output("dumpsys", "display")
            if "mState=ON" not in display_state2 and "mState=2" not in display_state2 and "state=ON" not in display_state2:
                _run("input", "keyevent", "26")  # POWER toggle ON
                time.sleep(1.0)

            # 2. Get screen dimensions
            size_out = _adb_output("wm", "size")
            try:
                parts = size_out.strip().split()[-1].split("x")
                sw, sh = int(parts[0]), int(parts[1])
            except Exception:
                sw, sh = 1080, 2340

            # 3. Swipe up from bottom third (300 ms — avoids long-press misread)
            mid_x = sw // 2
            _run("input", "swipe",
                 str(mid_x), str(int(sh * 0.85)),
                 str(mid_x), str(int(sh * 0.15)),
                 "300")
            time.sleep(0.8)

            # 4. KEYCODE_MENU (82) — backup dismiss for Huawei/HarmonyOS no-PIN lock
            _run("input", "keyevent", "82")
            time.sleep(0.5)

            # 5. Enter PIN if configured
            if self.lock_pin:
                _run("input", "text", self.lock_pin)
                time.sleep(0.3)
                _run("input", "keyevent", "66")  # ENTER
                time.sleep(1)
                logger.info(f"[{self.serial}] Screen unlocked with PIN")
            else:
                logger.info(f"[{self.serial}] Screen woken and unlocked (no PIN)")
        except Exception as e:
            logger.warning(f"_unlock_screen failed (non-fatal): {e}")

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
        self._adb_wakeup()  # 确保 app 启动后屏幕仍亮着

        # 并联短超时：所有 selector 在同一轮内快速轮询，总耗时 ≤ 8s
        def _try_publish_btn(timeout=8.0) -> bool:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._click_by_selector_key(d, "nav_publish", timeout=0.5):
                    return True
                if self._click_resource(d, f"{XHS_PACKAGE}:id/tab_add", timeout=0.5):
                    return True
                if self._click_resource(d, f"{XHS_PACKAGE}:id/create", timeout=0.5):
                    return True
                if self._click_desc(d, "发布", "加号", "创作", timeout=0.5):
                    return True
                if self._click_text(d, "+", "发笔记", "创作", timeout=0.5):
                    return True
                time.sleep(0.3)
            return False

        published = _try_publish_btn(timeout=8)
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
        self._adb_wakeup()  # 防止屏幕在 selector 逐一尝试期间熟眠
        if not self._is_publish_chooser_screen(d):
            self._screenshot(d, "open_publish_wrong_screen")
            if self.strict_mode:
                raise XHSPublishError(
                    "Tapped publish entry but did not enter creation screen; "
                    "strict mode aborted"
                )
            logger.warning("Did not enter creation screen; compatible mode: continuing anyway")


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
            self._click_by_selector_key(d, "post_type_image_text", timeout=4)
            or self._click_text(d, "从相册选择", timeout=4)
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
                self._click_by_selector_key(d, "album_button", timeout=4)
                or self._click_text(d, "相册", timeout=6)
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
        """Save a debug screenshot.

        If job_id is set, saves to output/<job_id>/screenshots/; otherwise falls back
        to the system temp directory.  The path is appended to self.screenshots.
        """
        try:
            import datetime as _dt
            ts = _dt.datetime.now().strftime("%H%M%S")
            filename = f"xhs_{tag}_{ts}.png"
            if self.job_id:
                _out_dir = (
                    Path(__file__).resolve().parent.parent.parent
                    / "output" / self.job_id / "screenshots"
                )
                _out_dir.mkdir(parents=True, exist_ok=True)
                path = str(_out_dir / filename)
            else:
                import tempfile
                path = os.path.join(tempfile.gettempdir(), filename)
            d.screenshot(path)
            self.screenshots.append(path)
            logger.debug(f"[screenshot] {tag} → {path}")
        except Exception as e:
            logger.debug(f"[screenshot] {tag} failed (non-fatal): {e}")

    def _publish(self, d):
        """Click the final publish button and wait for the page to leave edit state."""
        self._screenshot(d, "before_publish")
        published = (
            self._click_by_selector_key(d, "publish_confirm_button", timeout=8)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/publish_btn", timeout=8)
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
        """Check if publish succeeded by looking for explicit success indicators.

        Tiered approach:
          Tier 1 — definitive: "发布成功" / "笔记已发布" toast (2 s timeout).
          Tier 2 — in-progress wait: if "发布中"/"上传中" detected, poll up to
                   60 s for the upload to finish before moving on.
          Tier 3 — strong: expected_title[:10] + "刚刚" both visible in feed.
          Tier 4 — negative gate: title/body input still visible → still editing.
          Tier 5 — hierarchy scan: full XML dump for tier-1/3 signals.
          Tier 6 — weak heuristic: 刚刚 + 赞 + feed tab (last resort, logged
                   as warning to flag potential false positives).
        """
        # Tier 1: definitive success toasts (2 s each — toasts are brief)
        for _t1 in ("发布成功", "笔记已发布"):
            if d(text=_t1).exists(timeout=2):
                logger.info(f"_check_success: ✅ tier-1 '{_t1}'")
                return True

        # Tier 2: if still uploading/publishing, wait for completion
        # (video uploads can take 30-60 s after the publish tap)
        _upload_phrases = ("发布中", "上传中", "正在发布", "视频上传中")
        _waiting = any(d(textContains=_p).exists(timeout=0.5) for _p in _upload_phrases)
        if _waiting:
            logger.info("_check_success: upload/publish in progress — polling up to 60 s…")
            for _ in range(60):
                time.sleep(1)
                # Re-check tier-1
                for _t1 in ("发布成功", "笔记已发布"):
                    if d(text=_t1).exists(timeout=0.5):
                        logger.info(f"_check_success: ✅ tier-1 '{_t1}' after upload wait")
                        return True
                # Still uploading?
                if not any(d(textContains=_p).exists(timeout=0.5) for _p in _upload_phrases):
                    break  # upload finished — fall through to other tiers

        # Tier 4 (negative gate): still on the edit screen → publish not finished
        _still_editing = (
            d(resourceId=f"{XHS_PACKAGE}:id/title_input").exists(timeout=1)
            or d(resourceId=f"{XHS_PACKAGE}:id/desc_input").exists(timeout=1)
        )
        if _still_editing:
            logger.warning("_check_success: ❌ still on edit page after publish call")
            self._screenshot(d, "check_success_still_editing")
            return False

        # Tier 3: expected title visible in feed alongside "刚刚"
        # Use ≥10 chars for better disambiguation vs. other posts.
        if expected_title:
            _probe = expected_title.strip()[:10]
            if _probe:
                _title_visible = (
                    d(textContains=_probe).exists(timeout=2)
                    or d(descriptionContains=_probe).exists(timeout=1)
                )
                _just_now = (
                    d(text="刚刚").exists(timeout=1)
                    or d(textContains="刚刚").exists(timeout=1)
                )
                if _title_visible and _just_now:
                    logger.info(f"_check_success: ✅ tier-3 title '{_probe}' + '刚刚'")
                    return True

        # Tier 5: full hierarchy scan for tier-1 / tier-3 signals
        try:
            xml = d.dump_hierarchy()

            # Tier-1 in XML
            for _t1 in ("发布成功", "笔记已发布"):
                if _t1 in xml:
                    logger.info(f"_check_success: ✅ tier-1 in XML '{_t1}'")
                    return True

            # Note "发布中"/"上传中" still in XML after wait = unconfirmed (not success)
            for _p in ("发布中", "上传中"):
                if _p in xml:
                    logger.warning(f"_check_success: '{_p}' still in XML — treating as unconfirmed")
                    break

            # Tier-3 in XML
            if expected_title:
                _probe = expected_title.strip()[:10]
                if _probe and _probe in xml and "刚刚" in xml:
                    logger.info("_check_success: ✅ tier-3 in XML (title + 刚刚)")
                    return True

            # Tier 6: weak heuristic — feed-like state without title verification
            if "刚刚" in xml and "赞" in xml and ("首页" in xml or "市集" in xml):
                logger.warning(
                    "_check_success: ⚠️ tier-6 weak heuristic (刚刚 + 赞 + feed) — "
                    "possible false positive if title could not be verified"
                )
                return True

            try:
                info = d.info
                logger.warning(f"_check_success: ❌ no indicator found. device info: {info}")
            except Exception:
                pass
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
            self._unlock_screen()  # wake up + unlock PIN if configured
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

    # -------------------------------------------------------------------------
    # Delete Post API
    # -------------------------------------------------------------------------

    def _delete_post_sync(self, post_title: str) -> bool:
        """
        Navigate to My Profile → Notes, find the post by title, and delete it.

        Confirmed XHS delete flow (2025):
          1. Open XHS → profile tab
          2. Click the note thumbnail to open detail page
          3. Click "编辑和权限设置" (bottom of detail page)
          4. In "笔记设置" bottom sheet, swipe left on icon row to reveal "删除"
          5. Tap "删除" → tap "删除笔记" → tap "确认删除"
        Returns True if the post was deleted, False otherwise.
        """
        import re as _re

        d = self._get_device()
        orig_timeout = self._get_screen_timeout()
        self._set_screen_timeout(300000)
        try:
            self._unlock_screen()
            # 1. Start XHS and go to profile tab
            d.app_start(XHS_PACKAGE, stop=True)
            time.sleep(3)
            self._grant_permissions(d)
            self._dismiss_blocking_dialogs(d)

            # 2. Tap profile/me tab (rightmost bottom nav item)
            profile_tapped = (
                self._click_desc(d, "我", "我的", "个人中心", timeout=4)
                or self._click_text(d, "我", "我的", timeout=4)
                or self._click_resource(d, f"{XHS_PACKAGE}:id/tab_me", timeout=3)
            )
            if not profile_tapped:
                w, h = self._screen_size(d)
                d.click(int(w * 0.9), int(h * 0.972))  # far-right nav tab
            time.sleep(2)

            # 3. Find the note by title
            # XHS grid view stores title in content-desc (not text attribute).
            # The profile grid uses RecyclerView, so off-screen items are not
            # rendered — we must scroll to find the note.
            base_title = _re.split(r"[（(]", post_title)[0].strip() or post_title
            search_kw = post_title[:6] if len(post_title) >= 6 else post_title

            def _find_note() -> object:
                for selector in (
                    d(text=post_title),
                    d(textContains=search_kw),
                    d(descriptionContains=search_kw),
                    d(descriptionContains=base_title) if base_title != post_title else None,
                ):
                    if selector is not None and selector.exists(timeout=1):
                        return selector
                return None

            # Dismiss any in-feed banners (e.g. "随手拍&分享") by pressing back
            # or tapping close button before scrolling
            if d(text="去看看").exists(timeout=1):
                if d(textContains="✕").exists(timeout=1):
                    d(textContains="✕").click()
                else:
                    try:
                        close_btn = d(description="关闭")
                        if close_btn.exists(timeout=1):
                            close_btn.click()
                    except Exception:
                        pass

            note_el = _find_note()
            if note_el is None:
                w, h = self._screen_size(d)
                # Scroll down up to 6 times to find the note in the RecyclerView
                for _ in range(6):
                    d.swipe(w // 2, int(h * 0.6), w // 2, int(h * 0.3), duration=0.4)
                    time.sleep(0.8)
                    note_el = _find_note()
                    if note_el is not None:
                        break

            if note_el is None:
                self._screenshot(d, "delete_note_not_found")
                logger.warning(f"[{self.serial}] delete_post: note '{post_title}' not found")
                return False

            # 4. Click note to open detail page (NOT long-press — XHS grid is not long-clickable)
            note_el.click()
            time.sleep(3)
            self._dismiss_blocking_dialogs(d)

            # 5. Click "编辑和权限设置" to open 笔记设置 bottom sheet
            if not d(text="编辑和权限设置").exists(timeout=4):
                self._screenshot(d, "delete_edit_button_not_found")
                logger.warning(f"[{self.serial}] delete_post: '编辑和权限设置' not found")
                d.press("back")
                return False
            d(text="编辑和权限设置").click()
            time.sleep(2)

            # 6. Swipe LEFT in icon row to reveal "删除" (it's off-screen to the right)
            w, h = self._screen_size(d)
            icon_y = int(h * 0.935)  # icon row is at ~93.5% of screen height
            d.swipe(int(w * 0.83), icon_y, int(w * 0.05), icon_y, duration=0.6)
            time.sleep(1)

            # 7. Tap "删除"
            if not d(text="删除").exists(timeout=3):
                self._screenshot(d, "delete_icon_not_found")
                logger.warning(f"[{self.serial}] delete_post: '删除' icon not found after swipe")
                d.press("back")
                return False
            d(text="删除").click()
            time.sleep(1.5)

            # 8. Tap "删除笔记" (first confirmation)
            if d(text="删除笔记").exists(timeout=3):
                d(text="删除笔记").click()
                time.sleep(1.5)

            # 9. Tap "确认删除" (second/final confirmation)
            for confirm_text in ("确认删除", "确认", "确定"):
                if d(text=confirm_text).exists(timeout=2):
                    d(text=confirm_text).click()
                    break

            time.sleep(2)
            self._screenshot(d, "delete_post_done")
            logger.info(f"[{self.serial}] ✅ Post '{post_title}' deleted")
            return True

        except Exception as exc:
            logger.error(f"[{self.serial}] delete_post error: {exc}")
            return False
        finally:
            self._set_screen_timeout(orig_timeout)

    async def delete_post(self, post_title: str) -> bool:
        """Delete a published Xiaohongshu post by title (async wrapper)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._delete_post_sync, post_title)

    # -------------------------------------------------------------------------
    # Video Publish API
    # -------------------------------------------------------------------------

    async def publish_video(
        self,
        video_path: str,
        title: str,
        body: str,
        hashtags: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Publish a single-video note to Xiaohongshu.

        Args:
            video_path: Local path to the .mp4 file.
            title:      Post title.
            body:       Post body / description.
            hashtags:   Topic tags (without #).
            dry_run:    If True, run all steps up to (but not including) the
                        final "发布" tap. Useful for end-to-end smoke checks
                        that do not actually post.

        Returns:
            True on confirmed success; False otherwise (or True in dry_run
            once the editor is reached).
        """
        hashtags = hashtags or []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._publish_video_sync,
            video_path,
            title,
            body,
            hashtags,
            dry_run,
        )

    def _publish_video_sync(
        self,
        video_path: str,
        title: str,
        body: str,
        hashtags: List[str],
        dry_run: bool,
    ) -> bool:
        if not Path(video_path).exists():
            raise XHSPublishError(f"Video file not found: {video_path}")

        device_path: Optional[str] = None
        _orig_screen_timeout: Optional[int] = None
        try:
            d = self._get_device()
            _orig_screen_timeout = self._get_screen_timeout()
            self._set_screen_timeout(300000)  # 5 min — prevent sleep during automation

            # 1. Push video to device
            logger.info(f"[{self.serial}] Pushing video {video_path}")
            device_path = self._push_video(video_path)

            # 2. Open XHS publish flow
            logger.info(f"[{self.serial}] Opening XHS publish screen")
            self._unlock_screen()  # wake up + unlock PIN if configured
            self._open_xhs_publish(d)
            self._screenshot(d, "v01_publish_screen")

            # 3. Select video mode / video entry
            self._select_video_mode(d)
            self._screenshot(d, "v02_video_mode")

            # 4. Pick the freshly pushed video from album
            logger.info(f"[{self.serial}] Selecting video from album: {Path(video_path).name}")
            self._select_video_from_album(d, Path(video_path).name)
            self._screenshot(d, "v03_video_selected")

            # 5. Fill title / body (XHS may show a media editor with "下一步" first)
            logger.info(f"[{self.serial}] Filling title and body")
            self._fill_title_and_body(d, title, body)
            self._screenshot(d, "v04_content_filled")

            # 6. Hashtags
            if hashtags:
                logger.info(f"[{self.serial}] Adding {len(hashtags)} hashtags")
                self._add_hashtags(d, hashtags)
                self._screenshot(d, "v05_hashtags_added")

            if dry_run:
                logger.info(f"[{self.serial}] DRY RUN - skipping final publish tap")
                self._screenshot(d, "v06_dry_run_stop")
                return True

            # 7. Publish
            logger.info(f"[{self.serial}] Submitting video post")
            self._adb_wakeup()
            self._publish(d)

            # 8. Verify
            self._adb_wakeup()
            success = self._check_success(d, expected_title=title)
            if success:
                logger.info(f"[{self.serial}] ✅ Video post published")
            else:
                logger.warning(f"[{self.serial}] ⚠️ Could not confirm video publish success")
            return success

        except XHSPublishError:
            raise
        except Exception as exc:
            raise XHSPublishError(f"Video publish failed on {self.serial}: {exc}") from exc
        finally:
            if _orig_screen_timeout is not None:
                self._set_screen_timeout(_orig_screen_timeout)  # restore original timeout
            if device_path:
                try:
                    self._adb("shell", "rm", "-f", device_path)
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # Video-specific UI helpers
    # -------------------------------------------------------------------------

    def _select_video_mode(self, d):
        """
        From the publish chooser, enter the video flow.

        Newer XHS shows a bottom-sheet with options such as
            "从相册选择 / 拍摄 / 写文字"
        and once the album opens you can switch between 照片 / 视频 tabs.
        Older builds show explicit "视频" mode tabs at the bottom of the camera.
        """
        clicked = (
            self._click_text(d, "从相册选择", timeout=4)
            or self._click_text_contains(d, "相册选择", timeout=4)
            or self._click_text(d, "视频", timeout=6)
            or self._click_text_contains(d, "视频", timeout=6)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/video_tab", timeout=4)
        )
        if not clicked:
            self._screenshot(d, "video_mode_fail")
            if self.strict_mode:
                raise XHSPublishError(
                    "Could not find 视频 entry; strict mode aborted"
                )
            logger.warning("Could not find 视频 entry; compatible mode: tap mid-bottom")
            w, h = self._screen_size(d)
            d.click(int(w * 0.5), int(h * 0.92))
        time.sleep(1)

    def _select_video_from_album(self, d, filename: str):
        """
        Open the album (if not already) and select the freshly pushed video
        identified by `filename`.

        Strategy:
          1. Make sure we are on an album/grid screen; if photos are shown,
             try to switch to the "视频" tab.
          2. Prefer matching the cell whose contentDescription contains the
             filename. Fall back to the first video-like clickable cell.
        """
        self._grant_permissions(d)

        # Try switching album content type to videos if a tab exists
        switched = (
            self._click_text(d, "视频", timeout=3)
            or self._click_text_contains(d, "视频", timeout=2)
        )
        if switched:
            time.sleep(1)
            self._grant_permissions(d)

        # 1) Prefer description match (newer XHS sets desc to filename or duration)
        target_desc = filename
        el = d(descriptionContains=target_desc)
        if el.exists(timeout=3):
            el.click()
            time.sleep(1)
            self._confirm_album_selection(d)
            return

        # 2) Stem match (drop extension)
        stem = Path(filename).stem
        if stem and stem != target_desc:
            el2 = d(descriptionContains=stem)
            if el2.exists(timeout=1.5):
                el2.click()
                time.sleep(1)
                self._confirm_album_selection(d)
                return

        # 3) Classic resource-id (treat as a single-select grid)
        items = d(resourceId=f"{XHS_PACKAGE}:id/photo_item")
        if items.exists(timeout=2) and items.count > 0:
            items[0].click()
            time.sleep(1)
            self._confirm_album_selection(d)
            return

        # 4) Obfuscated grid fallback: first big clickable image cell.
        if self._is_album_grid_screen(d):
            picked = self._select_images_from_obfuscated_grid(d, 1)
            if picked > 0:
                time.sleep(1)
                self._confirm_album_selection(d)
                return

        self._screenshot(d, "video_pick_fail")
        if self.strict_mode:
            raise XHSPublishError(
                f"Could not locate pushed video '{filename}' in album; strict mode aborted"
            )

    def _confirm_album_selection(self, d):
        """Tap 下一步/完成 after picking media."""
        confirmed = (
            self._click_text(d, "下一步", "完成", "确定", timeout=6)
            or self._click_text_contains(d, "下一步", "完成", "确定", timeout=4)
            or self._click_resource(d, f"{XHS_PACKAGE}:id/next_btn", timeout=4)
        )
        if not confirmed and self.strict_mode:
            self._screenshot(d, "video_next_fail")
            raise XHSPublishError(
                "Could not tap 下一步 after picking video; strict mode aborted"
            )
        time.sleep(2)
