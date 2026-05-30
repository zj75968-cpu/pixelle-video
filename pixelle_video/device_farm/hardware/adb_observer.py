# -*- coding: utf-8 -*-
"""
ADB integration module for Android device observation.

Provides functionality to:
- Scan connected ADB devices
- Capture screenshots from devices
- Get device information (model, resolution, etc.)
- Check device connectivity status
"""

import subprocess
import re
from typing import List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from loguru import logger


class ADBError(Exception):
    """Base exception for ADB-related errors."""
    pass


@dataclass
class ADBDevice:
    """Represents an ADB-connected Android device."""
    serial: str
    status: str  # device, offline, unauthorized, etc.
    model: Optional[str] = None
    resolution: Optional[Tuple[int, int]] = None

    def __str__(self) -> str:
        return f"ADBDevice(serial={self.serial}, status={self.status}, model={self.model})"


def _run_adb_command(args: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """
    Execute an ADB command and return (returncode, stdout, stderr).

    Args:
        args: Command arguments (e.g., ['devices', '-l'])
        timeout: Command timeout in seconds

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    try:
        cmd = ['adb'] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace'
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        raise ADBError(f"ADB command timed out after {timeout}s: {' '.join(args)}")
    except FileNotFoundError:
        raise ADBError("ADB executable not found. Ensure Android Platform Tools are installed and in PATH.")
    except Exception as e:
        raise ADBError(f"Failed to execute ADB command: {e}")


def scan_adb_devices() -> List[ADBDevice]:
    """
    Scan for connected ADB devices.

    Returns:
        List of ADBDevice objects representing connected devices

    Raises:
        ADBError: If ADB command fails

    Example:
        >>> devices = scan_adb_devices()
        >>> for device in devices:
        ...     print(f"Found: {device.serial} - {device.status}")
    """
    returncode, stdout, stderr = _run_adb_command(['devices', '-l'])

    if returncode != 0:
        raise ADBError(f"ADB devices command failed: {stderr}")

    devices = []
    lines = stdout.strip().split('\n')

    # Skip the first line "List of devices attached"
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # Parse line format: "serial status [properties]"
        # Example: "emulator-5554 device product:sdk_gphone64_arm64 model:sdk_gphone64_arm64"
        parts = line.split()
        if len(parts) < 2:
            continue

        serial = parts[0]
        status = parts[1]

        # Extract model from properties if available
        model = None
        for part in parts[2:]:
            if part.startswith('model:'):
                model = part.split(':', 1)[1]
                break

        device = ADBDevice(serial=serial, status=status, model=model)
        devices.append(device)
        logger.debug(f"Discovered ADB device: {device}")

    logger.info(f"Found {len(devices)} ADB device(s)")
    return devices


def capture_screenshot(serial: str, output_path: Optional[str] = None) -> bytes:
    """
    Capture screenshot from an ADB device.

    Args:
        serial: Device serial number
        output_path: Optional path to save screenshot PNG file

    Returns:
        Screenshot image data as bytes (PNG format)

    Raises:
        ADBError: If screenshot capture fails

    Example:
        >>> img_data = capture_screenshot("emulator-5554")
        >>> with open("screen.png", "wb") as f:
        ...     f.write(img_data)
    """
    # Use exec-out to get raw binary data without line ending conversion
    returncode, stdout_text, stderr = _run_adb_command(
        ['-s', serial, 'exec-out', 'screencap', '-p'],
        timeout=30
    )

    if returncode != 0:
        raise ADBError(f"Screenshot capture failed for {serial}: {stderr}")

    # Convert text output back to bytes (subprocess.run with text=True decoded it)
    # We need to re-encode and handle it as binary
    try:
        # Re-run with binary mode for screenshot
        cmd = ['adb', '-s', serial, 'exec-out', 'screencap', '-p']
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30
        )

        if result.returncode != 0:
            raise ADBError(f"Screenshot capture failed for {serial}: {result.stderr.decode('utf-8', errors='replace')}")

        img_data = result.stdout

        if not img_data or len(img_data) < 100:
            raise ADBError(f"Screenshot data is empty or too small for {serial}")

        # Verify PNG header
        if not img_data.startswith(b'\x89PNG'):
            raise ADBError(f"Screenshot data is not a valid PNG for {serial}")

        # Save to file if path provided
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(img_data)
            logger.info(f"Screenshot saved to {output_path}")

        logger.debug(f"Captured screenshot from {serial}: {len(img_data)} bytes")
        return img_data

    except subprocess.TimeoutExpired:
        raise ADBError(f"Screenshot capture timed out for {serial}")
    except Exception as e:
        raise ADBError(f"Failed to capture screenshot from {serial}: {e}")


def get_device_info(serial: str) -> ADBDevice:
    """
    Get detailed information about an ADB device.

    Args:
        serial: Device serial number

    Returns:
        ADBDevice object with populated model and resolution

    Raises:
        ADBError: If device info retrieval fails

    Example:
        >>> info = get_device_info("emulator-5554")
        >>> print(f"Model: {info.model}, Resolution: {info.resolution}")
    """
    # Get device model
    model = None
    returncode, stdout, stderr = _run_adb_command(
        ['-s', serial, 'shell', 'getprop', 'ro.product.model']
    )
    if returncode == 0:
        model = stdout.strip()

    # Get screen resolution
    resolution = None
    returncode, stdout, stderr = _run_adb_command(
        ['-s', serial, 'shell', 'wm', 'size']
    )
    if returncode == 0:
        # Parse output like "Physical size: 1080x2400"
        match = re.search(r'(\d+)x(\d+)', stdout)
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            resolution = (width, height)

    # Check device status
    devices = scan_adb_devices()
    status = 'offline'
    for dev in devices:
        if dev.serial == serial:
            status = dev.status
            break

    device = ADBDevice(
        serial=serial,
        status=status,
        model=model,
        resolution=resolution
    )

    logger.info(f"Device info for {serial}: {device}")
    return device


def check_device_connectivity(serial: str) -> bool:
    """
    Check if a device is connected and responsive.

    Args:
        serial: Device serial number

    Returns:
        True if device is connected and status is 'device', False otherwise

    Example:
        >>> if check_device_connectivity("emulator-5554"):
        ...     print("Device is ready")
    """
    try:
        devices = scan_adb_devices()
        for dev in devices:
            if dev.serial == serial and dev.status == 'device':
                return True
        return False
    except ADBError as e:
        logger.warning(f"Failed to check connectivity for {serial}: {e}")
        return False


# Convenience function for backward compatibility
def get_screen_resolution(serial: str) -> Optional[Tuple[int, int]]:
    """
    Get screen resolution of a device.

    Args:
        serial: Device serial number

    Returns:
        Tuple of (width, height) or None if failed
    """
    try:
        device = get_device_info(serial)
        return device.resolution
    except ADBError:
        return None
