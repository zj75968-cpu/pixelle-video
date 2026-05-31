#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Device Calibration Script - Step 1

This script helps you calibrate your device by:
1. Connecting to the device via ADB and CH9329
2. Capturing screenshots
3. Saving UI point coordinates
4. Testing the calibration points

Usage:
    python scripts/01_calibrate_device.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware.adb_observer import (
    scan_adb_devices,
    capture_screenshot,
    get_device_info
)
from pixelle_video.device_farm.hardware.ch9329_controller import (
    scan_com_ports,
    connect_ch9329,
    test_tap
)
from pixelle_video.utils.ch9329 import CH9329Controller

# Configuration
PHONE_ID = "vivo_v2199a_001"
ADB_SERIAL = "10ACBE28M70044L"
CH9329_PORT = "COM5"
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400

# Output directory for screenshots
SCREENSHOTS_DIR = project_root / "runtime" / "calibration_screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def check_hardware():
    """Step 1: Check hardware connectivity."""
    logger.info("=" * 60)
    logger.info("Step 1: Hardware Connectivity Check")
    logger.info("=" * 60)

    # Check ADB
    logger.info("\n[ADB Check]")
    devices = scan_adb_devices()

    if not devices:
        logger.error("No ADB devices found!")
        logger.info("Please:")
        logger.info("  1. Connect device via USB")
        logger.info("  2. Enable USB debugging")
        logger.info("  3. Accept USB debugging prompt on device")
        return False

    device_found = False
    for device in devices:
        logger.info(f"  Found: {device}")
        if device.serial == ADB_SERIAL:
            device_found = True
            logger.success(f"  ✓ Target device found: {ADB_SERIAL}")

    if not device_found:
        logger.warning(f"  Target device {ADB_SERIAL} not found")
        logger.info(f"  Available devices: {[d.serial for d in devices]}")
        return False

    # Check CH9329
    logger.info("\n[CH9329 Check]")
    ports = scan_com_ports()

    if not ports:
        logger.error("No COM ports found!")
        return False

    port_found = False
    for port, desc, hwid in ports:
        logger.info(f"  Found: {port} - {desc}")
        if port == CH9329_PORT:
            port_found = True
            logger.success(f"  ✓ Target port found: {CH9329_PORT}")

    if not port_found:
        logger.warning(f"  Target port {CH9329_PORT} not found")
        logger.info(f"  Available ports: {[p[0] for p in ports]}")
        return False

    # Test CH9329 connection
    logger.info("\n[CH9329 Connection Test]")
    ser = connect_ch9329(CH9329_PORT)
    if ser:
        logger.success(f"  ✓ Successfully connected to {CH9329_PORT}")
        ser.close()
    else:
        logger.error(f"  ✗ Failed to connect to {CH9329_PORT}")
        return False

    logger.success("\n✓ All hardware checks passed!")
    return True


def capture_reference_screenshots():
    """Step 2: Capture reference screenshots for calibration."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: Capture Reference Screenshots")
    logger.info("=" * 60)

    screens = [
        ("home", "Navigate to app home screen, then press Enter..."),
        ("publish_menu", "Open publish menu, then press Enter..."),
        ("album_view", "Open album selection, then press Enter..."),
        ("edit_screen", "Open edit screen, then press Enter..."),
    ]

    captured = {}

    for screen_name, instruction in screens:
        logger.info(f"\n[{screen_name}]")
        logger.info(f"  {instruction}")

        try:
            input()  # Wait for user
        except KeyboardInterrupt:
            logger.warning("\n  Skipped")
            continue

        try:
            output_path = SCREENSHOTS_DIR / f"{screen_name}.png"
            img_data = capture_screenshot(ADB_SERIAL, str(output_path))
            logger.success(f"  ✓ Screenshot saved: {output_path}")
            captured[screen_name] = output_path
        except Exception as e:
            logger.error(f"  ✗ Failed to capture: {e}")

    logger.info(f"\n✓ Captured {len(captured)} screenshots")
    logger.info(f"  Location: {SCREENSHOTS_DIR}")
    logger.info("\nNext: Open screenshots in an image viewer to find coordinates")

    return captured


def interactive_calibration():
    """Step 3: Interactive point calibration."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Interactive Point Calibration")
    logger.info("=" * 60)

    logger.info("\nOpen your screenshots in an image viewer (e.g., Paint, GIMP)")
    logger.info("Hover over UI elements to get pixel coordinates")
    logger.info(f"Screenshots location: {SCREENSHOTS_DIR}")

    logger.info("\nCommands:")
    logger.info("  save <name> <x> <y> - Save a calibration point")
    logger.info("  test <x> <y>        - Test tap at coordinates")
    logger.info("  list                - List saved points")
    logger.info("  done                - Finish calibration")

    # Initialize CH9329 controller
    controller = CH9329Controller(port=CH9329_PORT)
    if not controller.connect():
        logger.error("Failed to connect to CH9329")
        return {}

    points = {}

    try:
        while True:
            try:
                cmd = input("\ncalibrate> ").strip()

                if not cmd:
                    continue

                if cmd == "done":
                    break

                elif cmd == "list":
                    if not points:
                        logger.info("  No points saved yet")
                    else:
                        logger.info(f"  Saved {len(points)} point(s):")
                        for name, (x, y) in points.items():
                            x_ratio = x / SCREEN_WIDTH
                            y_ratio = y / SCREEN_HEIGHT
                            logger.info(f"    {name}: ({x}, {y}) = ({x_ratio:.3f}, {y_ratio:.3f})")

                elif cmd.startswith("save "):
                    parts = cmd.split()
                    if len(parts) != 4:
                        logger.error("  Usage: save <name> <x> <y>")
                        continue

                    name = parts[1]
                    x = int(parts[2])
                    y = int(parts[3])

                    if x < 0 or x > SCREEN_WIDTH or y < 0 or y > SCREEN_HEIGHT:
                        logger.error(f"  Coordinates out of range (0-{SCREEN_WIDTH}, 0-{SCREEN_HEIGHT})")
                        continue

                    points[name] = (x, y)
                    x_ratio = x / SCREEN_WIDTH
                    y_ratio = y / SCREEN_HEIGHT
                    logger.success(f"  ✓ Saved '{name}': ({x}, {y}) = ({x_ratio:.3f}, {y_ratio:.3f})")

                elif cmd.startswith("test "):
                    parts = cmd.split()
                    if len(parts) != 3:
                        logger.error("  Usage: test <x> <y>")
                        continue

                    x = int(parts[1])
                    y = int(parts[2])
                    x_ratio = x / SCREEN_WIDTH
                    y_ratio = y / SCREEN_HEIGHT

                    logger.info(f"  Testing tap at ({x}, {y}) = ({x_ratio:.3f}, {y_ratio:.3f})...")
                    logger.warning("  Watch your device screen!")

                    if controller.click(x_ratio, y_ratio):
                        logger.success("  ✓ Tap executed")
                    else:
                        logger.error("  ✗ Tap failed")

                else:
                    logger.warning(f"  Unknown command: {cmd}")

            except KeyboardInterrupt:
                logger.info("\n  Use 'done' to finish")
                continue
            except ValueError as e:
                logger.error(f"  Invalid input: {e}")
                continue

    finally:
        controller.disconnect()

    return points


