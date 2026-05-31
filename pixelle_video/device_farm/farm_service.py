"""
Device Farm Service - Orchestrates all device farm components.

Provides a unified API for:
- Device management (list, status, state updates)
- Calibration (start session, save/test points)
- Job execution (submit, status, logs)
- Screenshot viewing
- Manual recovery (retry, mark handled, recalibrate)
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from pixelle_video.device_farm.registry import DeviceRegistry, Device, DeviceStatus
from pixelle_video.device_farm.calibration import (
    CalibrationWorkbench,
    LegacyProfileManager as ProfileManager,
    CalibrationProfile,
    CalibrationPoint,
)
from pixelle_video.device_farm import hardware
from pixelle_video.device_farm.runtime import (
    ActionExecutor,
    JobLogger,
    JobStatus,
    StepResult,
    load_flow,
)

logger = logging.getLogger(__name__)


class FarmServiceError(Exception):
    """Base exception for farm service errors."""
    pass


class DeviceNotFoundError(FarmServiceError):
    """Device not found in registry."""
    pass


class CalibrationSessionError(FarmServiceError):
    """Calibration session error."""
    pass


class JobExecutionError(FarmServiceError):
    """Job execution error."""
    pass


@dataclass
class JobSubmission:
    """Job submission request."""
    phone_id: str
    flow_id: str
    job_data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class JobResult:
    """Job execution result."""
    job_id: str
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_step: Optional[str] = None
    error: Optional[str] = None
    screenshots: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['status'] = self.status.value
        return data


class DeviceFarmService:
    """
    Device Farm Service - Central orchestration layer.

    Manages devices, calibration, job execution, and recovery operations.
    """

    def __init__(
        self,
        config_dir: Optional[str] = None,
        logs_dir: Optional[str] = None,
        screenshots_dir: Optional[str] = None,
    ):
        """
        Initialize Device Farm Service.

        Args:
            config_dir: Configuration directory. Defaults to config/
            logs_dir: Logs directory. Defaults to logs/
            screenshots_dir: Screenshots directory. Defaults to runtime/screenshots/
        """
        # Set up directories
        project_root = Path(__file__).parent.parent.parent

        if config_dir is None:
            config_dir = project_root / "config"
        if logs_dir is None:
            logs_dir = project_root / "logs"
        if screenshots_dir is None:
            screenshots_dir = project_root / "runtime" / "screenshots"

        self.config_dir = Path(config_dir)
        self.logs_dir = Path(logs_dir)
        self.screenshots_dir = Path(screenshots_dir)

        # Initialize core components
        self.device_registry = DeviceRegistry(
            config_path=self.config_dir / "devices.yaml"
        )
        self.profile_manager = ProfileManager(
            profiles_dir=self.config_dir / "calibration_profiles"
        )
        self.job_logger = JobLogger(logs_dir=self.logs_dir / "jobs")
        self.action_executor = ActionExecutor(
            device_registry=self.device_registry,
            profile_manager=self.profile_manager,
            screenshots_dir=self.screenshots_dir,
        )

        # Active calibration sessions
        self._calibration_sessions: Dict[str, CalibrationWorkbench] = {}

        # ADB observers (lazy initialization)
        self._adb_observers: Dict[str, ADBObserver] = {}

        logger.info("Device Farm Service initialized")

    # =========================================================================
    # Device Management
    # =========================================================================

    def list_devices(
        self,
        status: Optional[DeviceStatus] = None,
        include_disabled: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List all devices with optional filtering.

        Args:
            status: Filter by device status
            include_disabled: Include disabled devices

        Returns:
            List of device dictionaries
        """
        devices = self.device_registry.list_devices(
            status=status,
            include_disabled=include_disabled,
        )
        return [device.to_dict() for device in devices]

    def get_device_status(self, phone_id: str) -> Dict[str, Any]:
        """
        Get detailed device status.

        Args:
            phone_id: Device identifier

        Returns:
            Device status dictionary with additional runtime info

        Raises:
            DeviceNotFoundError: If device not found
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        status_info = device.to_dict()

        # Add ADB connectivity status
        try:
            observer = self._get_adb_observer(device)
            adb_connected = observer.is_connected()
            status_info["adb_connected"] = adb_connected

            if adb_connected:
                status_info["screen_on"] = observer.is_screen_on()
        except Exception as e:
            logger.warning(f"Failed to check ADB status for {phone_id}: {e}")
            status_info["adb_connected"] = False

        # Add calibration status
        if device.calibration_profile:
            profile = self.profile_manager.load_profile(device.calibration_profile)
            status_info["calibration_valid"] = profile is not None
            if profile:
                status_info["calibration_points_count"] = len(profile.points)
        else:
            status_info["calibration_valid"] = False

        return status_info

    def update_device_state(
        self,
        phone_id: str,
        status: Optional[DeviceStatus] = None,
        calibration_profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Update device state.

        Args:
            phone_id: Device identifier
            status: New device status
            calibration_profile: New calibration profile name
            metadata: Additional metadata to merge

        Returns:
            Updated device dictionary

        Raises:
            DeviceNotFoundError: If device not found
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        if status is not None:
            self.device_registry.update_device_status(phone_id, status)
            logger.info(f"Updated device {phone_id} status to {status.value}")

        if calibration_profile is not None:
            device.calibration_profile = calibration_profile
            device.last_updated = datetime.now().isoformat()
            self.device_registry._save()
            logger.info(f"Updated device {phone_id} calibration profile to {calibration_profile}")

        if metadata is not None:
            device.metadata.update(metadata)
            device.last_updated = datetime.now().isoformat()
            self.device_registry._save()
            logger.info(f"Updated device {phone_id} metadata")

        return device.to_dict()

    # =========================================================================
    # Calibration
    # =========================================================================

    def start_calibration_session(
        self,
        phone_id: str,
        profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start a calibration session for a device.

        Args:
            phone_id: Device identifier
            profile_id: Profile ID to create/update. Auto-generated if None.

        Returns:
            Session info with profile_id and initial screenshot path

        Raises:
            DeviceNotFoundError: If device not found
            CalibrationSessionError: If session cannot be started
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        if phone_id in self._calibration_sessions:
            raise CalibrationSessionError(
                f"Calibration session already active for {phone_id}"
            )

        # Generate profile ID if not provided
        if profile_id is None:
            profile_id = f"{phone_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            # Create calibration workbench
            workbench = CalibrationWorkbench(
                adb_serial=device.adb_serial,
                ch9329_port=device.ch9329_port,
                screen_width=device.screen["width"],
                screen_height=device.screen["height"],
                profile_id=profile_id,
                profile_manager=self.profile_manager,
            )

            # Start calibration
            screenshot_path = workbench.start_calibration()

            # Store session
            self._calibration_sessions[phone_id] = workbench

            logger.info(f"Started calibration session for {phone_id} with profile {profile_id}")

            return {
                "phone_id": phone_id,
                "profile_id": profile_id,
                "screenshot_path": str(screenshot_path),
                "screen": device.screen,
            }

        except Exception as e:
            logger.error(f"Failed to start calibration session for {phone_id}: {e}")
            raise CalibrationSessionError(f"Failed to start calibration: {e}")

    def save_calibration_point(
        self,
        phone_id: str,
        point_name: str,
        x: int,
        y: int,
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Save a calibration point in active session.

        Args:
            phone_id: Device identifier
            point_name: Point identifier (e.g., "xhs.home.publish_button")
            x: X coordinate in pixels
            y: Y coordinate in pixels
            description: Human-readable description

        Returns:
            Saved point info

        Raises:
            CalibrationSessionError: If no active session
        """
        workbench = self._calibration_sessions.get(phone_id)
        if workbench is None:
            raise CalibrationSessionError(
                f"No active calibration session for {phone_id}"
            )

        try:
            point = workbench.save_point(
                point_name=point_name,
                x=x,
                y=y,
                description=description,
            )

            logger.info(f"Saved calibration point {point_name} for {phone_id}")

            return {
                "point_name": point.name,
                "x": point.x,
                "y": point.y,
                "description": point.description,
            }

        except Exception as e:
            logger.error(f"Failed to save calibration point: {e}")
            raise CalibrationSessionError(f"Failed to save point: {e}")

    def test_calibration_point(
        self,
        phone_id: str,
        point_name: str,
    ) -> Dict[str, Any]:
        """
        Test a calibration point by clicking it.

        Args:
            phone_id: Device identifier
            point_name: Point identifier to test

        Returns:
            Test result with before/after screenshots

        Raises:
            CalibrationSessionError: If no active session or point not found
        """
        workbench = self._calibration_sessions.get(phone_id)
        if workbench is None:
            raise CalibrationSessionError(
                f"No active calibration session for {phone_id}"
            )

        try:
            before_path, after_path = workbench.test_point(point_name)

            logger.info(f"Tested calibration point {point_name} for {phone_id}")

            return {
                "point_name": point_name,
                "screenshot_before": str(before_path),
                "screenshot_after": str(after_path),
            }

        except Exception as e:
            logger.error(f"Failed to test calibration point: {e}")
            raise CalibrationSessionError(f"Failed to test point: {e}")

    def finish_calibration_session(
        self,
        phone_id: str,
        assign_to_device: bool = True,
    ) -> Dict[str, Any]:
        """
        Finish calibration session and save profile.

        Args:
            phone_id: Device identifier
            assign_to_device: Automatically assign profile to device

        Returns:
            Profile info

        Raises:
            CalibrationSessionError: If no active session
        """
        workbench = self._calibration_sessions.get(phone_id)
        if workbench is None:
            raise CalibrationSessionError(
                f"No active calibration session for {phone_id}"
            )

        try:
            # Finish and save profile
            profile = workbench.finish_calibration()

            # Assign to device if requested
            if assign_to_device:
                self.update_device_state(
                    phone_id=phone_id,
                    calibration_profile=profile.profile_id,
                    status=DeviceStatus.IDLE,
                )

            # Remove session
            del self._calibration_sessions[phone_id]

            logger.info(f"Finished calibration session for {phone_id}")

            return {
                "profile_id": profile.profile_id,
                "points_count": len(profile.points),
                "assigned_to_device": assign_to_device,
            }

        except Exception as e:
            logger.error(f"Failed to finish calibration session: {e}")
            raise CalibrationSessionError(f"Failed to finish calibration: {e}")

    def cancel_calibration_session(self, phone_id: str) -> None:
        """
        Cancel active calibration session without saving.

        Args:
            phone_id: Device identifier
        """
        if phone_id in self._calibration_sessions:
            del self._calibration_sessions[phone_id]
            logger.info(f"Cancelled calibration session for {phone_id}")

    # =========================================================================
    # Job Execution
    # =========================================================================

    def submit_job(
        self,
        phone_id: str,
        flow_id: str,
        job_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Submit a job for execution.

        Args:
            phone_id: Device identifier
            flow_id: Flow identifier (path to flow YAML file)
            job_data: Job-specific data (variables for flow)
            metadata: Optional job metadata

        Returns:
            Job ID

        Raises:
            DeviceNotFoundError: If device not found
            JobExecutionError: If job cannot be submitted
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        # Check device status
        if device.status not in [DeviceStatus.IDLE, DeviceStatus.COOLDOWN]:
            raise JobExecutionError(
                f"Device {phone_id} is not available (status: {device.status.value})"
            )

        # Generate job ID
        job_id = f"{phone_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        try:
            # Create job log
            job_log = self.job_logger.create_job_log(
                job_id=job_id,
                phone_id=phone_id,
                flow_id=flow_id,
                metadata=metadata,
            )

            # Update device status
            self.device_registry.update_device_status(phone_id, DeviceStatus.RUNNING)

            # Start job execution (async in real implementation)
            self._execute_job(job_id, device, flow_id, job_data)

            logger.info(f"Submitted job {job_id} for device {phone_id}")

            return job_id

        except Exception as e:
            logger.error(f"Failed to submit job: {e}")
            raise JobExecutionError(f"Failed to submit job: {e}")

    def _execute_job(
        self,
        job_id: str,
        device: Device,
        flow_id: str,
        job_data: Dict[str, Any],
    ) -> None:
        """
        Execute a job (internal method).

        Args:
            job_id: Job identifier
            device: Device configuration
            flow_id: Flow file path
            job_data: Job data/variables
        """
        try:
            # Start job
            self.job_logger.start_job(job_id)

            # Parse flow
            flow = parse_flow(flow_id)

            # Execute flow
            self.action_executor.execute_flow(
                phone_id=device.phone_id,
                flow=flow,
                context=job_data,
                job_logger=self.job_logger,
                job_id=job_id,
            )

            # Complete job
            self.job_logger.complete_job(job_id)
            self.device_registry.update_device_status(device.phone_id, DeviceStatus.IDLE)

            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            self.job_logger.fail_job(job_id, error=str(e))
            self.device_registry.update_device_status(device.phone_id, DeviceStatus.BLOCKED)

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get job execution status.

        Args:
            job_id: Job identifier

        Returns:
            Job status dictionary

        Raises:
            JobExecutionError: If job not found
        """
        try:
            job_log = self.job_logger.get_job_log(job_id)
            if job_log is None:
                raise JobExecutionError(f"Job {job_id} not found")

            return job_log.to_dict()

        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise JobExecutionError(f"Failed to get job status: {e}")

    def get_job_logs(
        self,
        phone_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Query job logs with filters.

        Args:
            phone_id: Filter by device
            status: Filter by job status
            limit: Maximum number of results

        Returns:
            List of job log dictionaries
        """
        try:
            job_logs = self.job_logger.query_logs(
                phone_id=phone_id,
                status=status,
                limit=limit,
            )

            return [log.to_dict() for log in job_logs]

        except Exception as e:
            logger.error(f"Failed to query job logs: {e}")
            return []

    # =========================================================================
    # Screenshot Viewing
    # =========================================================================

    def get_latest_screenshot(self, phone_id: str) -> Optional[str]:
        """
        Get path to latest screenshot for a device.

        Args:
            phone_id: Device identifier

        Returns:
            Screenshot file path or None if not found

        Raises:
            DeviceNotFoundError: If device not found
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        # Find latest screenshot in screenshots directory
        device_screenshots = list(self.screenshots_dir.glob(f"{phone_id}_*.png"))

        if not device_screenshots:
            return None

        # Sort by modification time
        latest = max(device_screenshots, key=lambda p: p.stat().st_mtime)
        return str(latest)

    def capture_screenshot(self, phone_id: str) -> str:
        """
        Capture a new screenshot from device.

        Args:
            phone_id: Device identifier

        Returns:
            Screenshot file path

        Raises:
            DeviceNotFoundError: If device not found
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        try:
            observer = self._get_adb_observer(device)
            screenshot_path = self.action_executor.capture_screenshot(
                phone_id=phone_id,
                prefix="manual",
            )

            logger.info(f"Captured screenshot for {phone_id}: {screenshot_path}")
            return str(screenshot_path)

        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            raise FarmServiceError(f"Failed to capture screenshot: {e}")

    # =========================================================================
    # Manual Recovery
    # =========================================================================

    def retry_failed_step(self, job_id: str, step_id: str) -> Dict[str, Any]:
        """
        Retry a failed step in a job.

        Args:
            job_id: Job identifier
            step_id: Step identifier to retry

        Returns:
            Retry result

        Raises:
            JobExecutionError: If job/step not found or cannot retry
        """
        try:
            job_log = self.job_logger.get_job_log(job_id)
            if job_log is None:
                raise JobExecutionError(f"Job {job_id} not found")

            # Find the failed step
            step_log = next((s for s in job_log.action_log if s.step_id == step_id), None)
            if step_log is None:
                raise JobExecutionError(f"Step {step_id} not found in job {job_id}")

            if step_log.result != StepResult.FAILED:
                raise JobExecutionError(f"Step {step_id} is not in failed state")

            # Get device
            device = self.device_registry.get_device(job_log.phone_id)
            if device is None:
                raise DeviceNotFoundError(f"Device {job_log.phone_id} not found")

            # TODO: Implement step retry logic
            # This would require re-parsing the flow and executing from the failed step

            logger.info(f"Retrying step {step_id} in job {job_id}")

            return {
                "job_id": job_id,
                "step_id": step_id,
                "status": "retry_initiated",
            }

        except Exception as e:
            logger.error(f"Failed to retry step: {e}")
            raise JobExecutionError(f"Failed to retry step: {e}")

    def mark_job_handled(self, job_id: str, resolution: str) -> None:
        """
        Mark a failed job as manually handled.

        Args:
            job_id: Job identifier
            resolution: Resolution description

        Raises:
            JobExecutionError: If job not found
        """
        try:
            job_log = self.job_logger.get_job_log(job_id)
            if job_log is None:
                raise JobExecutionError(f"Job {job_id} not found")

            # Add resolution to metadata
            job_log.metadata["manual_resolution"] = resolution
            job_log.metadata["resolved_at"] = datetime.now().isoformat()

            # Update device status if needed
            device = self.device_registry.get_device(job_log.phone_id)
            if device and device.status == DeviceStatus.BLOCKED:
                self.device_registry.update_device_status(
                    job_log.phone_id,
                    DeviceStatus.IDLE,
                )

            self.job_logger._save_log(job_log)

            logger.info(f"Marked job {job_id} as handled: {resolution}")

        except Exception as e:
            logger.error(f"Failed to mark job as handled: {e}")
            raise JobExecutionError(f"Failed to mark job as handled: {e}")

    def recalibrate_device(self, phone_id: str) -> Dict[str, Any]:
        """
        Mark device as needing recalibration and start session.

        Args:
            phone_id: Device identifier

        Returns:
            Calibration session info

        Raises:
            DeviceNotFoundError: If device not found
        """
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise DeviceNotFoundError(f"Device {phone_id} not found")

        # Update device status
        self.device_registry.update_device_status(
            phone_id,
            DeviceStatus.NEEDS_CALIBRATION,
        )

        # Start calibration session
        return self.start_calibration_session(phone_id)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_adb_observer(self, device: Device) -> ADBObserver:
        """
        Get or create ADB observer for device.

        Args:
            device: Device configuration

        Returns:
            ADBObserver instance
        """
        if device.phone_id not in self._adb_observers:
            observer = ADBObserver(device.adb_serial)
            self._adb_observers[device.phone_id] = observer

        return self._adb_observers[device.phone_id]

    def shutdown(self) -> None:
        """Shutdown service and cleanup resources."""
        logger.info("Shutting down Device Farm Service")

        # Close all ADB observers
        for observer in self._adb_observers.values():
            try:
                observer.disconnect()
            except Exception as e:
                logger.warning(f"Error closing ADB observer: {e}")

        # Close all CH9329 controllers
        for controller in self.action_executor._ch9329_cache.values():
            try:
                controller.disconnect()
            except Exception as e:
                logger.warning(f"Error closing CH9329 controller: {e}")

        logger.info("Device Farm Service shutdown complete")
