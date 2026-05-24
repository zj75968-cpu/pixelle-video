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

    @property
    def devices_file(self) -> Path:
        from pixelle_video.utils.user_context import get_current_username
        username = get_current_username()
        if username == "default":
            return DATA_DIR / "devices.json"
        path = DATA_DIR / "users" / username / "devices.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def _devices(self) -> Dict[str, DeviceInfo]:
        from pixelle_video.utils.user_context import get_current_username
        username = get_current_username()
        
        path = self.devices_file
        current_mtime = 0
        try:
            if path.exists():
                current_mtime = path.stat().st_mtime
        except Exception:
            pass
            
        if (username not in self._user_devices or 
            self._user_devices_mtimes.get(username, 0) != current_mtime):
            self._load()
            
        return self._user_devices[username]

    @_devices.setter
    def _devices(self, value: Dict[str, DeviceInfo]):
        from pixelle_video.utils.user_context import get_current_username
        username = get_current_username()
        self._user_devices[username] = value
        
        path = self.devices_file
        try:
            if path.exists():
                self._user_devices_mtimes[username] = path.stat().st_mtime
            else:
                self._user_devices_mtimes[username] = 0
        except Exception:
            self._user_devices_mtimes[username] = 0

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._user_devices: Dict[str, Dict[str, DeviceInfo]] = {}
        self._user_devices_mtimes: Dict[str, float] = {}  # Added
        self._adb_cmd = self._resolve_adb_command()
        self._adb_server_host: str = "127.0.0.1"
        self._adb_server_port: int = 5037
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._auto_sync_thread: Optional[threading.Thread] = None
        self._auto_sync_interval = DEFAULT_AUTO_SYNC_INTERVAL
        self._wifi_reconnect_cooldown = DEFAULT_WIFI_RECONNECT_COOLDOWN
        self._last_wifi_attempt: Dict[str, float] = {}
        # load will be triggered automatically when property accessed

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _load(self):
        """Load device registry from JSON file."""
        from pixelle_video.utils.user_context import get_current_username
        username = get_current_username()
        with self._lock:
            path = self.devices_file
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._user_devices[username] = {
                        s: DeviceInfo.from_dict(d)
                        for s, d in data.items()
                    }
                    self._user_devices_mtimes[username] = path.stat().st_mtime
                    logger.info(f"Loaded {len(self._user_devices[username])} devices from registry")
                except Exception as e:
                    logger.warning(f"Failed to load devices registry: {e}")
                    self._user_devices[username] = {}
                    self._user_devices_mtimes[username] = 0
            else:
                self._user_devices[username] = {}
                self._user_devices_mtimes[username] = 0

    def _save(self):
        """Persist device registry to JSON file."""
        from pixelle_video.utils.user_context import get_current_username
        username = get_current_username()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = self.devices_file
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {s: d.to_dict() for s, d in self._devices.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            if path.exists():
                self._user_devices_mtimes[username] = path.stat().st_mtime
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

    def configure_adb_server(self, host: str, port: int) -> None:
        """Set a remote ADB server to proxy commands through.

        When host differs from 127.0.0.1 or port from 5037, all subsequent
        adb invocations will prepend ``-H host -P port`` so they target that
        remote ADB server (where the phone is actually connected).
        """
        self._adb_server_host = host.strip() or "127.0.0.1"
        self._adb_server_port = int(port) if port else 5037
        logger.info(f"ADB server configured: {self._adb_server_host}:{self._adb_server_port}")

    def _adb(self, *args: str, serial: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run an adb command and return the CompletedProcess result."""
        cmd = [self._adb_cmd]
        # Proxy to remote ADB server when configured
        if self._adb_server_host != "127.0.0.1" or self._adb_server_port != 5037:
            cmd += ["-H", self._adb_server_host, "-P", str(self._adb_server_port)]
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
        ok, _ = self.connect_wifi(host, port, quiet=True)
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
        """Return list of ADB-connected device serials (and client agent serials)."""
        serials = []
        # 1. 物理/本地 WiFi ADB 连接的设备
        try:
            self.refresh_adb_command()
            result = self._adb("devices")
            for line in result.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
        except Exception as e:
            logger.debug(f"Local ADB check skipped/failed: {e}")

        # 2. 从 Client Agent (客户端拉取代理) 获取在线设备（在云端/VPS环境下，即使模式不是agent_pull也应显示在线的代理设备，以便用户选择）
        try:
            from pixelle_video.services.android_device_dispatcher import DistributionAdapter
            if True:  # 允许所有模式同步并显示在线的 Client Agent 设备
                import os
                from datetime import datetime
                now = datetime.now()
                agents_list = []
                
                if os.environ.get("IS_FASTAPI_PROCESS") == "1":
                    # 在 FastAPI 进程内，直接读内存字典
                    try:
                        from api.routers.publish import ACTIVE_AGENTS
                        agents_list = list(ACTIVE_AGENTS.values())
                    except ImportError:
                        pass
                else:
                    # 在 Streamlit 进程内，发起 HTTP 请求向 FastAPI 查询
                    import requests
                    try:
                        res = requests.get("http://127.0.0.1:8000/api/publish/agent/list", timeout=1.5)
                        if res.status_code == 200:
                            agents_list = res.json().get("agents", [])
                    except Exception as ex:
                        logger.debug(f"Failed to query active agents via HTTP: {ex}")
                
                for agent in agents_list:
                    last_seen_str = agent.get("last_seen", "")
                    if last_seen_str:
                        # 兼容有无 T/Z 的 ISO 字符串
                        try:
                            last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                            if last_seen.tzinfo is not None:
                                # 统一转为无时区本地时间进行比较
                                last_seen = last_seen.astimezone().replace(tzinfo=None)
                        except Exception:
                            continue
                        # 如果代理在 30 秒内活跃，则认为其连接的所有设备在线
                        if (now - last_seen).total_seconds() <= 30:
                            for s in agent.get("serials", []):
                                if s not in serials:
                                    serials.append(s)
        except Exception as e:
            logger.warning(f"Failed to load active client agents: {e}")

        # 3. 兼容 phone_agent 虚拟代理在线状态
        try:
            from pixelle_video.config import config_manager
            from pixelle_video.services.phone_agent_client import ping
            cfg = config_manager.config
            agent_url = cfg.phone_agent.url.strip()
            if agent_url:
                # 检查是否在线
                is_online = ping(agent_url, token=cfg.phone_agent.token.strip(), timeout=2)
                if is_online:
                    serial_name = "phone_agent"
                    if serial_name not in serials:
                        serials.append(serial_name)
                    # 自动将其注册进设备管理器，以防 get_all() 过滤掉
                    if serial_name not in self._devices:
                        self.add_device(serial=serial_name, name="手机 HTTP 代理", theme="默认主题")
        except Exception as e:
            logger.debug(f"Failed to check phone agent online status: {e}")

        if serials:
            logger.debug(f"Found connected devices: {serials}")
        return serials

    def connect_wifi(self, host: str, port: int = 5555, quiet: bool = False) -> Tuple[bool, str]:
        """Connect to a device over WiFi (TCP/IP).

        Returns:
            (success, adb_output_message)
        """
        try:
            result = self._adb("connect", f"{host}:{port}")
            message = result.stdout.strip()
            success = "connected" in message.lower()
            if quiet:
                logger.debug(f"WiFi connect {host}:{port}: {message}")
            else:
                logger.info(f"WiFi connect {host}:{port}: {message}")
            return success, message
        except FileNotFoundError:
            msg = "ADB not found in PATH"
            if not quiet:
                logger.warning(msg)
            return False, msg
        except Exception as e:
            msg = str(e)
            if quiet:
                logger.debug(f"WiFi connect error: {msg}")
            else:
                logger.error(f"WiFi connect error: {msg}")
            return False, msg

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

    # -------------------------------------------------------------------------
    # LAN / mDNS Discovery
    # -------------------------------------------------------------------------

    def scan_mdns(self, timeout: float = 5.0) -> List[Dict[str, str]]:
        """Discover ADB devices via mDNS (Android 11+ wireless-debugging broadcasts).

        Returns a list of dicts with keys: ip, port, serial, type.
          type is either 'connect' (_adb-tls-connect) or 'pair' (_adb-tls-pairing).

        Requires adb >= 30 and Android 11+. Returns [] if mDNS is not supported.
        """
        found: List[Dict[str, str]] = []
        try:
            result = self._adb("mdns", "services")
            for line in result.stdout.splitlines():
                # Format: adb-<serial>    _adb-tls-connect._tcp.    192.168.x.x:port
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                svc_type = parts[1] if len(parts) > 1 else ""
                addr = parts[-1]  # "ip:port"
                if ":" not in addr:
                    continue
                ip, port_str = addr.rsplit(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    continue
                kind = (
                    "connect" if "connect" in svc_type
                    else "pair" if "pair" in svc_type
                    else "unknown"
                )
                found.append({
                    "ip": ip,
                    "port": port,
                    "serial": f"{ip}:{port}",
                    "type": kind,
                    "raw": line.strip(),
                })
            logger.info(f"mDNS scan found {len(found)} service(s)")
        except Exception as exc:
            logger.debug(f"mDNS scan failed (may not be supported): {exc}")
        return found

    def scan_lan_port(
        self,
        port: int = 5555,
        subnet: Optional[str] = None,
        max_threads: int = 50,
        connect_timeout: float = 0.5,
    ) -> List[str]:
        """Scan the local subnet for open ADB TCP port (default 5555).

        Used for older Android ≤10 devices where "adb tcpip 5555" was run via USB.

        Args:
            port: TCP port to probe (default 5555).
            subnet: Base IP like "192.168.1" — auto-detected if None.
            max_threads: Parallel probes (default 50 → ~2.5 s for /24).
            connect_timeout: Per-host timeout in seconds.

        Returns:
            List of "ip:port" strings where the port was open.
        """
        import ipaddress
        import socket
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Auto-detect local subnet from default gateway interface
        if subnet is None:
            try:
                import socket as _sock
                s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
                s.settimeout(0)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                subnet = ".".join(local_ip.split(".")[:3])
            except Exception:
                logger.warning("scan_lan_port: could not auto-detect subnet, defaulting to 192.168.1")
                subnet = "192.168.1"

        def _probe(ip_str: str) -> Optional[str]:
            try:
                with socket.create_connection((ip_str, port), timeout=connect_timeout):
                    return ip_str
            except (ConnectionRefusedError, socket.timeout, OSError):
                return None

        hosts = [f"{subnet}.{i}" for i in range(1, 255)]
        reachable: List[str] = []
        with ThreadPoolExecutor(max_workers=max_threads) as pool:
            for result in as_completed([pool.submit(_probe, h) for h in hosts]):
                val = result.result()
                if val:
                    reachable.append(val)

        reachable.sort(key=lambda x: int(x.rsplit(".", 1)[-1]))
        logger.info(f"LAN port scan (subnet {subnet}, port {port}): {len(reachable)} host(s) found")
        return [f"{ip}:{port}" for ip in reachable]

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
