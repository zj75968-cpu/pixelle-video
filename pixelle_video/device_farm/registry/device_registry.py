"""Device Registry for managing device bindings and state.

This module provides YAML-based persistence for device configurations and state management.
"""

import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import yaml


class DeviceStatus(str, Enum):
    """Device operational states."""
    OFFLINE = "offline"
    IDLE = "idle"
    RUNNING = "running"
    NEEDS_CALIBRATION = "needs_calibration"
    BLOCKED = "blocked"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


@dataclass
class Device:
    """Device configuration and state."""
    phone_id: str
    name: str
    adb_serial: str
    ch9329_port: str
    screen: Dict[str, int]  # {"width": int, "height": int}
    status: DeviceStatus = DeviceStatus.OFFLINE
    calibration_profile: Optional[str] = None
    last_updated: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert device to dictionary for YAML serialization."""
        data = asdict(self)
        data['status'] = self.status.value
        if self.last_updated is None:
            data['last_updated'] = datetime.now().isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'Device':
        """Create device from dictionary loaded from YAML."""
        data = data.copy()
        if 'status' in data:
            data['status'] = DeviceStatus(data['status'])
        return cls(**data)


class DeviceRegistry:
    """Registry for managing device configurations with YAML persistence."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize device registry.

        Args:
            config_path: Path to devices.yaml file. Defaults to config/devices.yaml
        """
        if config_path is None:
            # Default to config/devices.yaml relative to project root
            project_root = Path(__file__).parent.parent.parent.parent
            config_path = project_root / "config" / "devices.yaml"

        self.config_path = Path(config_path)
        self._devices: Dict[str, Device] = {}
        self._load()

    def _load(self) -> None:
        """Load devices from YAML file."""
        if not self.config_path.exists():
            # Create empty config file with structure
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            devices_data = data.get('devices', [])
            self._devices = {
                device_data['phone_id']: Device.from_dict(device_data)
                for device_data in devices_data
            }
        except Exception as e:
            raise RuntimeError(f"Failed to load device registry from {self.config_path}: {e}")

    def _save(self) -> None:
        """Save devices to YAML file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                'devices': [device.to_dict() for device in self._devices.values()],
                'last_modified': datetime.now().isoformat()
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            raise RuntimeError(f"Failed to save device registry to {self.config_path}: {e}")

    def register_device(
        self,
        phone_id: str,
        name: str,
        adb_serial: str,
        ch9329_port: str,
        screen: Dict[str, int],
        calibration_profile: Optional[str] = None,
        status: DeviceStatus = DeviceStatus.OFFLINE,
        metadata: Optional[Dict] = None
    ) -> Device:
        """Register a new device or update existing device.

        Args:
            phone_id: Unique identifier for the device
            name: Human-readable device name
            adb_serial: ADB serial number
            ch9329_port: CH9329 serial port (e.g., "COM3")
            screen: Screen dimensions {"width": int, "height": int}
            calibration_profile: Optional calibration profile name
            status: Initial device status
            metadata: Optional additional metadata

        Returns:
            Device: The registered device

        Raises:
            ValueError: If required fields are invalid
        """
        if not phone_id:
            raise ValueError("phone_id is required")
        if not adb_serial:
            raise ValueError("adb_serial is required")
        if not ch9329_port:
            raise ValueError("ch9329_port is required")
        if not screen or 'width' not in screen or 'height' not in screen:
            raise ValueError("screen must contain 'width' and 'height'")

        device = Device(
            phone_id=phone_id,
            name=name,
            adb_serial=adb_serial,
            ch9329_port=ch9329_port,
            screen=screen,
            status=status,
            calibration_profile=calibration_profile,
            last_updated=datetime.now().isoformat(),
            metadata=metadata or {}
        )

        self._devices[phone_id] = device
        self._save()
        return device

    def get_device(self, phone_id: str) -> Optional[Device]:
        """Get device by phone_id.

        Args:
            phone_id: Device identifier

        Returns:
            Device if found, None otherwise
        """
        return self._devices.get(phone_id)

    def list_devices(
        self,
        status: Optional[DeviceStatus] = None,
        include_disabled: bool = True
    ) -> List[Device]:
        """List all devices, optionally filtered by status.

        Args:
            status: Filter by specific status
            include_disabled: Whether to include disabled devices

        Returns:
            List of devices matching criteria
        """
        devices = list(self._devices.values())

        if status is not None:
            devices = [d for d in devices if d.status == status]

        if not include_disabled:
            devices = [d for d in devices if d.status != DeviceStatus.DISABLED]

        return devices

    def update_device_status(
        self,
        phone_id: str,
        status: DeviceStatus,
        metadata: Optional[Dict] = None
    ) -> Optional[Device]:
        """Update device status and optionally metadata.

        Args:
            phone_id: Device identifier
            status: New status
            metadata: Optional metadata to merge with existing

        Returns:
            Updated device if found, None otherwise
        """
        device = self._devices.get(phone_id)
        if device is None:
            return None

        device.status = status
        device.last_updated = datetime.now().isoformat()

        if metadata:
            device.metadata.update(metadata)

        self._save()
        return device

    def update_device(
        self,
        phone_id: str,
        **kwargs
    ) -> Optional[Device]:
        """Update device fields.

        Args:
            phone_id: Device identifier
            **kwargs: Fields to update (name, adb_serial, ch9329_port, screen,
                     calibration_profile, status, metadata)

        Returns:
            Updated device if found, None otherwise
        """
        device = self._devices.get(phone_id)
        if device is None:
            return None

        # Update allowed fields
        allowed_fields = {
            'name', 'adb_serial', 'ch9329_port', 'screen',
            'calibration_profile', 'status', 'metadata'
        }

        for key, value in kwargs.items():
            if key in allowed_fields:
                if key == 'status' and isinstance(value, str):
                    value = DeviceStatus(value)
                setattr(device, key, value)

        device.last_updated = datetime.now().isoformat()
        self._save()
        return device

    def remove_device(self, phone_id: str) -> bool:
        """Remove device from registry.

        Args:
            phone_id: Device identifier

        Returns:
            True if device was removed, False if not found
        """
        if phone_id in self._devices:
            del self._devices[phone_id]
            self._save()
            return True
        return False

    def get_available_devices(self) -> List[Device]:
        """Get devices available for job assignment (idle status).

        Returns:
            List of idle devices
        """
        return self.list_devices(status=DeviceStatus.IDLE, include_disabled=False)

    def reload(self) -> None:
        """Reload devices from YAML file."""
        self._load()
