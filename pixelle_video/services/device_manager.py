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
Device Manager Service

Manages Android device connections via ADB for automated Xiaohongshu publishing.
Supports USB and WiFi (TCP/IP) connections.
"""

import json
import os
import shutil
import subprocess
import threading
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from loguru import logger


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEVICES_FILE = DATA_DIR / "devices.json"
PROJECT_LOCAL_ADB = (
    Path(__file__).resolve().parent.parent.parent
    / "packaging"
    / "windows"
    / "platform-tools"
    / "adb.exe"
)
DEFAULT_AUTO_SYNC_INTERVAL = 8
DEFAULT_WIFI_RECONNECT_COOLDOWN = 30


class DeviceInfo:
    """Android device information and status."""

    def __init__(
        self,
        serial: str,
        name: str = "",
        theme: str = "",
        notes: str = "",
    ):
        self.serial = serial
        self.name = name
        self.theme = theme
        self.notes = notes
        self.connected: bool = False
        self.last_seen: Optional[str] = None
        self.added_at: str = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "serial": self.serial,
            "name": self.name,
            "theme": self.theme,
            "notes": self.notes,
            "connected": self.connected,
            "last_seen": self.last_seen,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceInfo":
        obj = cls(
            serial=data["serial"],
            name=data.get("name", ""),
            theme=data.get("theme", ""),
            notes=data.get("notes", ""),
        )
        obj.connected = data.get("connected", False)
        obj.last_seen = data.get("last_seen")
        obj.added_at = data.get("added_at", datetime.now().isoformat())
        return obj


class DeviceManager:
    """
    Android device manager using ADB.

    Manages device registry, connection status, and basic ADB operations.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[str, DeviceInfo] = {}
        self._adb_cmd = self._resolve_adb_command()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._auto_sync_thread: Optional[threading.Thread] = None
        self._auto_sync_interval = DEFAULT_AUTO_SYNC_INTERVAL
        self._wifi_reconnect_cooldown = DEFAULT_WIFI_RECONNECT_COOLDOWN
        self._last_wifi_attempt: Dict[str, float] = {}
        self._load()

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _load(self):
        """Load device registry from JSON file."""
        with self._lock:
            if DEVICES_FILE.exists():
                try:
                    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._devices = {
                        s: DeviceInfo.from_dict(d)
                        for s, d in data.items()
                    }
                    logger.info(f"Loaded {len(self._devices)} devices from registry")
                except Exception as e:
                    logger.warning(f"Failed to load devices registry: {e}")
                    self._devices = {}

    def _save(self):
        """Persist device registry to JSON file."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {s: d.to_dict() for s, d in self._devices.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to save devices registry: {e}")

    # -------------------------------------------------------------------------
    # ADB Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _candidate_adb_paths() -> List[Path]:
        """Collect likely adb.exe locations on Windows and common SDK layouts."""
        candidates: List[Path] = []

        env_roots = [
            os.environ.get("ADB_PATH"),
            os.environ.get("ANDROID_SDK_ROOT"),
            os.environ.get("ANDROID_HOME"),
        ]
        for raw in env_roots:
            if not raw:
                continue
            root = Path(raw)
            if root.suffix.lower() == ".exe":
                candidates.append(root)
            else:
                candidates.append(root / "platform-tools" / "adb.exe")

        home = Path.home()
        candidates.extend([
            PROJECT_LOCAL_ADB,
            home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            home / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path("C:/Android/platform-tools/adb.exe"),
        ])

        return candidates

    def _resolve_adb_command(self) -> str:
        """Resolve an executable adb command for subprocess invocation."""
        adb_from_path = shutil.which("adb")
        if adb_from_path:
            logger.info(f"Using adb from PATH: {adb_from_path}")
            return adb_from_path

        for candidate in self._candidate_adb_paths():
            if candidate.exists():
                logger.info(f"Using adb from discovered location: {candidate}")
                return str(candidate)

        logger.warning("ADB executable not found. Install Platform-Tools or set ADB_PATH.")
        return "adb"

    def refresh_adb_command(self) -> str:
        """Re-resolve adb command in case environment changed after startup."""
        self._adb_cmd = self._resolve_adb_command()
        return self._adb_cmd

    def get_adb_command(self) -> str:
        """Return current adb command path used by the service."""
        return self._adb_cmd

    def _adb(self, *args: str, serial: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run an adb command and return the CompletedProcess result."""
        cmd = [self._adb_cmd]
        if serial:
            cmd += ["-s", serial]
        cmd += list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for lightweight theme/topic matching."""
        cleaned = re.sub(r"\s+", "", (text or "").lower())
        return cleaned

    @classmethod
    def _tokenize_for_match(cls, text: str) -> List[str]:
        """Split topic/theme into coarse-grained tokens without extra dependencies."""
        normalized = cls._normalize_text(text)
        if not normalized:
            return []

        parts = re.split(r"[^\w\u4e00-\u9fff]+", normalized)
        tokens = [p for p in parts if p]

        # Add bi-grams for Chinese phrases to improve rough matching quality.
        if len(normalized) >= 2:
            tokens.extend([normalized[i:i + 2] for i in range(len(normalized) - 1)])

        return list(dict.fromkeys(tokens))

    def suggest_devices_by_topic(
        self,
        topic: str,
        connected_only: bool = True,
        threshold: float = 0.35,
    ) -> List[Tuple[DeviceInfo, float, str]]:
        """
        Suggest devices by topic-theme similarity.

        Returns tuples of (device, score, reason) sorted by score desc.
        """
        self.sync_connected()
        topic_tokens = self._tokenize_for_match(topic)
        if not topic_tokens:
            return []

        topic_set = set(topic_tokens)
        ranked: List[Tuple[DeviceInfo, float, str]] = []

        with self._lock:
            for dev in self._devices.values():
                if connected_only and not dev.connected:
                    continue
                if not dev.theme:
                    continue

                theme_tokens = self._tokenize_for_match(dev.theme)
                if not theme_tokens:
                    continue

                overlap = topic_set.intersection(theme_tokens)
                if not overlap:
                    continue

                score = len(overlap) / max(1, len(set(theme_tokens)))
                if score < threshold:
                    continue

                reason = f"主题命中: {', '.join(sorted(list(overlap))[:3])}"
                ranked.append((dev, score, reason))

        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    @staticmethod
    def _is_wifi_serial(serial: str) -> bool:
        """Best-effort check whether serial is a WiFi endpoint like host:port."""
        return ":" in serial and not serial.startswith("emulator-")

    def _try_auto_reconnect_wifi(self, serial: str) -> bool:
        """Attempt reconnect for saved WiFi device with cooldown to avoid spamming adb."""
        if not self._is_wifi_serial(serial):
            return False

        host, port_str = serial.rsplit(":", 1)
        if not host:
            return False

        try:
            port = int(port_str)
        except ValueError:
            logger.debug(f"Skip invalid WiFi serial: {serial}")
            return False

        now = time.time()
        last_attempt = self._last_wifi_attempt.get(serial, 0)
        if now - last_attempt < self._wifi_reconnect_cooldown:
            return False

        self._last_wifi_attempt[serial] = now
        ok = self.connect_wifi(host, port, quiet=True)
        if ok:
            logger.info(f"Auto reconnected WiFi device: {serial}")
        return ok

    def _update_live_status(self, live: set[str], now_iso: str) -> bool:
        """Update registry connected flags based on live adb serial set."""
        changed = False

        # Auto-register newly discovered live devices to avoid manual USB registration.
        for serial in live:
            if serial not in self._devices:
                self._devices[serial] = DeviceInfo(serial=serial)
                self._devices[serial].connected = True
                self._devices[serial].last_seen = now_iso
                changed = True
                logger.info(f"Auto-registered live device: {serial}")

        for serial, device in self._devices.items():
            was_connected = device.connected
            device.connected = serial in live
            if device.connected and not was_connected:
                device.last_seen = now_iso
                changed = True
                logger.info(f"Device {serial} ({device.name}) connected")
            elif not device.connected and was_connected:
                changed = True
                logger.info(f"Device {serial} ({device.name}) disconnected")
        return changed

    def list_connected_serials(self) -> List[str]:
        """Return list of ADB-connected device serials."""
        try:
            self.refresh_adb_command()
            result = self._adb("devices")
            serials = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
            if serials:
                logger.debug(f"Found connected devices: {serials}")
            return serials
        except FileNotFoundError:
            logger.error("ADB not found in PATH. Install Android SDK Platform-Tools to enable device management.")
            return []
        except subprocess.TimeoutExpired:
            logger.error("ADB devices command timed out. Check if ADB is responsive.")
            return []
        except Exception as e:
            logger.error(f"ADB devices error: {e}", exc_info=True)
            return []

    def connect_wifi(self, host: str, port: int = 5555, quiet: bool = False) -> bool:
        """Connect to a device over WiFi (TCP/IP)."""
        try:
            result = self._adb("connect", f"{host}:{port}")
            success = "connected" in result.stdout.lower()
            message = result.stdout.strip()
            if quiet:
                logger.debug(f"WiFi connect {host}:{port}: {message}")
            else:
                logger.info(f"WiFi connect {host}:{port}: {message}")
            return success
        except FileNotFoundError:
            if not quiet:
                logger.warning("ADB not found in PATH.")
            return False
        except Exception as e:
            if quiet:
                logger.debug(f"WiFi connect error: {e}")
            else:
                logger.error(f"WiFi connect error: {e}")
            return False

    def pair_wireless(self, host: str, pair_port: int, code: str) -> Tuple[bool, str]:
        """Pair a device using Android 11+ wireless pairing (adb pair).

        Must be called before connect_wifi when using QR/pairing-code method.
        Args:
            host:      Device IP address shown in Wireless Debugging screen.
            pair_port: Temporary pairing port (different from the main connect port).
            code:      6-digit pairing code shown in the pairing dialog.
        Returns:
            (success, adb_output_message)
        """
        try:
            result = subprocess.run(
                [self._adb_cmd, "pair", f"{host}:{pair_port}", code],
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            output = (stdout + ("\n" + stderr if stderr else "")).strip()
            # adb pair prints "Successfully paired to …" on success
            success = (
                "successfully" in output.lower()
                or "paired to" in output.lower()
                or result.returncode == 0 and not output.lower().startswith("error")
            )
            logger.info(f"adb pair {host}:{pair_port}: {output}")
            return success, output
        except FileNotFoundError:
            return False, "ADB 未找到，请先安装 Platform-Tools"
        except subprocess.TimeoutExpired:
            return False, "配对超时（30s），请检查网络连通性"
        except Exception as exc:
            return False, str(exc)

    def disconnect_wifi(self, host: str, port: int = 5555) -> bool:
        """Disconnect a WiFi-connected device."""
        try:
            result = self._adb("disconnect", f"{host}:{port}")
            logger.info(f"WiFi disconnect {host}:{port}: {result.stdout.strip()}")
            return True
        except Exception as e:
            logger.error(f"WiFi disconnect error: {e}")
            return False

    def screenshot(self, serial: str) -> Optional[bytes]:
        """Capture a screenshot from the specified device. Returns PNG bytes."""
        try:
            result = subprocess.run(
                [self._adb_cmd, "-s", serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except Exception as e:
            logger.error(f"Screenshot failed for {serial}: {e}")
            return None

    # -------------------------------------------------------------------------
    # Registry Operations
    # -------------------------------------------------------------------------

    def sync_connected(self):
        """Sync connected status for all registered devices against live ADB list."""
        with self._lock:
            live = set(self.list_connected_serials())
            now = datetime.now().isoformat()
            changed = self._update_live_status(live, now)

            reconnect_candidates = [
                serial
                for serial, device in self._devices.items()
                if not device.connected and self._is_wifi_serial(serial)
            ]

            retried = False
            for serial in reconnect_candidates:
                if self._try_auto_reconnect_wifi(serial):
                    retried = True

            if retried:
                live = set(self.list_connected_serials())
                changed = self._update_live_status(live, now) or changed

            if changed:
                self._save()

    def get_all(self) -> List[DeviceInfo]:
        """Return all registered devices."""
        self.sync_connected()
        with self._lock:
            return list(self._devices.values())

    def get(self, serial: str) -> Optional[DeviceInfo]:
        """Return device info by serial."""
        with self._lock:
            return self._devices.get(serial)

    def add_device(
        self,
        serial: str,
        name: str = "",
        theme: str = "",
        notes: str = "",
    ) -> DeviceInfo:
        """Register a new device (or update existing)."""
        with self._lock:
            if serial in self._devices:
                dev = self._devices[serial]
                if name:
                    dev.name = name
                if theme:
                    dev.theme = theme
                if notes:
                    dev.notes = notes
            else:
                dev = DeviceInfo(serial=serial, name=name, theme=theme, notes=notes)
                self._devices[serial] = dev
            self._save()
        logger.info(f"Registered device: {serial} ({name})")
        return dev

    def remove_device(self, serial: str) -> bool:
        """Remove a device from the registry."""
        with self._lock:
            if serial in self._devices:
                del self._devices[serial]
                self._save()
                logger.info(f"Removed device: {serial}")
                return True
            return False

    def _auto_sync_loop(self):
        """Background loop to keep USB/WiFi device state fresh."""
        while not self._stop_event.wait(self._auto_sync_interval):
            try:
                self.sync_connected()
            except Exception as e:
                logger.error(f"Device auto-sync tick failed: {e}", exc_info=True)

    def start_auto_sync(self, interval_seconds: int = DEFAULT_AUTO_SYNC_INTERVAL):
        """Start background auto-sync loop once per process."""
        interval = max(3, int(interval_seconds))
        self._auto_sync_interval = interval

        if self._auto_sync_thread and self._auto_sync_thread.is_alive():
            return

        self._stop_event.clear()
        self._auto_sync_thread = threading.Thread(
            target=self._auto_sync_loop,
            name="device-manager-auto-sync",
            daemon=True,
        )
        self._auto_sync_thread.start()
        logger.info(f"Device auto-sync started (interval={self._auto_sync_interval}s)")

    def stop_auto_sync(self):
        """Stop background auto-sync loop."""
        if not self._auto_sync_thread:
            return
        self._stop_event.set()
        self._auto_sync_thread.join(timeout=3)
        self._auto_sync_thread = None
        logger.info("Device auto-sync stopped")

    def check_adb_available(self) -> bool:
        """Check if ADB is installed and available."""
        try:
            self.refresh_adb_command()
            result = self._adb("version")
            ok = result.returncode == 0
            if ok:
                logger.debug(f"ADB is available via: {self._adb_cmd}")
            else:
                logger.warning(f"ADB version check failed with code {result.returncode}: {result.stderr}")
            return ok
        except FileNotFoundError:
            logger.warning("ADB command not found in PATH")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("ADB version check timed out")
            return False
        except Exception as e:
            logger.warning(f"ADB availability check failed: {e}")
            return False


# Module-level singleton
device_manager = DeviceManager()


# ---------------------------------------------------------------------------
# Standalone utility: push images to device gallery
# ---------------------------------------------------------------------------

def push_images_to_gallery(
    serial: str,
    local_paths: List[str],
    push_dir: str = "/sdcard/DCIM/PixelleVideo",
) -> dict:
    """Push local image files to an Android device's gallery via ADB.

    Each file is pushed with ``adb push`` then a ``MEDIA_SCANNER_SCAN_FILE``
    broadcast is sent so the images appear in the device's photo gallery
    immediately without requiring a reboot.

    Args:
        serial: ADB device serial (or host:port for WiFi).
        local_paths: Absolute local paths of the image files to push.
        push_dir: Destination directory on the device.

    Returns:
        A dict with keys:
        - ``success`` (int): number of files pushed successfully.
        - ``failed`` (list[str]): local paths that failed.
        - ``device_paths`` (list[str]): device-side paths of pushed files.
    """
    def _adb(*args: str) -> str:
        result = subprocess.run(
            ["adb", "-s", serial] + list(args),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ADB error: {result.stderr.strip()}")
        return result.stdout.strip()

    # Ensure destination directory exists
    try:
        _adb("shell", "mkdir", "-p", push_dir)
    except Exception as exc:
        logger.warning(f"push_images_to_gallery: mkdir failed ({exc}), proceeding anyway")

    device_paths: list[str] = []
    failed: list[str] = []

    for local_path in local_paths:
        filename = Path(local_path).name
        device_path = f"{push_dir}/{filename}"
        try:
            _adb("push", local_path, device_path)
            device_paths.append(device_path)
            logger.info(f"push_images_to_gallery: pushed {local_path} → {device_path}")
        except Exception as exc:
            logger.error(f"push_images_to_gallery: failed to push {local_path}: {exc}")
            failed.append(local_path)

    # Trigger media scanner for successfully pushed files
    for dp in device_paths:
        try:
            _adb(
                "shell", "am", "broadcast",
                "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d", f"file://{dp}",
            )
        except Exception as exc:
            logger.warning(f"push_images_to_gallery: media scan failed for {dp}: {exc}")

    if device_paths:
        time.sleep(2)  # Give media scanner time to index

    return {
        "success": len(device_paths),
        "failed": failed,
        "device_paths": device_paths,
    }
