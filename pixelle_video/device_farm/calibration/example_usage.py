# -*- coding: utf-8 -*-
"""
Example usage of Calibration Workbench API.

Demonstrates the interactive calibration workflow:
1. Start calibration session
2. Capture screenshots
3. Save semantic points
4. Test points via CH9329
5. Compare before/after screenshots
"""

from pixelle_video.device_farm.calibration import CalibrationWorkbench, CalibrationError
from loguru import logger


def example_calibration_workflow():
    """Example calibration workflow."""

    # Initialize workbench
    workbench = CalibrationWorkbench()

    phone_id = "phone_001"

    try:
        # 1. Start calibration session
        logger.info("Starting calibration session...")
        session = workbench.start_calibration(phone_id)
        logger.info(f"Session started for {session.device.name}")

        # 2. Capture initial screenshot
        logger.info("Capturing screenshot...")
        img_data, screenshot_path = workbench.capture_screen(phone_id)
        logger.info(f"Screenshot saved: {screenshot_path}")

        # 3. Save semantic points (coordinates would come from user interaction)
        logger.info("Saving semantic points...")

        # Example: Home button at bottom center
        point1 = workbench.save_point(
            phone_id=phone_id,
            name="home_button",
            x=540,  # Center of 1080px width
            y=2300,  # Near bottom of 2400px height
            description="Main home button for returning to home screen"
        )
        logger.info(f"Saved point: {point1.name} at ({point1.x}, {point1.y})")

        # Example: Search icon at top
        point2 = workbench.save_point(
            phone_id=phone_id,
            name="search_icon",
            x=900,
            y=100,
            description="Search icon in top navigation bar"
        )
        logger.info(f"Saved point: {point2.name} at ({point2.x}, {point2.y})")

        # 4. Test a point
        logger.info("Testing point 'search_icon'...")
        test_result = workbench.test_point(phone_id, "search_icon", capture_after=True)

        if test_result['success']:
            logger.info("Point test successful!")
            logger.info(f"Before screenshot: {test_result['before_screenshot']}")
            logger.info(f"After screenshot: {test_result['after_screenshot']}")

            # 5. Compare screenshots
            logger.info("Comparing screenshots...")
            comparison = workbench.compare_screenshots(phone_id)
            logger.info(f"Change detected: {comparison['change_percentage']:.2f}%")

            if comparison['identical']:
                logger.warning("Screenshots are identical - point may not have triggered UI change")
            else:
                logger.info("UI change detected - point appears to be working correctly")
        else:
            logger.error(f"Point test failed: {test_result.get('error')}")

        # 6. List all points
        logger.info("Listing all calibrated points...")
        points = workbench.list_points(phone_id)
        for point in points:
            logger.info(f"  - {point['name']}: ({point['x']}, {point['y']}) - {point['description']}")

        # 7. Get profile summary
        profile = workbench.get_profile(phone_id)
        logger.info(f"Profile: {profile.profile_name}")
        logger.info(f"Screen: {profile.screen_width}x{profile.screen_height}")
        logger.info(f"Total points: {len(profile.points)}")

    except CalibrationError as e:
        logger.error(f"Calibration error: {e}")

    finally:
        # Always stop calibration session to cleanup resources
        logger.info("Stopping calibration session...")
        workbench.stop_calibration(phone_id, save_profile=True)
        logger.info("Calibration session ended")


def example_load_existing_profile():
    """Example of loading and using an existing profile."""

    workbench = CalibrationWorkbench()
    phone_id = "phone_001"

    try:
        # Start session with existing profile
        session = workbench.start_calibration(phone_id, profile_name="phone_001")

        # List existing points
        points = workbench.list_points(phone_id)
        logger.info(f"Loaded {len(points)} existing points")

        # Test an existing point
        if points:
            point_name = points[0]['name']
            logger.info(f"Testing existing point: {point_name}")
            result = workbench.test_point(phone_id, point_name)
            logger.info(f"Test result: {result['success']}")

    except CalibrationError as e:
        logger.error(f"Error: {e}")

    finally:
        workbench.stop_calibration(phone_id, save_profile=False)


def example_point_management():
    """Example of managing calibration points."""

    workbench = CalibrationWorkbench()
    phone_id = "phone_001"

    try:
        session = workbench.start_calibration(phone_id)

        # Add multiple points
        points_to_add = [
            ("back_button", 50, 100, "Back navigation button"),
            ("menu_icon", 1030, 100, "Menu icon in top right"),
            ("publish_button", 540, 2200, "Main publish/create button"),
            ("profile_tab", 900, 2350, "Profile tab in bottom navigation"),
        ]

        for name, x, y, desc in points_to_add:
            workbench.save_point(phone_id, name, x, y, desc)
            logger.info(f"Added point: {name}")

        # Remove a point
        removed = workbench.remove_point(phone_id, "back_button")
        if removed:
            logger.info("Removed point: back_button")

        # List remaining points
        points = workbench.list_points(phone_id)
        logger.info(f"Total points: {len(points)}")

    except CalibrationError as e:
        logger.error(f"Error: {e}")

    finally:
        workbench.stop_calibration(phone_id, save_profile=True)


if __name__ == "__main__":
    logger.info("=== Calibration Workbench Example ===")

    # Run example workflow
    # Note: Requires a device to be registered in device registry
    # and both ADB and CH9329 to be properly connected

    try:
        example_calibration_workflow()
    except Exception as e:
        logger.error(f"Example failed: {e}")
        logger.info("Make sure device is registered and connected before running examples")