def save_calibration_profile(points):
    """Step 4: Save calibration profile to YAML."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 4: Save Calibration Profile")
    logger.info("=" * 60)

    if not points:
        logger.warning("No points to save")
        return None

    profile_dir = project_root / "config" / "calibration_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profile_dir / f"{PHONE_ID}_profile.yaml"

    # Generate YAML content
    yaml_content = f"""# Calibration Profile for {PHONE_ID}
# Generated: 2026-05-30
# Device: Vivo V2199A

profile_id: "{PHONE_ID}_default"
phone_id: "{PHONE_ID}"
screen:
  width: {SCREEN_WIDTH}
  height: {SCREEN_HEIGHT}
  safe_top: 100
  safe_bottom: 120
  navigation_mode: "gesture"

points:
"""

    for name, (x, y) in points.items():
        x_ratio = x / SCREEN_WIDTH
        y_ratio = y / SCREEN_HEIGHT
        yaml_content += f"""  - name: "{name}"
    type: "absolute"
    x: {x}
    y: {y}
    x_ratio: {x_ratio:.4f}
    y_ratio: {y_ratio:.4f}
    description: "Calibrated point for {name}"
"""

    profile_path.write_text(yaml_content, encoding='utf-8')
    logger.success(f"✓ Profile saved: {profile_path}")
    logger.info(f"  Points: {len(points)}")

    return profile_path


def main():
    """Main calibration workflow."""
    logger.info("=" * 60)
    logger.info("Device Calibration Wizard")
    logger.info("=" * 60)
    logger.info(f"Device: {PHONE_ID}")
    logger.info(f"ADB Serial: {ADB_SERIAL}")
    logger.info(f"CH9329 Port: {CH9329_PORT}")
    logger.info(f"Screen: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")

    # Step 1: Check hardware
    if not check_hardware():
        logger.error("\nHardware check failed. Please fix issues and try again.")
        return 1

    # Step 2: Capture screenshots
    logger.info("\n" + "=" * 60)
    logger.info("Ready to capture reference screenshots?")
    logger.info("Press Enter to continue, or Ctrl+C to skip...")
    logger.info("=" * 60)

    try:
        input()
        captured = capture_reference_screenshots()
    except KeyboardInterrupt:
        logger.info("\nSkipped screenshot capture")
        captured = {}

    # Step 3: Interactive calibration
    logger.info("\n" + "=" * 60)
    logger.info("Ready for interactive calibration?")
    logger.info("Press Enter to continue, or Ctrl+C to skip...")
    logger.info("=" * 60)

    try:
        input()
        points = interactive_calibration()
    except KeyboardInterrupt:
        logger.info("\nSkipped calibration")
        points = {}

    # Step 4: Save profile
    if points:
        profile_path = save_calibration_profile(points)

        logger.info("\n" + "=" * 60)
        logger.info("Calibration Complete!")
        logger.info("=" * 60)
        logger.success(f"✓ Profile saved: {profile_path}")
        logger.info(f"✓ Calibrated {len(points)} points")
        logger.info("\nNext steps:")
        logger.info("  1. Update config/devices.yaml to reference this profile")
        logger.info("  2. Run: python scripts/02_test_automation.py")
    else:
        logger.warning("\nNo calibration points saved")

    return 0


if __name__ == "__main__":
    sys.exit(main())
