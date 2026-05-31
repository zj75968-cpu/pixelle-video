#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Device Setup Wizard

Quickly add and configure new devices to your device farm.
Automatically detects ADB devices and CH9329 controllers.

Usage:
    python scripts/00_add_new_device.py
"""

import sys
from pathlib import Path
import yaml
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware.adb_observer import (
    scan_adb_devices,
    get_device_info
)
from pixelle_video.device_farm.hardware.ch9329_controller import scan_com_ports

DEVICES_CONFIG = project_root / "config" / "devices.yaml"


def scan_available_hardware():
    """Scan for available ADB devices and CH9329 controllers."""
    logger.info("=" * 60)
    logger.info("Scanning Available Hardware")
    logger.info("=" * 60)

    # Scan ADB devices
    logger.info("\n[ADB Devices]")
    adb_devices = scan_adb_devices()

    if not adb_devices:
        logger.warning("No ADB devices found")
        logger.info("Please:")
        logger.info("  1. Connect device via USB")
        logger.info("  2. Enable USB debugging")
        logger.info("  3. Accept USB debugging prompt")
        adb_devices = []
    else:
        logger.success(f"Found {len(adb_devices)} ADB device(s):")
        for i, device in enumerate(adb_devices, 1):
            info = get_device_info(device.serial)
            logger.info(f"  [{i}] Serial: {device.serial}")
            logger.info(f"      Model: {info.model}")
            logger.info(f"      Resolution: {info.resolution}")
            logger.info(f"      Status: {device.status}")

    # Scan COM ports
    logger.info("\n[CH9329 Controllers]")
    com_ports = scan_com_ports()

    if not com_ports:
        logger.warning("No COM ports found")
        com_ports = []
    else:
        logger.success(f"Found {len(com_ports)} COM port(s):")
        for i, (port, desc, hwid) in enumerate(com_ports, 1):
            logger.info(f"  [{i}] Port: {port}")
            logger.info(f"      Description: {desc}")
            if "CH340" in hwid or "1A86:7523" in hwid:
                logger.info(f"      Type: CH9329 (CH340 chip) ✓")
            else:
                logger.info(f"      Type: Other")

    return adb_devices, com_ports


def load_existing_devices():
    """Load existing device configuration."""
    if not DEVICES_CONFIG.exists():
        return []

    with open(DEVICES_CONFIG, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config.get('devices', [])


def generate_phone_id(model, existing_devices):
    """Generate a unique phone_id."""
    # Clean model name
    base_id = model.lower().replace(' ', '_').replace('-', '_')

    # Find next available number
    existing_ids = [d['phone_id'] for d in existing_devices]
    counter = 1

    while True:
        phone_id = f"{base_id}_{counter:03d}"
        if phone_id not in existing_ids:
            return phone_id
        counter += 1


def interactive_device_setup(adb_devices, com_ports, existing_devices):
    """Interactive device configuration."""
    logger.info("\n" + "=" * 60)
    logger.info("Device Setup Wizard")
    logger.info("=" * 60)

    if not adb_devices:
        logger.error("No ADB devices available. Please connect a device first.")
        return None

    # Select ADB device
    logger.info("\n[Step 1] Select ADB Device")
    for i, device in enumerate(adb_devices, 1):
        info = get_device_info(device.serial)
        logger.info(f"  [{i}] {info.model} ({device.serial})")

    while True:
        try:
            choice = input(f"\nSelect device [1-{len(adb_devices)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(adb_devices):
                selected_device = adb_devices[idx]
                break
            logger.warning(f"Please enter a number between 1 and {len(adb_devices)}")
        except (ValueError, KeyboardInterrupt):
            logger.error("\nSetup cancelled")
            return None

    # Get device info
    device_info = get_device_info(selected_device.serial)
    logger.success(f"\n✓ Selected: {device_info.model} ({selected_device.serial})")

    # Select CH9329 port
    logger.info("\n[Step 2] Select CH9329 Port")
    if not com_ports:
        logger.warning("No COM ports found. You can set this later.")
        ch9329_port = None
    else:
        for i, (port, desc, hwid) in enumerate(com_ports, 1):
            marker = " ← CH9329" if "CH340" in hwid or "1A86:7523" in hwid else ""
            logger.info(f"  [{i}] {port} - {desc}{marker}")

        while True:
            try:
                choice = input(f"\nSelect port [1-{len(com_ports)}] or 'skip': ").strip()
                if choice.lower() == 'skip':
                    ch9329_port = None
                    logger.info("Skipped CH9329 port selection")
                    break
                idx = int(choice) - 1
                if 0 <= idx < len(com_ports):
                    ch9329_port = com_ports[idx][0]
                    logger.success(f"✓ Selected: {ch9329_port}")
                    break
                logger.warning(f"Please enter a number between 1 and {len(com_ports)}")
            except ValueError:
                logger.warning("Invalid input")
            except KeyboardInterrupt:
                logger.error("\nSetup cancelled")
                return None

    # Generate phone_id
    phone_id = generate_phone_id(device_info.model or "device", existing_devices)
    logger.info(f"\n[Step 3] Device ID: {phone_id}")

    # Get friendly name
    default_name = device_info.model or "Unknown Device"
    name = input(f"\nDevice name [{default_name}]: ").strip() or default_name

    # Screen resolution
    if device_info.resolution:
        width, height = device_info.resolution
        logger.info(f"\n[Step 4] Screen Resolution: {width}x{height} (auto-detected)")
    else:
        logger.info("\n[Step 4] Screen Resolution")
        logger.info("Common resolutions:")
        logger.info("  1. 1080x2400 (FHD+)")
        logger.info("  2. 1080x2340 (FHD+)")
        logger.info("  3. 1440x3200 (QHD+)")
        logger.info("  4. 720x1600 (HD+)")

        while True:
            try:
                res_input = input("\nSelect [1-4] or enter 'WIDTHxHEIGHT': ").strip()
                if res_input == '1':
                    width, height = 1080, 2400
                    break
                elif res_input == '2':
                    width, height = 1080, 2340
                    break
                elif res_input == '3':
                    width, height = 1440, 3200
                    break
                elif res_input == '4':
                    width, height = 720, 1600
                    break
                elif 'x' in res_input:
                    w, h = res_input.split('x')
                    width, height = int(w), int(h)
                    break
                logger.warning("Invalid input")
            except (ValueError, KeyboardInterrupt):
                logger.error("\nSetup cancelled")
                return None

    # Build device config
    device_config = {
        'phone_id': phone_id,
        'name': name,
        'adb_serial': selected_device.serial,
        'ch9329_port': ch9329_port,
        'screen': {
            'width': width,
            'height': height
        },
        'status': 'idle',
        'calibration_profile': None,
        'last_updated': datetime.now().isoformat(),
        'metadata': {
            'model': device_info.model,
            'auto_detected': True
        }
    }

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Device Configuration Summary")
    logger.info("=" * 60)
    logger.info(f"Phone ID: {phone_id}")
    logger.info(f"Name: {name}")
    logger.info(f"ADB Serial: {selected_device.serial}")
    logger.info(f"CH9329 Port: {ch9329_port or 'Not set'}")
    logger.info(f"Screen: {width}x{height}")
    logger.info(f"Model: {device_info.model}")

    confirm = input("\nAdd this device? [Y/n]: ").strip().lower()
    if confirm in ['', 'y', 'yes']:
        return device_config
    else:
        logger.info("Device not added")
        return None


def save_device_config(new_device, existing_devices):
    """Save device configuration to YAML."""
    # Add new device
    existing_devices.append(new_device)

    # Sort by phone_id
    existing_devices.sort(key=lambda d: d['phone_id'])

    # Build config
    config = {
        'devices': existing_devices,
        'last_modified': datetime.now().isoformat()
    }

    # Save to file
    DEVICES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(DEVICES_CONFIG, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.success(f"\n✓ Device configuration saved: {DEVICES_CONFIG}")
    logger.info(f"  Total devices: {len(existing_devices)}")


def create_device_calibration_template(device_config):
    """Create a calibration template for the new device."""
    phone_id = device_config['phone_id']
    template_dir = project_root / "config" / "calibration_profiles"
    template_dir.mkdir(parents=True, exist_ok=True)

    template_path = template_dir / f"{phone_id}_template.yaml"

    template_content = f"""# Calibration Profile Template for {device_config['name']}
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Device: {device_config['name']} ({device_config['metadata']['model']})

