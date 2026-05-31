#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Device Farm Management CLI

Centralized tool for managing multiple devices in your device farm.

Usage:
    python scripts/device_manager.py list
    python scripts/device_manager.py status
    python scripts/device_manager.py test <phone_id>
    python scripts/device_manager.py calibrate <phone_id>
    python scripts/device_manager.py enable <phone_id>
    python scripts/device_manager.py disable <phone_id>
"""

import sys
import argparse
from pathlib import Path
import yaml
from datetime import datetime
from typing import List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware.adb_observer import (
    scan_adb_devices,
    check_device_connectivity
)
from pixelle_video.device_farm.hardware.ch9329_controller import (
    scan_com_ports,
    connect_ch9329
)

DEVICES_CONFIG = project_root / "config" / "devices.yaml"


def load_devices() -> List[Dict]:
    """Load all devices from configuration."""
    if not DEVICES_CONFIG.exists():
        return []

    with open(DEVICES_CONFIG, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config.get('devices', [])


def save_devices(devices: List[Dict]):
    """Save devices to configuration."""
    config = {
        'devices': devices,
        'last_modified': datetime.now().isoformat()
    }

    with open(DEVICES_CONFIG, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def cmd_list(args):
    """List all configured devices."""
    devices = load_devices()

    if not devices:
        logger.warning("No devices configured")
        logger.info("Add a device with: python scripts/00_add_new_device.py")
        return 0

    logger.info("=" * 80)
    logger.info(f"Device Farm - {len(devices)} Device(s)")
    logger.info("=" * 80)

    for device in devices:
        status_color = {
            'idle': '🟢',
            'running': '🔵',
            'disabled': '⚫',
            'offline': '🔴',
            'needs_calibration': '🟡'
        }.get(device['status'], '⚪')

        logger.info(f"\n{status_color} {device['phone_id']}")
        logger.info(f"   Name: {device['name']}")
        logger.info(f"   ADB: {device['adb_serial']}")
        logger.info(f"   CH9329: {device['ch9329_port']}")
        logger.info(f"   Screen: {device['screen']['width']}x{device['screen']['height']}")
        logger.info(f"   Status: {device['status']}")
        logger.info(f"   Calibration: {device['calibration_profile'] or 'Not calibrated'}")

    return 0


def cmd_status(args):
    """Check real-time status of all devices."""
    devices = load_devices()

    if not devices:
        logger.warning("No devices configured")
        return 0

    logger.info("=" * 80)
    logger.info("Device Farm Status Check")
    logger.info("=" * 80)

    # Scan hardware
    logger.info("\n[Scanning Hardware...]")
    adb_devices = scan_adb_devices()
    com_ports = scan_com_ports()

    adb_serials = {d.serial for d in adb_devices}
    com_port_names = {p[0] for p in com_ports}

    # Check each device
    for device in devices:
        logger.info(f"\n📱 {device['name']} ({device['phone_id']})")

        # Check ADB
        adb_connected = device['adb_serial'] in adb_serials
        if adb_connected:
            logger.success(f"   ✓ ADB: Connected ({device['adb_serial']})")
        else:
            logger.error(f"   ✗ ADB: Not found ({device['adb_serial']})")

        # Check CH9329
        if device['ch9329_port']:
            ch9329_available = device['ch9329_port'] in com_port_names
            if ch9329_available:
                # Try to connect
                ser = connect_ch9329(device['ch9329_port'])
                if ser:
                    logger.success(f"   ✓ CH9329: Connected ({device['ch9329_port']})")
                    ser.close()
                else:
                    logger.warning(f"   ⚠ CH9329: Port exists but connection failed ({device['ch9329_port']})")
            else:
                logger.error(f"   ✗ CH9329: Port not found ({device['ch9329_port']})")
        else:
            logger.warning(f"   ⚠ CH9329: Not configured")

        # Check calibration
        if device['calibration_profile']:
            profile_path = project_root / "config" / "calibration_profiles" / f"{device['calibration_profile']}.yaml"
            if profile_path.exists():
                logger.success(f"   ✓ Calibration: {device['calibration_profile']}")
            else:
                logger.warning(f"   ⚠ Calibration: Profile missing ({device['calibration_profile']})")
        else:
            logger.warning(f"   ⚠ Calibration: Not configured")

        # Overall status
        if adb_connected and (not device['ch9329_port'] or device['ch9329_port'] in com_port_names):
            logger.success(f"   Status: Ready ✓")
        else:
            logger.error(f"   Status: Not Ready ✗")

    return 0


def cmd_test(args):
    """Test a specific device."""
    devices = load_devices()
    device = next((d for d in devices if d['phone_id'] == args.phone_id), None)

    if not device:
        logger.error(f"Device not found: {args.phone_id}")
        return 1

    logger.info("=" * 80)
    logger.info(f"Testing Device: {device['name']}")
    logger.info("=" * 80)

    # Test ADB
    logger.info("\n[ADB Test]")
    if check_device_connectivity(device['adb_serial']):
        logger.success(f"✓ ADB connected: {device['adb_serial']}")
    else:
        logger.error(f"✗ ADB not connected: {device['adb_serial']}")
        return 1

    # Test CH9329
    if device['ch9329_port']:
        logger.info("\n[CH9329 Test]")
        ser = connect_ch9329(device['ch9329_port'])
        if ser:
            logger.success(f"✓ CH9329 connected: {device['ch9329_port']}")
            ser.close()
        else:
            logger.error(f"✗ CH9329 connection failed: {device['ch9329_port']}")
            return 1
    else:
        logger.warning("\n[CH9329] Not configured")

    logger.success("\n✓ All tests passed!")
    logger.info("\nNext steps:")
    logger.info(f"  Run full automation test: python scripts/02_test_automation.py --device {args.phone_id}")

    return 0


def cmd_calibrate(args):
    """Start calibration for a device."""
    devices = load_devices()
    device = next((d for d in devices if d['phone_id'] == args.phone_id), None)

    if not device:
        logger.error(f"Device not found: {args.phone_id}")
        return 1

    logger.info(f"Starting calibration for: {device['name']}")
    logger.info(f"Run: python scripts/01_calibrate_device.py --device {args.phone_id}")

    return 0


def cmd_enable(args):
    """Enable a device."""
    devices = load_devices()
    device = next((d for d in devices if d['phone_id'] == args.phone_id), None)

    if not device:
        logger.error(f"Device not found: {args.phone_id}")
        return 1

    device['status'] = 'idle'
    device['last_updated'] = datetime.now().isoformat()
    save_devices(devices)

    logger.success(f"✓ Device enabled: {device['name']}")
    return 0


def cmd_disable(args):
    """Disable a device."""
    devices = load_devices()
    device = next((d for d in devices if d['phone_id'] == args.phone_id), None)

    if not device:
        logger.error(f"Device not found: {args.phone_id}")
        return 1

    device['status'] = 'disabled'
    device['last_updated'] = datetime.now().isoformat()
    save_devices(devices)

    logger.success(f"✓ Device disabled: {device['name']}")
    return 0


def cmd_remove(args):
    """Remove a device from configuration."""
    devices = load_devices()
    device = next((d for d in devices if d['phone_id'] == args.phone_id), None)

    if not device:
        logger.error(f"Device not found: {args.phone_id}")
        return 1

    logger.warning(f"Remove device: {device['name']} ({args.phone_id})?")
    confirm = input("Type 'yes' to confirm: ").strip().lower()

    if confirm != 'yes':
        logger.info("Cancelled")
        return 0

    devices = [d for d in devices if d['phone_id'] != args.phone_id]
    save_devices(devices)

    logger.success(f"✓ Device removed: {args.phone_id}")
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Device Farm Management CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List all devices:
    python scripts/device_manager.py list

  Check device status:
    python scripts/device_manager.py status

  Test a device:
    python scripts/device_manager.py test vivo_v2199a_001

  Enable/disable a device:
    python scripts/device_manager.py enable vivo_v2199a_001
    python scripts/device_manager.py disable vivo_v2199a_001
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # list command
    subparsers.add_parser('list', help='List all configured devices')

    # status command
    subparsers.add_parser('status', help='Check real-time status of all devices')

    # test command
    parser_test = subparsers.add_parser('test', help='Test a specific device')
    parser_test.add_argument('phone_id', help='Device phone_id to test')

    # calibrate command
    parser_calibrate = subparsers.add_parser('calibrate', help='Start calibration for a device')
    parser_calibrate.add_argument('phone_id', help='Device phone_id to calibrate')

    # enable command
    parser_enable = subparsers.add_parser('enable', help='Enable a device')
    parser_enable.add_argument('phone_id', help='Device phone_id to enable')

    # disable command
    parser_disable = subparsers.add_parser('disable', help='Disable a device')
    parser_disable.add_argument('phone_id', help='Device phone_id to disable')

    # remove command
    parser_remove = subparsers.add_parser('remove', help='Remove a device')
    parser_remove.add_argument('phone_id', help='Device phone_id to remove')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    commands = {
        'list': cmd_list,
        'status': cmd_status,
        'test': cmd_test,
        'calibrate': cmd_calibrate,
        'enable': cmd_enable,
        'disable': cmd_disable,
        'remove': cmd_remove,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
