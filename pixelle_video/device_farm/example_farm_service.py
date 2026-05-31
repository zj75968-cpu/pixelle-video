"""
Example usage of Device Farm Service.

Demonstrates:
- Device management
- Calibration workflow
- Job submission and monitoring
- Manual recovery operations
"""

import logging
from pathlib import Path

from pixelle_video.device_farm.farm_service import DeviceFarmService
from pixelle_video.device_farm.registry import DeviceStatus
from pixelle_video.device_farm.runtime import JobStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def example_device_management():
    """Example: Device management operations."""
    logger.info("=== Device Management Example ===")

    service = DeviceFarmService()

    # List all devices
    devices = service.list_devices()
    logger.info(f"Found {len(devices)} devices")

    if devices:
        phone_id = devices[0]["phone_id"]

        # Get detailed device status
        status = service.get_device_status(phone_id)
        logger.info(f"Device {phone_id} status: {status['status']}")
        logger.info(f"ADB connected: {status.get('adb_connected', False)}")
        logger.info(f"Calibration valid: {status.get('calibration_valid', False)}")

        # Update device state
        updated = service.update_device_state(
            phone_id=phone_id,
            metadata={"last_check": "2024-01-01T12:00:00"},
        )
        logger.info(f"Updated device metadata")


def example_calibration_workflow():
    """Example: Complete calibration workflow."""
    logger.info("=== Calibration Workflow Example ===")

    service = DeviceFarmService()

    # Get first available device
    devices = service.list_devices(status=DeviceStatus.IDLE)
    if not devices:
        logger.warning("No idle devices available")
        return

    phone_id = devices[0]["phone_id"]
    logger.info(f"Starting calibration for device {phone_id}")

    # Start calibration session
    session = service.start_calibration_session(phone_id)
    logger.info(f"Calibration session started: {session['profile_id']}")
    logger.info(f"Initial screenshot: {session['screenshot_path']}")

    # Save calibration points
    points = [
        ("xhs.home.publish_button", 540, 2100, "Publish button on home screen"),
        ("xhs.home.search_bar", 540, 150, "Search bar at top"),
        ("xhs.edit.next_button", 950, 100, "Next button in editor"),
    ]

    for point_name, x, y, description in points:
        point = service.save_calibration_point(
            phone_id=phone_id,
            point_name=point_name,
            x=x,
            y=y,
            description=description,
        )
        logger.info(f"Saved point: {point['point_name']} at ({point['x']}, {point['y']})")

    # Test a calibration point
    test_result = service.test_calibration_point(
        phone_id=phone_id,
        point_name="xhs.home.publish_button",
    )
    logger.info(f"Test result: {test_result['point_name']}")
    logger.info(f"Before: {test_result['screenshot_before']}")
    logger.info(f"After: {test_result['screenshot_after']}")

    # Finish calibration
    profile = service.finish_calibration_session(
        phone_id=phone_id,
        assign_to_device=True,
    )
    logger.info(f"Calibration complete: {profile['profile_id']}")
    logger.info(f"Points saved: {profile['points_count']}")


def example_job_submission():
    """Example: Submit and monitor a job."""
    logger.info("=== Job Submission Example ===")

    service = DeviceFarmService()

    # Get first idle device
    devices = service.list_devices(status=DeviceStatus.IDLE)
    if not devices:
        logger.warning("No idle devices available")
        return

    phone_id = devices[0]["phone_id"]

    # Submit a job
    job_id = service.submit_job(
        phone_id=phone_id,
        flow_id="flows/xhs_publish_video.yaml",
        job_data={
            "video_path": "/sdcard/DCIM/test_video.mp4",
            "title": "Test Video",
            "description": "Automated test",
        },
        metadata={
            "campaign": "test_campaign",
            "batch": "batch_001",
        },
    )
    logger.info(f"Job submitted: {job_id}")

    # Get job status
    job_status = service.get_job_status(job_id)
    logger.info(f"Job status: {job_status['status']}")
    logger.info(f"Created at: {job_status['created_at']}")

    # Query job logs
    recent_jobs = service.get_job_logs(phone_id=phone_id, limit=10)
    logger.info(f"Recent jobs for {phone_id}: {len(recent_jobs)}")


