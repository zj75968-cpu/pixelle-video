# -*- coding: utf-8 -*-
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from pixelle_video.config import config_manager

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEVICES_FILE = DATA_DIR / "devices.json"

class DeviceInfo:
    """Hardware serial device information and status."""
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
        self.connected: bool = True
        self.last_seen: Optional[str] = datetime.now().isoformat()
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
        obj.connected = data.get("connected", True)
        obj.last_seen = data.get("last_seen", datetime.now().isoformat())
        obj.added_at = data.get("added_at", datetime.now().isoformat())
        return obj

class DeviceManager:
    """
    Device manager for hardware-controlled devices (COM port).
    """
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._devices_cache: Dict[str, DeviceInfo] = {}
        self._load()

    def _load(self):
        """Load device registry from JSON file."""
        with self._lock:
            if DEVICES_FILE.exists():
                try:
                    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._devices_cache = {
                        s: DeviceInfo.from_dict(d)
                        for s, d in data.items()
                    }
                    logger.info(f"Loaded {len(self._devices_cache)} devices from registry")
                except Exception as e:
                    logger.warning(f"Failed to load devices registry: {e}")
                    self._devices_cache = {}
            else:
                self._devices_cache = {}

    def _save(self):
        """Persist device registry to JSON file."""
        with self._lock:
            try:
                with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                    json.dump(
                        {s: d.to_dict() for s, d in self._devices_cache.items()},
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            except Exception as e:
                logger.error(f"Failed to save devices registry: {e}")

    def list_connected_serials(self) -> List[str]:
        """Return list of connected hardware serials (COM ports)."""
        # 读取配置中的 COM 口作为唯一连接的设备
        try:
            com_port = config_manager.config.xhs_publish.hardware.com_port
            if com_port:
                return [com_port]
        except Exception:
            pass
        return ["COM3"]

    def check_adb_available(self) -> bool:
        """Return True so legacy publish UI can operate in CH9329 mode."""
        return True

    def configure_adb_server(self, host: str = "127.0.0.1", port: int = 5037):
        """Keep legacy ADB server settings harmlessly accepted in hardware mode."""
        self._adb_server_host = host or "127.0.0.1"
        self._adb_server_port = int(port or 5037)

    def connect_wifi(self, host: str, port: int) -> tuple[bool, str]:
        """WiFi ADB is unavailable when publishing through CH9329 hardware control."""
        return False, "CH9329 硬件控制模式不需要 ADB WiFi 连接，请在配置中设置串口 COM 号。"

    def pair_wireless(self, host: str, pair_port: int, pairing_code: str) -> tuple[bool, str]:
        """Wireless ADB pairing is unavailable in CH9329 hardware mode."""
        return False, "CH9329 硬件控制模式不需要 Android 无线配对。"

    def scan_mdns(self, timeout: float = 5.0) -> list[dict]:
        """mDNS discovery is only used by ADB wireless devices; CH9329 has none."""
        return []

    def sync_connected(self):
        """Dummy sync."""
        with self._lock:
            # 确保配置文件中的 COM 口在缓存中
            serials = self.list_connected_serials()
            for s in serials:
                if s not in self._devices_cache:
                    self._devices_cache[s] = DeviceInfo(serial=s, name="物理串口发帖机", theme="通用主题")
            self._save()

    def get_all(self) -> List[DeviceInfo]:
        """Return all registered devices."""
        self.sync_connected()
        with self._lock:
            return list(self._devices_cache.values())

    def get(self, serial: str) -> Optional[DeviceInfo]:
        """Return device info by serial."""
        with self._lock:
            return self._devices_cache.get(serial)

    def add_device(
        self,
        serial: str,
        name: str = "",
        theme: str = "",
        notes: str = "",
    ) -> DeviceInfo:
        """Register a new device."""
        with self._lock:
            if serial in self._devices_cache:
                dev = self._devices_cache[serial]
                if name:
                    dev.name = name
                if theme:
                    dev.theme = theme
                if notes:
                    dev.notes = notes
            else:
                dev = DeviceInfo(serial=serial, name=name, theme=theme, notes=notes)
                self._devices_cache[serial] = dev
            self._save()
        return dev

    def remove_device(self, serial: str) -> bool:
        """Remove a device from the registry."""
        with self._lock:
            if serial in self._devices_cache:
                del self._devices_cache[serial]
                self._save()
                return True
            return False

    def screenshot(self, serial: str) -> Optional[bytes]:
        """Hardware mode does not support screenshot."""
        return None

    def start_auto_sync(self, interval_seconds: int = 8):
        pass

    def stop_auto_sync(self):
        pass

# Module-level singleton
device_manager = DeviceManager()

def push_images_to_gallery(
    serial: str,
    local_paths: List[str],
    push_dir: str = "",
) -> dict:
    """Dummy fallback for image pushing in hardware mode."""
    logger.warning("push_images_to_gallery is deprecated in CH9329 hardware control mode.")
    return {
        "success": 0,
        "failed": local_paths,
        "device_paths": [],
    }
