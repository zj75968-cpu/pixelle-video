# -*- coding: utf-8 -*-
"""Device farm hardware controllers."""

from .adb_observer import (
    scan_adb_devices,
    capture_screenshot,
    get_device_info,
    check_device_connectivity,
    get_screen_resolution,
    ADBDevice,
    ADBError,
)

from .ch9329_controller import (
    scan_com_ports,
    connect_ch9329,
    test_tap,
)

__all__ = [
    # ADB functions and classes
    "scan_adb_devices",
    "capture_screenshot",
    "get_device_info",
    "check_device_connectivity",
    "get_screen_resolution",
    "ADBDevice",
    "ADBError",
    # CH9329 functions
    "scan_com_ports",
    "connect_ch9329",
    "test_tap",
]
