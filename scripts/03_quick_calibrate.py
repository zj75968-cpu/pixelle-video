#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Calibration Tool for Multi-Device Setup

Streamlined calibration process that:
1. Copies calibration points from a reference device
2. Allows quick adjustments for screen size differences
3. Batch tests all points

Usage:
    # Calibrate from scratch
    python scripts/03_quick_calibrate.py --device vivo_v2199a_002

    # Copy from reference device and adjust
    python scripts/03_quick_calibrate.py --device vivo_v2199a_002 --reference vivo_v2199a_001
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
from pixelle_video.device_farm.hardware.adb_observer import capture_screenshot
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


def load_calibration_profile(phone_id):
    """Load calibration profile for a device."""
    profile_dir = project_root / "config" / "calibration_profiles"

    # Try different profile names
    possible_names = [
        f"{phone_id}_default.yaml",
        f"{phone_id}_profile.yaml",
        f"{phone_id}.yaml"
    ]

    for name in possible_names:
        profile_path = profile_dir / name
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)

    return None


def scale_points_for_resolution(points, source_res, target_res):
    """Scale calibration points from source resolution to target resolution."""
    src_w, src_h = source_res
    tgt_w, tgt_h = target_res

    scaled_points = []

    for point in points:
        # Use ratio if available, otherwise calculate from absolute
        if 'x_ratio' in point and 'y_ratio' in point:
            x_ratio = point['x_ratio']
            y_ratio = point['y_ratio']
        else:
            x_ratio = point['x'] / src_w
            y_ratio = point['y'] / src_h

        # Calculate new absolute coordinates
        new_x = int(x_ratio * tgt_w)
        new_y = int(y_ratio * tgt_h)

        scaled_point = {
            'name': point['name'],
            'type': point.get('type', 'absolute'),
            'x': new_x,
            'y': new_y,
            'x_ratio': round(x_ratio, 4),
            'y_ratio': round(y_ratio, 4),
            'description': point.get('description', '') + f" (scaled from {src_w}x{src_h})"
        }

        scaled_points.append(scaled_point)

    return scaled_points


def quick_calibrate_from_reference(device_config, reference_profile):
    """Quick calibration by copying and scaling from reference device."""
    logger.info("=" * 60)
    logger.info("Quick Calibration from Reference")
    logger.info("=" * 60)

    device_res = (device_config['screen']['width'], device_config['screen']['height'])
    ref_res = (reference_profile['screen']['width'], reference_profile['screen']['height'])

    logger.info(f"\nReference resolution: {ref_res[0]}x{ref_res[1]}")
    logger.info(f"Target resolution: {device_res[0]}x{device_res[1]}")

    if device_res == ref_res:
        logger.success("✓ Same resolution - direct copy")
        scaled_points = reference_profile['points']
    else:
        logger.info("⚠ Different resolution - scaling points")
        scaled_points = scale_points_for_resolution(
            reference_profile['points'],
            ref_res,
            device_res
        )

    logger.info(f"\n✓ Copied {len(scaled_points)} calibration points:")
    for point in scaled_points:
        logger.info(f"  - {point['name']}: ({point['x']}, {point['y']})")

    return scaled_points


def batch_test_points(device_config, points, test_mode='visual'):
    """Batch test all calibration points."""
    logger.info("\n" + "=" * 60)
    logger.info("Batch Point Testing")
    logger.info("=" * 60)

    controller = CH9329Controller(port=device_config['ch9329_port'])
    controller.screen_width = device_config['screen']['width']
    controller.screen_height = device_config['screen']['height']

    if not controller.connect():
        logger.error("Failed to connect to CH9329")
        return False

    try:
        if test_mode == 'visual':
            logger.info("\nVisual test mode: cursor will move to each point")
            logger.info("Watch your device screen to verify positions")
            input("\nPress Enter to start...")

            for i, point in enumerate(points, 1):
                logger.info(f"\n[{i}/{len(points)}] Testing: {point['name']}")
                logger.info(f"  Position: ({point['x']}, {point['y']})")

                # Move to point (don't click)
                if controller.move_to(point['x_ratio'], point['y_ratio']):
                    logger.success("  ✓ Cursor moved")
                    input("  Press Enter for next point...")
                else:
                    logger.error("  ✗ Move failed")

        elif test_mode == 'tap':
            logger.warning("\nTap test mode: will actually tap each point!")
            logger.warning("Make sure your device is in a safe state")
            confirm = input("\nContinue? [y/N]: ").strip().lower()

            if confirm != 'y':
                logger.info("Test cancelled")
                return False

            for i, point in enumerate(points, 1):
                logger.info(f"\n[{i}/{len(points)}] Tapping: {point['name']}")
                logger.info(f"  Position: ({point['x']}, {point['y']})")

                if controller.click(point['x_ratio'], point['y_ratio']):
                    logger.success("  ✓ Tap executed")
                else:
                    logger.error("  ✗ Tap failed")

                input("  Press Enter for next point...")

        logger.success("\n✓ Batch test completed")
        return True

    finally:
        controller.disconnect()