profile_id: "{phone_id}_default"
phone_id: "{phone_id}"
screen:
  width: {device_config['screen']['width']}
  height: {device_config['screen']['height']}
  safe_top: 100
  safe_bottom: 120
  navigation_mode: "gesture"

# Add your calibration points here
# Use: python scripts/01_calibrate_device.py --device {phone_id}
points: []

# Example points:
# points:
#   - name: "screen.center"
#     type: "absolute"
#     x: {device_config['screen']['width'] // 2}
#     y: {device_config['screen']['height'] // 2}
#     x_ratio: 0.5000
#     y_ratio: 0.5000
#     description: "Screen center point"
#
#   - name: "xhs.home.publish_button"
#     type: "absolute"
#     x: {device_config['screen']['width'] // 2}
#     y: {int(device_config['screen']['height'] * 0.875)}
#     x_ratio: 0.5000
#     y_ratio: 0.8750
#     description: "Publish button at bottom center"
"""

    template_path.write_text(template_content, encoding='utf-8')
    logger.info(f"  Calibration template: {template_path}")

    return template_path


def main():
    """Main setup workflow."""
    logger.info("=" * 60)
    logger.info("Multi-Device Setup Wizard")
    logger.info("=" * 60)
    logger.info("Quickly add new devices to your device farm")

    # Scan hardware
    adb_devices, com_ports = scan_available_hardware()

    # Load existing devices
    existing_devices = load_existing_devices()
    logger.info(f"\n[Existing Devices] {len(existing_devices)} device(s) configured")
    for device in existing_devices:
        logger.info(f"  - {device['phone_id']}: {device['name']}")

    # Interactive setup
    new_device = interactive_device_setup(adb_devices, com_ports, existing_devices)

    if not new_device:
        logger.warning("\nNo device added")
        return 1

    # Save configuration
    save_device_config(new_device, existing_devices)

    # Create calibration template
    template_path = create_device_calibration_template(new_device)

    # Next steps
    logger.info("\n" + "=" * 60)
    logger.info("✓ Device Added Successfully!")
    logger.info("=" * 60)
    logger.success(f"Device ID: {new_device['phone_id']}")
    logger.info("\nNext steps:")
    logger.info(f"  1. Calibrate device:")
    logger.info(f"     python scripts/01_calibrate_device.py --device {new_device['phone_id']}")
    logger.info(f"  2. Test automation:")
    logger.info(f"     python scripts/02_test_automation.py --device {new_device['phone_id']}")
    logger.info(f"  3. Quick test CH9329:")
    logger.info(f"     python test_ch9329_debug.py {new_device['ch9329_port']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
