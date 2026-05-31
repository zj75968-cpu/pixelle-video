"""
REST API for Device Farm Service.

Provides HTTP endpoints for all device farm operations.
"""

import logging
from typing import Optional
from flask import Flask, request, jsonify, send_file
from pathlib import Path

from pixelle_video.device_farm.farm_service import (
    DeviceFarmService,
    DeviceNotFoundError,
    CalibrationSessionError,
    JobExecutionError,
    FarmServiceError,
)
from pixelle_video.device_farm.registry import DeviceStatus
from pixelle_video.device_farm.runtime import JobStatus

logger = logging.getLogger(__name__)


class DeviceFarmAPI:
    """REST API wrapper for Device Farm Service."""

    def __init__(self, service: DeviceFarmService):
        """
        Initialize API.

        Args:
            service: Device Farm Service instance
        """
        self.service = service

    def register_routes(self, app: Flask) -> None:
        """
        Register all API routes.

        Args:
            app: Flask application
        """
        # Device Management
        app.add_url_rule("/api/devices", "list_devices", self.list_devices, methods=["GET"])
        app.add_url_rule("/api/devices/<phone_id>", "get_device", self.get_device, methods=["GET"])
        app.add_url_rule("/api/devices/<phone_id>", "update_device", self.update_device, methods=["PATCH"])

        # Calibration
        app.add_url_rule("/api/calibration/start", "start_calibration", self.start_calibration, methods=["POST"])
        app.add_url_rule("/api/calibration/<phone_id>/point", "save_point", self.save_point, methods=["POST"])
        app.add_url_rule("/api/calibration/<phone_id>/test", "test_point", self.test_point, methods=["POST"])
        app.add_url_rule("/api/calibration/<phone_id>/finish", "finish_calibration", self.finish_calibration, methods=["POST"])
        app.add_url_rule("/api/calibration/<phone_id>/cancel", "cancel_calibration", self.cancel_calibration, methods=["POST"])

        # Job Execution
        app.add_url_rule("/api/jobs", "submit_job", self.submit_job, methods=["POST"])
        app.add_url_rule("/api/jobs/<job_id>", "get_job", self.get_job, methods=["GET"])
        app.add_url_rule("/api/jobs", "list_jobs", self.list_jobs, methods=["GET"])

        # Screenshots
        app.add_url_rule("/api/devices/<phone_id>/screenshot", "get_screenshot", self.get_screenshot, methods=["GET"])
        app.add_url_rule("/api/devices/<phone_id>/screenshot", "capture_screenshot", self.capture_screenshot, methods=["POST"])

        # Manual Recovery
        app.add_url_rule("/api/jobs/<job_id>/retry", "retry_step", self.retry_step, methods=["POST"])
        app.add_url_rule("/api/jobs/<job_id>/resolve", "resolve_job", self.resolve_job, methods=["POST"])
        app.add_url_rule("/api/devices/<phone_id>/recalibrate", "recalibrate", self.recalibrate, methods=["POST"])

        # Health check
        app.add_url_rule("/api/health", "health", self.health, methods=["GET"])

    # =========================================================================
    # Device Management Endpoints
    # =========================================================================

    def list_devices(self):
        """GET /api/devices - List all devices."""
        try:
            status_filter = request.args.get("status")
            include_disabled = request.args.get("include_disabled", "true").lower() == "true"

            if status_filter:
                status_filter = DeviceStatus(status_filter)

            devices = self.service.list_devices(
                status=status_filter,
                include_disabled=include_disabled,
            )

            return jsonify({
                "success": True,
                "devices": devices,
                "count": len(devices),
            })

        except Exception as e:
            logger.error(f"Error listing devices: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def get_device(self, phone_id: str):
        """GET /api/devices/<phone_id> - Get device status."""
        try:
            status = self.service.get_device_status(phone_id)
            return jsonify({"success": True, "device": status})

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error getting device status: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def update_device(self, phone_id: str):
        """PATCH /api/devices/<phone_id> - Update device state."""
        try:
            data = request.get_json()

            status = None
            if "status" in data:
                status = DeviceStatus(data["status"])

            device = self.service.update_device_state(
                phone_id=phone_id,
                status=status,
                calibration_profile=data.get("calibration_profile"),
                metadata=data.get("metadata"),
            )

            return jsonify({"success": True, "device": device})

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error updating device: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # Calibration Endpoints
    # =========================================================================

    def start_calibration(self):
        """POST /api/calibration/start - Start calibration session."""
        try:
            data = request.get_json()
            phone_id = data.get("phone_id")
            profile_id = data.get("profile_id")

            if not phone_id:
                return jsonify({"success": False, "error": "phone_id is required"}), 400

            session = self.service.start_calibration_session(
                phone_id=phone_id,
                profile_id=profile_id,
            )

            return jsonify({"success": True, "session": session})

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except CalibrationSessionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error starting calibration: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def save_point(self, phone_id: str):
        """POST /api/calibration/<phone_id>/point - Save calibration point."""
        try:
            data = request.get_json()

            point = self.service.save_calibration_point(
                phone_id=phone_id,
                point_name=data.get("point_name"),
                x=data.get("x"),
                y=data.get("y"),
                description=data.get("description", ""),
            )

            return jsonify({"success": True, "point": point})

        except CalibrationSessionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error saving calibration point: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def test_point(self, phone_id: str):
        """POST /api/calibration/<phone_id>/test - Test calibration point."""
        try:
            data = request.get_json()
            point_name = data.get("point_name")

            if not point_name:
                return jsonify({"success": False, "error": "point_name is required"}), 400

            result = self.service.test_calibration_point(
                phone_id=phone_id,
                point_name=point_name,
            )

            return jsonify({"success": True, "result": result})

        except CalibrationSessionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error testing calibration point: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def finish_calibration(self, phone_id: str):
        """POST /api/calibration/<phone_id>/finish - Finish calibration session."""
        try:
            data = request.get_json() or {}
            assign_to_device = data.get("assign_to_device", True)

            profile = self.service.finish_calibration_session(
                phone_id=phone_id,
                assign_to_device=assign_to_device,
            )

            return jsonify({"success": True, "profile": profile})

        except CalibrationSessionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error finishing calibration: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def cancel_calibration(self, phone_id: str):
        """POST /api/calibration/<phone_id>/cancel - Cancel calibration session."""
        try:
            self.service.cancel_calibration_session(phone_id)
            return jsonify({"success": True})

        except Exception as e:
            logger.error(f"Error cancelling calibration: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # Job Execution Endpoints
    # =========================================================================

    def submit_job(self):
        """POST /api/jobs - Submit a job."""
        try:
            data = request.get_json()

            phone_id = data.get("phone_id")
            flow_id = data.get("flow_id")
            job_data = data.get("job_data", {})
            metadata = data.get("metadata")

            if not phone_id or not flow_id:
                return jsonify({
                    "success": False,
                    "error": "phone_id and flow_id are required"
                }), 400

            job_id = self.service.submit_job(
                phone_id=phone_id,
                flow_id=flow_id,
                job_data=job_data,
                metadata=metadata,
            )

            return jsonify({"success": True, "job_id": job_id}), 201

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except JobExecutionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error submitting job: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def get_job(self, job_id: str):
        """GET /api/jobs/<job_id> - Get job status."""
        try:
            job = self.service.get_job_status(job_id)
            return jsonify({"success": True, "job": job})

        except JobExecutionError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error getting job status: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def list_jobs(self):
        """GET /api/jobs - List jobs with filters."""
        try:
            phone_id = request.args.get("phone_id")
            status_filter = request.args.get("status")
            limit = int(request.args.get("limit", 50))

            if status_filter:
                status_filter = JobStatus(status_filter)

            jobs = self.service.get_job_logs(
                phone_id=phone_id,
                status=status_filter,
                limit=limit,
            )

            return jsonify({
                "success": True,
                "jobs": jobs,
                "count": len(jobs),
            })

        except Exception as e:
            logger.error(f"Error listing jobs: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # Screenshot Endpoints
    # =========================================================================

    def get_screenshot(self, phone_id: str):
        """GET /api/devices/<phone_id>/screenshot - Get latest screenshot."""
        try:
            screenshot_path = self.service.get_latest_screenshot(phone_id)

            if screenshot_path is None:
                return jsonify({
                    "success": False,
                    "error": "No screenshot found"
                }), 404

            # Return image file
            return send_file(screenshot_path, mimetype="image/png")

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error getting screenshot: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def capture_screenshot(self, phone_id: str):
        """POST /api/devices/<phone_id>/screenshot - Capture new screenshot."""
        try:
            screenshot_path = self.service.capture_screenshot(phone_id)

            return jsonify({
                "success": True,
                "screenshot_path": screenshot_path,
            })

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # Manual Recovery Endpoints
    # =========================================================================

    def retry_step(self, job_id: str):
        """POST /api/jobs/<job_id>/retry - Retry failed step."""
        try:
            data = request.get_json()
            step_id = data.get("step_id")

            if not step_id:
                return jsonify({"success": False, "error": "step_id is required"}), 400

            result = self.service.retry_failed_step(job_id, step_id)

            return jsonify({"success": True, "result": result})

        except JobExecutionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error retrying step: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def resolve_job(self, job_id: str):
        """POST /api/jobs/<job_id>/resolve - Mark job as manually resolved."""
        try:
            data = request.get_json()
            resolution = data.get("resolution")

            if not resolution:
                return jsonify({"success": False, "error": "resolution is required"}), 400

            self.service.mark_job_handled(job_id, resolution)

            return jsonify({"success": True})

        except JobExecutionError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Error resolving job: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def recalibrate(self, phone_id: str):
        """POST /api/devices/<phone_id>/recalibrate - Start recalibration."""
        try:
            session = self.service.recalibrate_device(phone_id)

            return jsonify({"success": True, "session": session})

        except DeviceNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            logger.error(f"Error starting recalibration: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # Health Check
    # =========================================================================

    def health(self):
        """GET /api/health - Health check endpoint."""
        return jsonify({
            "success": True,
            "status": "healthy",
            "service": "Device Farm API",
        })


def create_app(
    config_dir: Optional[str] = None,
    logs_dir: Optional[str] = None,
    screenshots_dir: Optional[str] = None,
) -> Flask:
    """
    Create Flask application with Device Farm API.

    Args:
        config_dir: Configuration directory
        logs_dir: Logs directory
        screenshots_dir: Screenshots directory

    Returns:
        Flask application
    """
    app = Flask(__name__)

    # Initialize service
    service = DeviceFarmService(
        config_dir=config_dir,
        logs_dir=logs_dir,
        screenshots_dir=screenshots_dir,
    )

    # Initialize API
    api = DeviceFarmAPI(service)
    api.register_routes(app)

    # Store service for cleanup
    app.config["DEVICE_FARM_SERVICE"] = service

    # Register shutdown handler
    @app.teardown_appcontext
    def shutdown_service(exception=None):
        service = app.config.get("DEVICE_FARM_SERVICE")
        if service:
            service.shutdown()

    logger.info("Device Farm API initialized")

    return app


if __name__ == "__main__":
    # Development server
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
