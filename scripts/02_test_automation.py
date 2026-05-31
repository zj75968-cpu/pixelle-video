#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Automation Script - Step 2

This script tests your device automation setup by:
1. Loading device configuration
2. Executing a simple test flow
3. Verifying the results

Usage:
    python scripts/02_test_automation.py
"""

import sys
from pathlib import Path
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from pixelle_video.device_farm.hardware.adb_observer import (
    scan_adb_devices,
    capture_screenshot
)
from pixelle_video.utils.ch9329 import CH9329Controller

# Configuration
PHONE_ID = "vivo_v2199a_001"
ADB_SERIAL = "10ACBE28M70044L"
CH9329_PORT = "COM5"
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400

# Output directory
OUTPUT_DIR = project_root / "runtime" / "test_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def test_basic_actions():
    """Test basic device control actions."""
    logger.info("=" * 60)
    logger.info("Basic Actions Test")
    logger.info("=" * 60)

    # Initialize controller
    controller = CH9329Controller(port=CH9329_PORT)
    controller.screen_width = SCREEN_WIDTH
    controller.screen_height = SCREEN_HEIGHT

    if not controller.connect():
        logger.error("Failed to connect to CH9329")
        return False

    try:
        # Test 1: Return to home
        logger.info("\n[Test 1] Swipe up to home")
        logger.info("  Watch your device screen...")
        time.sleep(1)

        if controller.swipe_up_to_home():
            logger.success("  ✓ Home gesture executed")
        else:
            logger.error("  ✗ Home gesture failed")
            return False

        time.sleep(2)

        # Test 2: Tap screen center
        logger.info("\n[Test 2] Tap screen center")
        logger.info("  Tapping at (0.5, 0.5)...")

        if controller.click(0.5, 0.5):
            logger.success("  ✓ Center tap executed")
        else:
            logger.error("  ✗ Center tap failed")
            return False

        time.sleep(1)

        # Test 3: Tap top-left quadrant
        logger.info("\n[Test 3] Tap top-left quadrant")
        logger.info("  Tapping at (0.25, 0.25)...")

        if controller.click(0.25, 0.25):
            logger.success("  ✓ Top-left tap executed")
        else:
            logger.error("  ✗ Top-left tap failed")
            return False

        time.sleep(1)

        # Test 4: Long press
        logger.info("\n[Test 4] Long press center")
        logger.info("  Long pressing at (0.5, 0.5) for 1.5s...")

        if controller.long_press(0.5, 0.5, duration=1.5):
            logger.success("  ✓ Long press executed")
        else:
            logger.error("  ✗ Long press failed")
            return False

        time.sleep(1)

        # Test 5: Return to home again
        logger.info("\n[Test 5] Return to home")
        if controller.swipe_up_to_home():
            logger.success("  ✓ Home gesture executed")
        else:
            logger.error("  ✗ Home gesture failed")
            return False

        logger.success("\n✓ All basic actions completed successfully")
        return True

    finally:
        controller.disconnect()


def test_screenshot_capture():
    """Test ADB screenshot capture."""
    logger.info("\n" + "=" * 60)
    logger.info("Screenshot Capture Test")
    logger.info("=" * 60)

    try:
        output_path = OUTPUT_DIR / "test_screenshot.png"
        logger.info(f"\nCapturing screenshot to: {output_path}")

        img_data = capture_screenshot(ADB_SERIAL, str(output_path))

        logger.success(f"✓ Screenshot captured: {len(img_data)} bytes")
        logger.info(f"  Saved to: {output_path}")

        return True

    except Exception as e:
        logger.error(f"✗ Screenshot capture failed: {e}")
        return False


def test_combined_workflow():
    """Test combined ADB + CH9329 workflow."""
    logger.info("\n" + "=" * 60)
    logger.info("Combined Workflow Test")
    logger.info("=" * 60)

    controller = CH9329Controller(port=CH9329_PORT)
    controller.screen_width = SCREEN_WIDTH
    controller.screen_height = SCREEN_HEIGHT

    if not controller.connect():
        logger.error("Failed to connect to CH9329")
        return False

    try:
        # Step 1: Capture initial state
        logger.info("\n[Step 1] Capture initial state")
        before_path = OUTPUT_DIR / "workflow_before.png"
        capture_screenshot(ADB_SERIAL, str(before_path))
        logger.success(f"  ✓ Before screenshot: {before_path}")

        time.sleep(1)

        # Step 2: Perform action
        logger.info("\n[Step 2] Tap screen center")
        controller.click(0.5, 0.5)
        logger.success("  ✓ Tap executed")

        time.sleep(1)

        # Step 3: Capture result
        logger.info("\n[Step 3] Capture result state")
        after_path = OUTPUT_DIR / "workflow_after.png"
        capture_screenshot(ADB_SERIAL, str(after_path))
        logger.success(f"  ✓ After screenshot: {after_path}")

        # Step 4: Return to home
        logger.info("\n[Step 4] Return to home")
        controller.swipe_up_to_home()
        logger.success("  ✓ Home gesture executed")

        time.sleep(1)

        # Step 5: Final state
        logger.info("\n[Step 5] Capture final state")
        final_path = OUTPUT_DIR / "workflow_final.png"
        capture_screenshot(ADB_SERIAL, str(final_path))
        logger.success(f"  ✓ Final screenshot: {final_path}")

        logger.success("\n✓ Combined workflow completed successfully")
        logger.info(f"\nResults saved to: {OUTPUT_DIR}")

        return True

    except Exception as e:
        logger.error(f"✗ Workflow failed: {e}")
        return False

    finally:
        controller.disconnect()


def main():
    """Main test workflow."""
    logger.info("=" * 60)
    logger.info("Device Automation Test Suite")
    logger.info("=" * 60)
    logger.info(f"Device: {PHONE_ID}")
    logger.info(f"ADB Serial: {ADB_SERIAL}")
    logger.info(f"CH9329 Port: {CH9329_PORT}")

    results = {}

    # Test 1: Basic actions
    logger.info("\n" + "=" * 60)
    logger.info("Starting Test 1: Basic Actions")
    logger.info("=" * 60)
    input("Press Enter to start (watch your device screen)...")

    results['basic_actions'] = test_basic_actions()

    # Test 2: Screenshot capture
    logger.info("\n" + "=" * 60)
    logger.info("Starting Test 2: Screenshot Capture")
    logger.info("=" * 60)
    input("Press Enter to start...")

    results['screenshot'] = test_screenshot_capture()

    # Test 3: Combined workflow
    logger.info("\n" + "=" * 60)
    logger.info("Starting Test 3: Combined Workflow")
    logger.info("=" * 60)
    input("Press Enter to start (watch your device screen)...")

    results['workflow'] = test_combined_workflow()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {test_name}: {status}")

    logger.info(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        logger.success("\n🎉 All tests passed! Your device farm is ready!")
        logger.info("\nNext steps:")
        logger.info("  1. Create calibration profiles with: python scripts/01_calibrate_device.py")
        logger.info("  2. Define automation flows in: config/flows/")
        logger.info("  3. Start the REST API: python -m pixelle_video.device_farm.api.rest_api")
    else:
        logger.error(f"\n✗ {total - passed} test(s) failed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