def example_screenshot_operations():
    """Example: Screenshot capture and viewing."""
    logger.info("=== Screenshot Operations Example ===")

    service = DeviceFarmService()

    devices = service.list_devices()
    if not devices:
        logger.warning("No devices available")
        return

    phone_id = devices[0]["phone_id"]

    # Capture new screenshot
    screenshot_path = service.capture_screenshot(phone_id)
    logger.info(f"Captured screenshot: {screenshot_path}")

    # Get latest screenshot
    latest = service.get_latest_screenshot(phone_id)
    logger.info(f"Latest screenshot: {latest}")


def example_manual_recovery():
    """Example: Manual recovery operations."""
    logger.info("=== Manual Recovery Example ===")

    service = DeviceFarmService()

    # Get failed jobs
    failed_jobs = service.get_job_logs(status=JobStatus.FAILED, limit=5)
    logger.info(f"Found {len(failed_jobs)} failed jobs")

    if failed_jobs:
        job_id = failed_jobs[0]["job_id"]
        logger.info(f"Processing failed job: {job_id}")

        # Option 1: Retry failed step
        if failed_jobs[0].get("failed_step"):
            step_id = failed_jobs[0]["failed_step"]
            result = service.retry_failed_step(job_id, step_id)
            logger.info(f"Retry initiated: {result}")

        # Option 2: Mark as manually handled
        service.mark_job_handled(
            job_id=job_id,
            resolution="Manually verified and resolved",
        )
        logger.info(f"Job {job_id} marked as handled")

    # Recalibrate a device
    devices = service.list_devices(status=DeviceStatus.BLOCKED)
    if devices:
        phone_id = devices[0]["phone_id"]
        session = service.recalibrate_device(phone_id)
        logger.info(f"Recalibration started for {phone_id}: {session['profile_id']}")


def example_rest_api_server():
    """Example: Start REST API server."""
    logger.info("=== REST API Server Example ===")

    from pixelle_video.device_farm.api import create_app

    # Create Flask app
    app = create_app()

    logger.info("Starting Device Farm API server on http://0.0.0.0:5000")
    logger.info("Available endpoints:")
    logger.info("  GET  /api/devices - List devices")
    logger.info("  GET  /api/devices/<phone_id> - Get device status")
    logger.info("  POST /api/calibration/start - Start calibration")
    logger.info("  POST /api/jobs - Submit job")
    logger.info("  GET  /api/jobs/<job_id> - Get job status")
    logger.info("  GET  /api/devices/<phone_id>/screenshot - Get screenshot")

    # Run server (development mode)
    app.run(host="0.0.0.0", port=5000, debug=True)


def example_rest_api_client():
    """Example: REST API client usage."""
    logger.info("=== REST API Client Example ===")

    import requests

    base_url = "http://localhost:5000/api"

    # List devices
    response = requests.get(f"{base_url}/devices")
    devices = response.json()
    logger.info(f"Devices: {devices}")

    if devices["success"] and devices["devices"]:
        phone_id = devices["devices"][0]["phone_id"]

        # Get device status
        response = requests.get(f"{base_url}/devices/{phone_id}")
        status = response.json()
        logger.info(f"Device status: {status}")

        # Submit job
        response = requests.post(
            f"{base_url}/jobs",
            json={
                "phone_id": phone_id,
                "flow_id": "flows/xhs_publish_video.yaml",
                "job_data": {
                    "video_path": "/sdcard/test.mp4",
                    "title": "API Test",
                },
            },
        )
        job = response.json()
        logger.info(f"Job submitted: {job}")

        if job["success"]:
            job_id = job["job_id"]

            # Get job status
            response = requests.get(f"{base_url}/jobs/{job_id}")
            job_status = response.json()
            logger.info(f"Job status: {job_status}")


if __name__ == "__main__":
    # Run examples
    try:
        example_device_management()
        print("\n")

        example_calibration_workflow()
        print("\n")

        example_job_submission()
        print("\n")

        example_screenshot_operations()
        print("\n")

        example_manual_recovery()
        print("\n")

        # Uncomment to start REST API server
        # example_rest_api_server()

        # Uncomment to test REST API client (requires server running)
        # example_rest_api_client()

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