def save_calibration_profile(device_config, points):
    """Save calibration profile."""
    phone_id = device_config['phone_id']
    profile_dir = project_root / "config" / "calibration_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profile_dir / f"{phone_id}_default.yaml"

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
        'points': points,
        'created_at': datetime.now().isoformat(),
        'metadata': {
            'device_name': device_config['name'],
            'model': device_config['metadata'].get('model')
        }
    }

    with open(profile_path, 'w', encoding='utf-8') as f:
        yaml.dump(profile, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.success(f"\n✓ Profile saved: {profile_path}")

    # Update device config to reference this profile
    update_device_profile_reference(phone_id, f"{phone_id}_default")

    return profile_path


def update_device_profile_reference(phone_id, profile_id):
    """Update device configuration to reference calibration profile."""
    config_path = project_root / "config" / "devices.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    for device in config.get('devices', []):
        if device['phone_id'] == phone_id:
            device['calibration_profile'] = profile_id
            device['last_updated'] = datetime.now().isoformat()
            break

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info(f"  Updated device config: calibration_profile = {profile_id}")


def main():
    """Main quick calibration workflow."""
    parser = argparse.ArgumentParser(description='Quick calibration tool for multi-device setup')
    parser.add_argument('--device', required=True, help='Target device phone_id')
    parser.add_argument('--reference', help='Reference device phone_id to copy from')
    parser.add_argument('--test-mode', choices=['visual', 'tap', 'skip'], default='visual',
                       help='Point testing mode (default: visual)')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Quick Calibration Tool")
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

    # Load reference profile if specified
    if args.reference:
        logger.info(f"\nReference Device: {args.reference}")
        reference_profile = load_calibration_profile(args.reference)

        if not reference_profile:
            logger.error(f"Reference profile not found for: {args.reference}")
            logger.info("Available profiles:")
            profile_dir = project_root / "config" / "calibration_profiles"
            for profile_file in profile_dir.glob("*.yaml"):
                logger.info(f"  - {profile_file.stem}")
            return 1

        logger.success(f"✓ Loaded reference profile: {reference_profile['profile_id']}")
        logger.info(f"  Points: {len(reference_profile['points'])}")

        # Copy and scale points
        points = quick_calibrate_from_reference(device_config, reference_profile)
    else:
        logger.info("\nNo reference device specified")
        logger.info("Starting from scratch - use interactive calibration")
        logger.info("Run: python scripts/01_calibrate_device.py --device " + args.device)
        return 1

    # Test points
    if args.test_mode != 'skip':
        if not batch_test_points(device_config, points, args.test_mode):
            logger.warning("\nPoint testing incomplete")
            save_anyway = input("Save calibration anyway? [y/N]: ").strip().lower()
            if save_anyway != 'y':
                logger.info("Calibration not saved")
                return 1

    # Save profile
    profile_path = save_calibration_profile(device_config, points)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("✓ Quick Calibration Complete!")
    logger.info("=" * 60)
    logger.success(f"Device: {device_config['name']}")
    logger.success(f"Profile: {profile_path}")
    logger.info(f"Points: {len(points)}")

    logger.info("\nNext steps:")
    logger.info(f"  1. Test automation:")
    logger.info(f"     python scripts/02_test_automation.py --device {args.device}")
    logger.info(f"  2. Fine-tune points if needed:")
    logger.info(f"     python scripts/01_calibrate_device.py --device {args.device}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
