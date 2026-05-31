# -*- coding: utf-8 -*-
"""
Enhanced ADB Device Manager with Auto-Retry and Reconnection

Provides robust device management with:
- Automatic retry on transient failures
- Device health monitoring
- Auto-reconnection for dropped devices
- Connection state tracking
- Batch device operations
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from enum import Enum

from loguru import logger

from .adb_observer import (
    ADBDevice,
    ADBError,
    scan_adb_devices,
    check_device_connectivity,
    get_device_info,
    _run_adb_command
)


class DeviceState(Enum):
    """Device connection states."""
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    RECONNECTING = "reconnecting"


@dataclass
class DeviceHealth:
    """Tracks device health metrics."""
    serial: str
    state: DeviceState = DeviceState.UNKNOWN
    last_seen: datetime = field(default_factory=datetime.now)
    last_successful_command: datetime = field(default_factory=datetime.now)
    consecutive_failures: int = 0
    total_reconnects: int = 0
    uptime_start: Optional[datetime] = None

    def mark_success(self):
        """Mark a successful operation."""
        self.last_successful_command = datetime.now()
        self.consecutive_failures = 0
        if self.state != DeviceState.CONNECTED:
            self.state = DeviceState.CONNECTED
            self.uptime_start = datetime.now()

    def mark_failure(self):
        """Mark a failed operation."""
        self.consecutive_failures += 1
        self.last_seen = datetime.now()

    def is_healthy(self, max_failures: int = 3) -> bool:
        """Check if device is considered healthy."""
        return (
            self.state == DeviceState.CONNECTED and
            self.consecutive_failures < max_failures
        )

    def time_since_last_seen(self) -> timedelta:
        """Get time since device was last seen."""
        return datetime.now() - self.last_seen


class ADBManager:
    """
    Enhanced ADB device manager with auto-retry and monitoring.

    Features:
    - Automatic retry with exponential backoff
    - Device health tracking
    - Auto-reconnection for dropped devices
    - Background monitoring thread
    - Batch operations with error handling

    Example:
        >>> manager = ADBManager(retry_attempts=3, monitor_interval=10)
        >>> manager.start_monitoring()
        >>>
        >>> # Get device with auto-retry
        >>> device = manager.get_device_with_retry("10ACBE28M70044L")
        >>>
        >>> # Execute command with retry
        >>> success = manager.execute_with_retry(
        ...     "10ACBE28M70044L",
        ...     lambda serial: capture_screenshot(serial)
        ... )
    """

    def __init__(
        self,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        monitor_interval: float = 30.0,
        auto_restart_adb: bool = True,
        health_check_timeout: int = 5
    ):
        """
        Initialize ADB manager.

        Args:
            retry_attempts: Number of retry attempts for failed operations
            retry_delay: Initial delay between retries (seconds)
            retry_backoff: Backoff multiplier for retry delays
            monitor_interval: Interval for background monitoring (seconds)
            auto_restart_adb: Automatically restart ADB server on failures
            health_check_timeout: Timeout for health check operations (seconds)
        """
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.monitor_interval = monitor_interval
        self.auto_restart_adb = auto_restart_adb
        self.health_check_timeout = health_check_timeout

        # Device health tracking
        self._device_health: Dict[str, DeviceHealth] = {}
        self._health_lock = threading.Lock()

        # Monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_running = False
        self._monitor_lock = threading.Lock()

        # Callbacks
        self._on_device_connected: List[Callable[[str], None]] = []
        self._on_device_disconnected: List[Callable[[str], None]] = []
        self._on_device_reconnected: List[Callable[[str], None]] = []

        logger.info(
            f"ADBManager initialized: retry={retry_attempts}, "
            f"monitor_interval={monitor_interval}s"
        )

    def register_callback(
        self,
        event: str,
        callback: Callable[[str], None]
    ):
        """
        Register callback for device events.

        Args:
            event: Event type ('connected', 'disconnected', 'reconnected')
            callback: Callback function that takes device serial as argument
        """
        if event == 'connected':
            self._on_device_connected.append(callback)
        elif event == 'disconnected':
            self._on_device_disconnected.append(callback)
        elif event == 'reconnected':
            self._on_device_reconnected.append(callback)
        else:
            raise ValueError(f"Unknown event type: {event}")

    def scan_devices_with_retry(self) -> List[ADBDevice]:
        """
        Scan for ADB devices with automatic retry.

        Returns:
            List of discovered ADB devices
        """
        for attempt in range(self.retry_attempts):
            try:
                devices = scan_adb_devices()

                # Update health tracking
                with self._health_lock:
                    current_serials = {dev.serial for dev in devices}

                    # Mark existing devices as seen
                    for device in devices:
                        if device.serial not in self._device_health:
                            self._device_health[device.serial] = DeviceHealth(
                                serial=device.serial
                            )
                            logger.info(f"New device discovered: {device.serial}")
                            self._trigger_callbacks(self._on_device_connected, device.serial)

                        health = self._device_health[device.serial]
                        health.last_seen = datetime.now()

                        # Update state based on ADB status
                        if device.status == 'device':
                            if health.state != DeviceState.CONNECTED:
                                old_state = health.state
                                health.state = DeviceState.CONNECTED
                                health.uptime_start = datetime.now()
                                if old_state in [DeviceState.DISCONNECTED, DeviceState.OFFLINE]:
                                    health.total_reconnects += 1
                                    logger.success(f"Device reconnected: {device.serial}")
                                    self._trigger_callbacks(self._on_device_reconnected, device.serial)
                        elif device.status == 'offline':
                            health.state = DeviceState.OFFLINE
                        elif device.status == 'unauthorized':
                            health.state = DeviceState.UNAUTHORIZED

                    # Mark missing devices as disconnected
                    for serial, health in self._device_health.items():
                        if serial not in current_serials:
                            if health.state == DeviceState.CONNECTED:
                                health.state = DeviceState.DISCONNECTED
                                logger.warning(f"Device disconnected: {serial}")
                                self._trigger_callbacks(self._on_device_disconnected, serial)

                return devices

            except ADBError as e:
                logger.warning(f"Scan attempt {attempt + 1}/{self.retry_attempts} failed: {e}")

                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)
                    logger.info(f"Retrying in {delay:.1f}s...")
                    time.sleep(delay)

                    # Try restarting ADB server on repeated failures
                    if attempt == self.retry_attempts - 2 and self.auto_restart_adb:
                        logger.info("Attempting to restart ADB server...")
                        self._restart_adb_server()
                else:
                    logger.error(f"Failed to scan devices after {self.retry_attempts} attempts")
                    raise

        return []

    def get_device_with_retry(self, serial: str) -> Optional[ADBDevice]:
        """
        Get device info with automatic retry.

        Args:
            serial: Device serial number

        Returns:
            ADBDevice object or None if not found
        """
        for attempt in range(self.retry_attempts):
            try:
                device = get_device_info(serial)

                # Update health
                with self._health_lock:
                    if serial in self._device_health:
                        self._device_health[serial].mark_success()

                return device

            except ADBError as e:
                logger.warning(
                    f"Get device info attempt {attempt + 1}/{self.retry_attempts} "
                    f"failed for {serial}: {e}"
                )

                # Update health
                with self._health_lock:
                    if serial in self._device_health:
                        self._device_health[serial].mark_failure()

                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to get device info for {serial}")
                    return None

        return None

    def execute_with_retry(
        self,
        serial: str,
        operation: Callable[[str], any],
        operation_name: str = "operation"
    ) -> Optional[any]:
        """
        Execute an operation with automatic retry.

        Args:
            serial: Device serial number
            operation: Callable that takes serial and returns result
            operation_name: Name of operation for logging

        Returns:
            Operation result or None if all attempts failed
        """
        for attempt in range(self.retry_attempts):
            try:
                result = operation(serial)

                # Update health
                with self._health_lock:
                    if serial in self._device_health:
                        self._device_health[serial].mark_success()

                return result

            except Exception as e:
                logger.warning(
                    f"{operation_name} attempt {attempt + 1}/{self.retry_attempts} "
                    f"failed for {serial}: {e}"
                )

                # Update health
                with self._health_lock:
                    if serial in self._device_health:
                        self._device_health[serial].mark_failure()

                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)

                    # Check if device is still connected
                    if not check_device_connectivity(serial):
                        logger.warning(f"Device {serial} appears disconnected, attempting reconnection...")
                        if self._attempt_reconnect(serial):
                            logger.success(f"Device {serial} reconnected, retrying operation...")
                        else:
                            logger.error(f"Failed to reconnect device {serial}")
                            return None

                    time.sleep(delay)
                else:
                    logger.error(f"{operation_name} failed for {serial} after {self.retry_attempts} attempts")
                    return None

        return None

    def _attempt_reconnect(self, serial: str) -> bool:
        """
        Attempt to reconnect a device.

        Args:
            serial: Device serial number

        Returns:
            True if reconnection successful
        """
        with self._health_lock:
            if serial in self._device_health:
                self._device_health[serial].state = DeviceState.RECONNECTING

        try:
            # Try ADB reconnect command
            logger.info(f"Executing 'adb reconnect' for {serial}...")
            returncode, stdout, stderr = _run_adb_command(
                ['-s', serial, 'reconnect'],
                timeout=self.health_check_timeout
            )

            if returncode == 0:
                time.sleep(2)  # Wait for reconnection

                # Verify connection
                if check_device_connectivity(serial):
                    with self._health_lock:
                        if serial in self._device_health:
                            health = self._device_health[serial]
                            health.state = DeviceState.CONNECTED
                            health.total_reconnects += 1
                            health.consecutive_failures = 0

                    logger.success(f"Successfully reconnected {serial}")
                    self._trigger_callbacks(self._on_device_reconnected, serial)
                    return True

            return False

        except Exception as e:
            logger.error(f"Reconnection failed for {serial}: {e}")
            return False

    def _restart_adb_server(self):
        """Restart ADB server."""
        try:
            logger.info("Killing ADB server...")
            _run_adb_command(['kill-server'], timeout=5)
            time.sleep(1)

            logger.info("Starting ADB server...")
            _run_adb_command(['start-server'], timeout=10)
            time.sleep(2)

            logger.success("ADB server restarted")

        except Exception as e:
            logger.error(f"Failed to restart ADB server: {e}")

    def start_monitoring(self):
        """Start background device monitoring thread."""
        with self._monitor_lock:
            if self._monitor_running:
                logger.warning("Monitoring already running")
                return

            self._monitor_running = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="ADBMonitor"
            )
            self._monitor_thread.start()
            logger.info("Device monitoring started")

    def stop_monitoring(self):
        """Stop background device monitoring thread."""
        with self._monitor_lock:
            if not self._monitor_running:
                return

            self._monitor_running = False

        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            logger.info("Device monitoring stopped")

    def _monitor_loop(self):
        """Background monitoring loop."""
        logger.info(f"Monitor loop started (interval: {self.monitor_interval}s)")

        while self._monitor_running:
            try:
                # Scan devices
                devices = self.scan_devices_with_retry()

                # Check health of tracked devices
                with self._health_lock:
                    for serial, health in list(self._device_health.items()):
                        # Check if device hasn't been seen recently
                        if health.time_since_last_seen() > timedelta(seconds=self.monitor_interval * 2):
                            if health.state == DeviceState.CONNECTED:
                                logger.warning(
                                    f"Device {serial} not seen for "
                                    f"{health.time_since_last_seen().total_seconds():.0f}s"
                                )
                                health.state = DeviceState.DISCONNECTED
                                self._trigger_callbacks(self._on_device_disconnected, serial)

                        # Attempt reconnection for offline devices
                        if health.state in [DeviceState.OFFLINE, DeviceState.DISCONNECTED]:
                            if health.consecutive_failures < 5:  # Don't spam reconnect attempts
                                logger.info(f"Attempting to reconnect {serial}...")
                                self._attempt_reconnect(serial)

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            # Sleep with interrupt check
            for _ in range(int(self.monitor_interval * 10)):
                if not self._monitor_running:
                    break
                time.sleep(0.1)

        logger.info("Monitor loop stopped")

    def _trigger_callbacks(self, callbacks: List[Callable], serial: str):
        """Trigger registered callbacks."""
        for callback in callbacks:
            try:
                callback(serial)
            except Exception as e:
                logger.error(f"Callback error for {serial}: {e}")

    def get_device_health(self, serial: str) -> Optional[DeviceHealth]:
        """
        Get health status for a device.

        Args:
            serial: Device serial number

        Returns:
            DeviceHealth object or None if not tracked
        """
        with self._health_lock:
            return self._device_health.get(serial)

    def get_all_health_status(self) -> Dict[str, DeviceHealth]:
        """Get health status for all tracked devices."""
        with self._health_lock:
            return self._device_health.copy()

    def get_healthy_devices(self) -> List[str]:
        """Get list of healthy device serials."""
        with self._health_lock:
            return [
                serial for serial, health in self._device_health.items()
                if health.is_healthy()
            ]

    def reset_device_health(self, serial: str):
        """Reset health tracking for a device."""
        with self._health_lock:
            if serial in self._device_health:
                self._device_health[serial] = DeviceHealth(serial=serial)
                logger.info(f"Reset health tracking for {serial}")

    def __enter__(self):
        """Context manager entry."""
        self.start_monitoring()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop_monitoring()
