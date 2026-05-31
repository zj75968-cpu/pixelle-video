#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Device Calibration with Auto-Retry and Health Monitoring

Improvements over 01_calibrate_device.py:
- Automatic retry on ADB failures
- Device health monitoring during calibration
- Auto-reconnection on device drops
- Better error recovery
- Progress tracking

Usage:
    python scripts/05_enhanced_calibrate.py --device vivo_v2199a_001
    python scripts/05_enhanced_calibrate.py --device vivo_v2199a_002 --reference vivo_v2199a_001
"""

import sys
import argparse
from pathlib import Path
import yaml
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware import (
    ADBManager,
    DeviceState,
    capture_screenshot
)
from pixelle_video.utils.ch9329 import CH9329Controller


def load_device_config(phone_id):
    """Load device configuration."""
    config_path = project_root / "config" / "devices.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    for device in config.get('devices', []):
        if device['phone_id'] == phone_id:
            return device

    raise ValueError(f"Device not found: {phone_id}")


def check_hardware_with_retry(device_config, adb_manager):
    """Check hardware connectivity with automatic retry."""
    logger.info("=" * 60)
    logger.info("Hardware Connectivity Check (with auto-retry)")
    logger.info("=" * 60)

    # Check ADB with retry
    logger.info("\n[ADB Check]")
    devices = adb_manager.scan_devices_with_retry()

    if not devices:
        logger.error("No ADB devices found after retries!")
        logger.info("Please:")
        logger.info("  1. Connect device via USB")
        logger.info("  2. Enable USB debugging")
        logger.info("  3. Accept USB debugging prompt on device")
        return False

    target_serial = device_config['adb_serial']
    device_found = False

    for device in devices:
        logger.info(f"  Found: {device}")
        if device.serial == target_serial:
            device_found = True
            logger.success(f"  ✓ Target device found: {target_serial}")

            # Get detailed info with retry
            detailed = adb_manager.get_device_with_retry(target_serial)
            if detailed and detailed.resolution:
                logger.info(f"  Resolution: {detailed.resolution[0]}x{detailed.resolution[1]}")

    if not device_found:
        logger.warning(f"  Target device {target_serial} not found")
        logger.info(f"  Available devices: {[d.serial for d in devices]}")
        return False

    # Check device health
    health = adb_manager.get_device_health(target_serial)
    if health:
        logger.info(f"\n[Device Health]")
        logger.info(f"  State: {health.state.value}")
        logger.info(f"  Healthy: {'Yes' if health.is_healthy() else 'No'}")

    # Check CH9329
    logger.info("\n[CH9329 Check]")
    from pixelle_video.device_farm.hardware import scan_com_ports, connect_ch9329

    ports = scan_com_ports()

    if not ports:
        logger.error("No COM ports found!")
        return False

    ch9329_port = device_config['ch9329_port']
    port_found = False

    for port, desc, hwid in ports:
        logger.info(f"  Found: {port} - {desc}")
        if port == ch9329_port:
            port_found = True
            logger.success(f"  ✓ Target port found: {ch9329_port}")

    if not port_found:
        logger.warning(f"  Target port {ch9329_port} not found")
        logger.info(f"  Available ports: {[p[0] for p in ports]}")
        return False

    # Test CH9329 connection
    logger.info("\n[CH9329 Connection Test]")
    ser = connect_ch9329(ch9329_port)
    if ser:
        logger.success(f"  ✓ Successfully connected to {ch9329_port}")
        ser.close()
    else:
        logger.error(f"  ✗ Failed to connect to {ch9329_port}")
        return False

    logger.success("\n✓ All hardware checks passed!")
    return True


def capture_screenshots_with_retry(device_config, adb_manager, screenshots_dir):
    """Capture reference screenshots with automatic retry."""
    logger.info("\n" + "=" * 60)
    logger.info("Capture Reference Screenshots (with auto-retry)")
    logger.info("=" * 60)

    screens = [
        ("home", "Navigate to app home screen, then press Enter..."),
        ("publish_menu", "Open publish menu, then press Enter..."),
        ("album_view", "Open album selection, then press Enter..."),
        ("edit_screen", "Open edit screen, then press Enter..."),
    ]

    captured = {}
    serial = device_config['adb_serial']

    for screen_name, instruction in screens:
        logger.info(f"\n[{screen_name}]")
        logger.info(f"  {instruction}")

        try:
            input()  # Wait for user
        except KeyboardInterrupt:
            logger.warning("\n  Skipped")
            continue

        # Capture with retry
        output_path = screenshots_dir / f"{screen_name}.png"

        result = adb_manager.execute_with_retry(
            serial,
            lambda s: capture_screenshot(s, str(output_path)),
            operation_name=f"Screenshot capture ({screen_name})"
        )

        if result:
            logger.success(f"  ✓ Screenshot saved: {output_path}")
            captured[screen_name] = output_path
        else:
            logger.error(f"  ✗ Failed to capture after retries")

            # Check device health
            health = adb_manager.get_device_health(serial)
            if health and health.state != DeviceState.CONNECTED:
                logger.warning(f"  Device state: {health.state.value}")
                logger.info("  Waiting for device to reconnect...")
                time.sleep(5)

    logger.info(f"\n✓ Captured {len(captured)} screenshots")
    logger.info(f"  Location: {screenshots_dir}")

    return captured


def interactive_calibration_with_monitoring(device_config, adb_manager, screenshots_dir):
    """Interactive calibration with device health monitoring."""
    logger.info("\n" + "=" * 60)
    logger.info("Interactive Point Calibration (with monitoring)")
    logger.info("=" * 60)

    logger.info("\nOpen your screenshots in an image viewer (e.g., Paint, GIMP)")
    logger.info("Hover over UI elements to get pixel coordinates")
    logger.info(f"Screenshots location: {screenshots_dir}")

    logger.info("\nCommands:")
    logger.info("  save <name> <x> <y> - Save a calibration point")
    logger.info("  test <x> <y>        - Test tap at coordinates")
    logger.info("  list                - List saved points")
    logger.info("  health              - Check device health")
    logger.info("  done                - Finish calibration")

    # Initialize CH9329 controller
    controller = CH9329Controller(port=device_config['ch9329_port'])
    controller.screen_width = device_config['screen']['width']
    controller.screen_height = device_config['screen']['height']

    if not controller.connect():
        logger.error("Failed to connect to CH9329")
        return {}

    points = {}
    serial = device_config['adb_serial']

    try:
        while True:
            try:
                cmd = input("\ncalibrate> ").strip()

                if not cmd:
                    continue

                if cmd == "done":
                    break

                elif cmd == "health":
                    # Display device health
                    health = adb_manager.get_device_health(serial)
                    if health:
                        logger.info(f"  State: {health.state.value}")
                        logger.info(f"  Consecutive failures: {health.consecutive_failures}")
                        logger.info(f"  Total reconnects: {health.total_reconnects}")
                        logger.info(f"  Healthy: {'Yes' if health.is_healthy() else 'No'}")
                    else:
                        logger.warning("  No health data available")

                elif cmd == "list":
                    if not points:
                        logger.info("  No points saved yet")
                    else:
                        logger.info(f"  Saved {len(points)} point(s):")
                        for name, (x, y) in points.items():
                            x_ratio = x / device_config['screen']['width']
                            y_ratio = y / device_config['screen']['height']
                            logger.info(f"    {name}: ({x}, {y}) = ({x_ratio:.3f}, {y_ratio:.3f})")

                elif cmd.startswith("save "):
                    parts = cmd.split()
                    if len(parts) != 4:
                        logger.error("  Usage: save <name> <x> <y>")
                        continue

                    name = parts[1]
                    x = int(parts[2])
                    y = int(parts[3])

                    if x < 0 or x > device_config['screen']['width'] or \
                       y < 0 or y > device_config['screen']['height']:
                        logger.error(
                            f"  Coordinates out of range "
                            f"(0-{device_config['screen']['width']}, "
                            f"0-{device_config['screen']['height']})"
                        )
                        continue

                    points[name] = (x, y)
                    x_ratio = x / device_config['screen']['width']
                    y_ratio = y / device_config['screen']['height']
                    logger.success(f"  ✓ Saved '{name}': ({x}, {y}) = ({x_ratio:.3f}, {y_ratio:.3f})")

                elif cmd.startswith("test "):
                    parts = cmd.split()
                    if len(parts) != 3:
                        logger.error("  Usage: test <x> <y>")
                        continue

                    x = int(parts[1])
                    y = int(parts[2])
                    x_ratio = x / device_config['screen']['width']
                    y_ratio = y / device_config['screen']['height']

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


def save_calibration_profile(device_config, points):
    """Save calibration profile to YAML."""
    logger.info("\n" + "=" * 60)
    logger.info("Save Calibration Profile")
    logger.info("=" * 60)

    if not points:
        logger.warning("No points to save")
        return None

    phone_id = device_config['phone_id']
    profile_dir = project_root / "config" / "calibration_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profile_dir / f"{phone_id}_default.yaml"

    # Build profile data
    profile = {
        'profile_id': f"{phone_id}_default",
        'phone_id': phone_id,
        'screen': {
            'width': device_config['screen']['width'],
            'height': device_config['screen']['height'],
            'safe_top': 100,
            'safe_bottom': 120,
            'navigation_mode': 'gesture'
        },
        'points': [],
        'created_at': datetime.now().isoformat(),
        'metadata': {
            'device_name': device_config['name'],
            'model': device_config['metadata'].get('model'),
            'calibration_method': 'enhanced_interactive'
        }
    }

    for name, (x, y) in points.items():
        x_ratio = x / device_config['screen']['width']
        y_ratio = y / device_config['screen']['height']

        profile['points'].append({
            'name': name,
            'type': 'absolute',
            'x': x,
            'y': y,
            'x_ratio': round(x_ratio, 4),
            'y_ratio': round(y_ratio, 4),
            'description': f"Calibrated point for {name}"
        })

    with open(profile_path, 'w', encoding='utf-8') as f:
        yaml.dump(profile, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.success(f"✓ Profile saved: {profile_path}")
    logger.info(f"  Points: {len(points)}")

    return profile_path


def main():
    """Main calibration workflow with enhanced error handling."""
    parser = argparse.ArgumentParser(
        description='Enhanced device calibration with auto-retry and monitoring'
    )
    parser.add_argument('--device', required=True, help='Target device phone_id')
    parser.add_argument('--reference', help='Reference device phone_id to copy from')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Enhanced Device Calibration Wizard")
    logger.info("=" * 60)

    # Load device config
    try:
        device_config = load_device_config(args.device)
        logger.info(f"\nTarget Device: {device_config['name']} ({args.device})")
        logger.info(f"  ADB Serial: {device_config['adb_serial']}")
        logger.info(f"  CH9329 Port: {device_config['ch9329_port']}")
        logger.info(f"  Screen: {device_config['screen']['width']}x{device_config['screen']['height']}")
    except Exception as e:
        logger.error(f"Failed to load device config: {e}")
        return 1

    # Initialize ADB manager with monitoring
    adb_manager = ADBManager(
        retry_attempts=3,
        retry_delay=2.0,
        retry_backoff=2.0,
        monitor_interval=20.0,
        auto_restart_adb=True
    )

    # Start monitoring
    adb_manager.start_monitoring()

    try:
        # Step 1: Check hardware with retry
        if not check_hardware_with_retry(device_config, adb_manager):
            logger.error("\nHardware check failed. Please fix issues and try again.")
            return 1

        # Screenshots directory
        screenshots_dir = project_root / "runtime" / "calibration_screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Step 2: Capture screenshots with retry
        logger.info("\n" + "=" * 60)
        logger.info("Ready to capture reference screenshots?")
        logger.info("Press Enter to continue, or Ctrl+C to skip...")
        logger.info("=" * 60)

        try:
            input()
            captured = capture_screenshots_with_retry(
                device_config,
                adb_manager,
                screenshots_dir
            )
        except KeyboardInterrupt:
            logger.info("\nSkipped screenshot capture")
            captured = {}

        # Step 3: Interactive calibration with monitoring
        logger.info("\n" + "=" * 60)
        logger.info("Ready for interactive calibration?")
        logger.info("Press Enter to continue, or Ctrl+C to skip...")
        logger.info("=" * 60)

        try:
            input()
            points = interactive_calibration_with_monitoring(
                device_config,
                adb_manager,
                screenshots_dir
            )
        except KeyboardInterrupt:
            logger.info("\nSkipped calibration")
            points = {}

        # Step 4: Save profile
        if points:
            profile_path = save_calibration_profile(device_config, points)

            logger.info("\n" + "=" * 60)
            logger.info("Calibration Complete!")
            logger.info("=" * 60)
            logger.success(f"✓ Profile saved: {profile_path}")
            logger.info(f"✓ Calibrated {len(points)} points")

            # Display final health status
            health = adb_manager.get_device_health(device_config['adb_serial'])
            if health:
                logger.info(f"\nFinal device health:")
                logger.info(f"  State: {health.state.value}")
                logger.info(f"  Total reconnects: {health.total_reconnects}")
                logger.info(f"  Failures: {health.consecutive_failures}")

            logger.info("\nNext steps:")
            logger.info("  1. Test automation:")
            logger.info(f"     python scripts/02_test_automation.py --device {args.device}")
        else:
            logger.warning("\nNo calibration points saved")

    finally:
        # Stop monitoring
        adb_manager.stop_monitoring()

    return 0


if __name__ == "__main__":
    import time
    sys.exit(main())
