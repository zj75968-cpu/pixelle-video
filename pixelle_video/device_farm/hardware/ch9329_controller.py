# -*- coding: utf-8 -*-
"""
CH9329 Device Farm Hardware Controller

Provides COM port scanning and CH9329 device connection management
for the device farm automation system.
"""
import time
from typing import List, Optional, Tuple
from loguru import logger
import serial
import serial.tools.list_ports


def scan_com_ports() -> List[Tuple[str, str, str]]:
    """
    Scan all available COM ports on the system.

    Returns:
        List of tuples (port, description, hwid) for each available COM port.
        Example: [('COM3', 'USB Serial Port', 'USB VID:PID=1A86:7523')]
    """
    try:
        ports = serial.tools.list_ports.comports()
        available_ports = [(port.device, port.description, port.hwid) for port in ports]

        logger.info(f"Found {len(available_ports)} COM port(s)")
        for port, desc, hwid in available_ports:
            logger.debug(f"  {port}: {desc} [{hwid}]")

        return available_ports
    except Exception as e:
        logger.error(f"Failed to scan COM ports: {e}")
        return []


def connect_ch9329(port: str, baudrate: int = 9600, timeout: float = 0.5) -> Optional[serial.Serial]:
    """
    Connect to CH9329 device on specified COM port.

    Args:
        port: COM port name (e.g., 'COM3')
        baudrate: Serial baudrate (default: 9600)
        timeout: Serial timeout in seconds (default: 0.5)

    Returns:
        Serial connection object if successful, None otherwise.
    """
    try:
        logger.info(f"Connecting to CH9329 on {port} at {baudrate} baud...")
        ser = serial.Serial(port, baudrate, timeout=timeout)
        logger.info(f"Successfully connected to {port}")
        return ser
    except serial.SerialException as e:
        logger.error(f"Failed to connect to {port}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error connecting to {port}: {e}")
        return None


def test_tap(ser: Optional[serial.Serial], x_ratio: float = 0.5, y_ratio: float = 0.5) -> bool:
    """
    Send a test tap command to verify CH9329 connectivity.

    Uses relative mouse control with calibration to perform a tap at the
    specified screen ratio coordinates.

    Args:
        ser: Serial connection object
        x_ratio: X coordinate as ratio of screen width (0.0-1.0, default: 0.5)
        y_ratio: Y coordinate as ratio of screen height (0.0-1.0, default: 0.5)

    Returns:
        True if tap command sent successfully, False otherwise.
    """
    if not ser or not ser.is_open:
        logger.error("Serial connection not available for test tap")
        return False

    try:
        # Screen resolution preset (1080x2400)
        screen_width = 1080
        screen_height = 2400

        logger.info(f"Sending test tap at ({x_ratio}, {y_ratio})...")

        # Step 1: Calibrate mouse to (0, 0)
        logger.debug("Calibrating mouse to origin...")
        for _ in range(30):
            packet = _build_rel_mouse_packet(0x00, -120, -120, 0)
            ser.write(packet)
            ser.flush()
            time.sleep(0.005)

        # Step 2: Move to target position
        tx = int(x_ratio * screen_width)
        ty = int(y_ratio * screen_height)
        logger.debug(f"Moving to pixel position ({tx}, {ty})...")

        # Move X axis
        step_x = 100 if tx >= 0 else -100
        for _ in range(abs(tx) // 100):
            packet = _build_rel_mouse_packet(0x00, step_x, 0, 0)
            ser.write(packet)
            ser.flush()
            time.sleep(0.008)
        if abs(tx) % 100 != 0:
            rem_x = (abs(tx) % 100) * (1 if tx >= 0 else -1)
            packet = _build_rel_mouse_packet(0x00, rem_x, 0, 0)
            ser.write(packet)
            ser.flush()
            time.sleep(0.008)

        # Move Y axis
        step_y = 100 if ty >= 0 else -100
        for _ in range(abs(ty) // 100):
            packet = _build_rel_mouse_packet(0x00, 0, step_y, 0)
            ser.write(packet)
            ser.flush()
            time.sleep(0.008)
        if abs(ty) % 100 != 0:
            rem_y = (abs(ty) % 100) * (1 if ty >= 0 else -1)
            packet = _build_rel_mouse_packet(0x00, 0, rem_y, 0)
            ser.write(packet)
            ser.flush()
            time.sleep(0.008)

        time.sleep(0.1)

        # Step 3: Click (press and release)
        logger.debug("Executing click...")
        packet = _build_rel_mouse_packet(0x01, 0, 0, 0)  # Press
        ser.write(packet)
        ser.flush()
        time.sleep(0.08)

        packet = _build_rel_mouse_packet(0x00, 0, 0, 0)  # Release
        ser.write(packet)
        ser.flush()
        time.sleep(0.1)

        logger.info("Test tap completed successfully")
        return True

    except serial.SerialException as e:
        logger.error(f"Serial communication error during test tap: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during test tap: {e}")
        return False


def _build_rel_mouse_packet(buttons: int, x_rel: int, y_rel: int, wheel: int) -> bytes:
    """
    Build CH9329 relative mouse control packet.

    Args:
        buttons: Button state (0x00=none, 0x01=left, 0x02=right)
        x_rel: Relative X movement (-127 to 127)
        y_rel: Relative Y movement (-127 to 127)
        wheel: Wheel movement (-127 to 127)

    Returns:
        Complete CH9329 protocol packet as bytes.
    """
    # Packet structure: HEAD(2) + ADDR(1) + CMD(1) + LEN(1) + DATA(5) + CHECKSUM(1)
    head = bytes([0x57, 0xAB])
    addr = bytes([0x00])
    cmd = bytes([0x05])  # Mouse command

    # Data: [0x01 (relative mouse flag), buttons, x_rel, y_rel, wheel]
    x_b = x_rel & 0xFF
    y_b = y_rel & 0xFF
    wheel_b = wheel & 0xFF
    data = bytes([0x01, buttons, x_b, y_b, wheel_b])

    length = bytes([len(data)])

    # Checksum: sum of all bytes except HEAD
    sum_data = 0x57 + 0xAB + 0x00 + 0x05 + len(data) + sum(data)
    checksum = bytes([sum_data & 0xFF])

    return head + addr + cmd + length + data + checksum
