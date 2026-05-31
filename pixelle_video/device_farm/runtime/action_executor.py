"""Action Executor for translating DSL actions to CH9329/ADB operations.

This module executes automation flows by:
- Resolving semantic point names via calibration profiles
- Translating high-level actions to hardware operations
- Managing execution state and logging
- Capturing failure screenshots for debugging
"""

import hashlib
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from pixelle_video.device_farm.calibration.profile_manager import (
    CalibrationPoint,
    ProfileManager,
)
from pixelle_video.device_farm.hardware.adb_observer import (
    ADBError,
    capture_screenshot,
    check_device_connectivity,
)
from pixelle_video.device_farm.registry.device_registry import Device, DeviceRegistry
from pixelle_video.device_farm.runtime.action_dsl import (
    ActionStep,
    ActionType,
    Flow,
    VerifyType,
    load_flow,
)
from pixelle_video.utils.ch9329 import CH9329Controller


class ActionExecutionError(Exception):
    """Raised when action execution fails."""

    pass


@dataclass
class StepResult:
    """Result of executing a single step.

    Attributes:
        step_id: ID of the executed step
        success: Whether the step succeeded
        duration: Execution time in seconds
        error: Error message if failed
        screenshot_path: Path to screenshot if captured
        metadata: Additional result data
    """

    step_id: str
    success: bool
    duration: float
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "step_id": self.step_id,
            "success": self.success,
            "duration": self.duration,
            "error": self.error,
            "screenshot_path": self.screenshot_path,
            "metadata": self.metadata,
        }


@dataclass
class FlowResult:
    """Result of executing a complete flow.

    Attributes:
        flow_id: ID of the executed flow
        phone_id: Device that executed the flow
        success: Whether the entire flow succeeded
        step_results: Results for each step
        total_duration: Total execution time in seconds
        started_at: ISO timestamp when flow started
        completed_at: ISO timestamp when flow completed
    """

    flow_id: str
    phone_id: str
    success: bool
    step_results: List[StepResult]
    total_duration: float
    started_at: str
    completed_at: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "flow_id": self.flow_id,
            "phone_id": self.phone_id,
            "success": self.success,
            "step_results": [r.to_dict() for r in self.step_results],
            "total_duration": self.total_duration,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class ActionExecutor:
    """Executes automation flows by translating DSL actions to hardware operations."""

    def __init__(
        self,
        device_registry: DeviceRegistry,
        profile_manager: ProfileManager,
        screenshots_dir: Optional[str] = None,
    ):
        """Initialize action executor.

        Args:
            device_registry: Registry for device configurations
            profile_manager: Manager for calibration profiles
            screenshots_dir: Directory for saving screenshots.
                           Defaults to runtime/screenshots/
        """
        self.device_registry = device_registry
        self.profile_manager = profile_manager

        # Set up screenshots directory
        if screenshots_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            screenshots_dir = project_root / "runtime" / "screenshots"
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Cache for CH9329 controllers (one per device)
        self._ch9329_cache: Dict[str, CH9329Controller] = {}

        # Cache for last screenshot hash (for verification)
        self._last_screenshot_hash: Dict[str, str] = {}

    def _get_ch9329_controller(self, device: Device) -> CH9329Controller:
        """Get or create CH9329 controller for a device.

        Args:
            device: Device configuration

        Returns:
            CH9329Controller instance
        """
        if device.phone_id not in self._ch9329_cache:
            controller = CH9329Controller(
                port=device.ch9329_port,
                baudrate=9600,
                timeout=0.5,
            )
            # Set screen dimensions from device config
            controller.screen_width = device.screen["width"]
            controller.screen_height = device.screen["height"]
            self._ch9329_cache[device.phone_id] = controller

        return self._ch9329_cache[device.phone_id]

    def _resolve_point(
        self, device: Device, point_name: str
    ) -> Tuple[float, float]:
        """Resolve semantic point name to screen coordinates.

        Args:
            device: Device configuration
            point_name: Semantic point name (e.g., "xhs.home.publish_button")

        Returns:
            Tuple of (x_ratio, y_ratio) in range [0.0, 1.0]

        Raises:
            ActionExecutionError: If point cannot be resolved
        """
        if not device.calibration_profile:
            raise ActionExecutionError(
                f"Device {device.phone_id} has no calibration profile assigned"
            )

        # Load calibration profile
        profile = self.profile_manager.load_profile(device.calibration_profile)
        if profile is None:
            raise ActionExecutionError(
                f"Calibration profile '{device.calibration_profile}' not found"
            )

        # Get calibration point
        point = profile.get_point(point_name)
        if point is None:
            raise ActionExecutionError(
                f"Point '{point_name}' not found in profile '{device.calibration_profile}'"
            )

        # Convert absolute coordinates to ratios
        x_ratio = point.x / profile.screen.width
        y_ratio = point.y / profile.screen.height

        logger.debug(
            f"Resolved point '{point_name}' to ({x_ratio:.4f}, {y_ratio:.4f}) "
            f"[{point.x}, {point.y}]"
        )

        return x_ratio, y_ratio

    def _execute_tap(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute tap action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If tap fails
        """
        if not step.point:
            raise ActionExecutionError(f"Step {step.id}: tap action requires 'point'")

        x_ratio, y_ratio = self._resolve_point(device, step.point)
        controller = self._get_ch9329_controller(device)

        logger.info(f"Tapping point '{step.point}' at ({x_ratio:.4f}, {y_ratio:.4f})")
        if not controller.click(x_ratio, y_ratio):
            raise ActionExecutionError(f"Failed to tap point '{step.point}'")

    def _execute_swipe(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute swipe action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If swipe fails
        """
        # Swipe requires 'from' and 'to' points in metadata
        from_point = step.metadata.get("from")
        to_point = step.metadata.get("to")

        if not from_point or not to_point:
            raise ActionExecutionError(
                f"Step {step.id}: swipe action requires 'from' and 'to' in metadata"
            )

        from_x, from_y = self._resolve_point(device, from_point)
        to_x, to_y = self._resolve_point(device, to_point)

        controller = self._get_ch9329_controller(device)

        logger.info(
            f"Swiping from '{from_point}' ({from_x:.4f}, {from_y:.4f}) "
            f"to '{to_point}' ({to_x:.4f}, {to_y:.4f})"
        )

        # Move to start position
        if not controller.move_to(from_x, from_y):
            raise ActionExecutionError(f"Failed to move to start point '{from_point}'")

        time.sleep(0.1)

        # Press and hold
        if not controller._send_rel_mouse(0x01, 0, 0):
            raise ActionExecutionError("Failed to press mouse button")

        time.sleep(0.1)

        # Calculate swipe steps
        duration = step.metadata.get("duration", 0.5)  # Default 0.5s swipe
        steps = int(duration * 60)  # 60 steps per second
        steps = max(10, min(steps, 100))  # Clamp to [10, 100]

        # Calculate delta per step
        delta_x = (to_x - from_x) / steps
        delta_y = (to_y - from_y) / steps

        # Execute swipe
        for i in range(steps):
            current_x = from_x + delta_x * (i + 1)
            current_y = from_y + delta_y * (i + 1)

            # Convert to pixel deltas for relative movement
            pixel_delta_x = int(delta_x * device.screen["width"])
            pixel_delta_y = int(delta_y * device.screen["height"])

            # Clamp to CH9329 limits [-127, 127]
            pixel_delta_x = max(-127, min(127, pixel_delta_x))
            pixel_delta_y = max(-127, min(127, pixel_delta_y))

            if not controller._send_rel_mouse(0x01, pixel_delta_x, pixel_delta_y):
                raise ActionExecutionError(f"Failed to swipe at step {i}")

            time.sleep(duration / steps)

        # Release
        if not controller._send_rel_mouse(0x00, 0, 0):
            raise ActionExecutionError("Failed to release mouse button")

        time.sleep(0.1)

    def _execute_input_text(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute input_text action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If input fails
        """
        if not step.value:
            raise ActionExecutionError(
                f"Step {step.id}: input_text action requires 'value'"
            )

        # Tap the input field first if point is specified
        if step.point:
            x_ratio, y_ratio = self._resolve_point(device, step.point)
            controller = self._get_ch9329_controller(device)

            logger.info(f"Tapping input field '{step.point}'")
            if not controller.click(x_ratio, y_ratio):
                raise ActionExecutionError(
                    f"Failed to tap input field '{step.point}'"
                )

            time.sleep(0.5)  # Wait for keyboard to appear

        # Use ADB clipboard paste (preferred method for Chinese text)
        logger.info(f"Inputting text via ADB clipboard: {step.value[:50]}...")

        try:
            # Set clipboard content
            subprocess.run(
                ["adb", "-s", device.adb_serial, "shell", "input", "text", f'"{step.value}"'],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            # Fallback: try setting clipboard and pasting
            try:
                # Escape special characters for shell
                escaped_value = step.value.replace('"', '\\"').replace("'", "\\'")

                # Set clipboard
                subprocess.run(
                    [
                        "adb",
                        "-s",
                        device.adb_serial,
                        "shell",
                        "am",
                        "broadcast",
                        "-a",
                        "clipper.set",
                        "-e",
                        "text",
                        escaped_value,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )

                # Paste via keyevent
                subprocess.run(
                    [
                        "adb",
                        "-s",
                        device.adb_serial,
                        "shell",
                        "input",
                        "keyevent",
                        "KEYCODE_PASTE",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.CalledProcessError as e2:
                raise ActionExecutionError(
                    f"Failed to input text via ADB: {e2.stderr.decode('utf-8', errors='replace')}"
                )

    def _execute_wait(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute wait action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context
        """
        duration = step.metadata.get("duration", 1.0)
        logger.info(f"Waiting for {duration}s")
        time.sleep(duration)

    def _execute_screenshot(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> str:
        """Execute screenshot action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Returns:
            Path to saved screenshot

        Raises:
            ActionExecutionError: If screenshot fails
        """
        label = step.metadata.get("label", step.id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{device.phone_id}_{label}_{timestamp}.png"
        output_path = self.screenshots_dir / filename

        logger.info(f"Capturing screenshot: {filename}")

        try:
            capture_screenshot(device.adb_serial, str(output_path))
            return str(output_path)
        except ADBError as e:
            raise ActionExecutionError(f"Failed to capture screenshot: {e}")

    def _execute_open_app(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute open_app action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If app launch fails
        """
        package = step.metadata.get("package")
        if not package:
            raise ActionExecutionError(
                f"Step {step.id}: open_app action requires 'package' in metadata"
            )

        activity = step.metadata.get("activity")
        logger.info(f"Opening app: {package}" + (f"/{activity}" if activity else ""))

        try:
            cmd = ["adb", "-s", device.adb_serial, "shell", "am", "start"]
            if activity:
                cmd.append(f"{package}/{activity}")
            else:
                cmd.extend(["-n", package])

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            raise ActionExecutionError(
                f"Failed to open app {package}: {e.stderr.decode('utf-8', errors='replace')}"
            )

    def _execute_back(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute back action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If back action fails
        """
        logger.info("Executing back action")

        try:
            subprocess.run(
                [
                    "adb",
                    "-s",
                    device.adb_serial,
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_BACK",
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            raise ActionExecutionError(
                f"Failed to execute back: {e.stderr.decode('utf-8', errors='replace')}"
            )

    def _execute_home(
        self, device: Device, step: ActionStep, context: Dict[str, Any]
    ) -> None:
        """Execute home action.

        Args:
            device: Target device
            step: Action step to execute
            context: Execution context

        Raises:
            ActionExecutionError: If home action fails
        """
        logger.info("Executing home action")

        try:
            subprocess.run(
                [
                    "adb",
                    "-s",
                    device.adb_serial,
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_HOME",
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            raise ActionExecutionError(
                f"Failed to execute home: {e.stderr.decode('utf-8', errors='replace')}"
            )

    def _verify_screenshot_changed(
        self, device: Device, step: ActionStep
    ) -> bool:
        """Verify that screenshot has changed since last capture.

        Args:
            device: Target device
            step: Action step being verified

        Returns:
            True if screenshot changed, False otherwise
        """
        try:
            # Capture current screenshot
            img_data = capture_screenshot(device.adb_serial)

            # Calculate hash
            current_hash = hashlib.sha256(img_data).hexdigest()

            # Compare with last hash
            last_hash = self._last_screenshot_hash.get(device.phone_id)
            if last_hash is None:
                # First screenshot, consider it changed
                self._last_screenshot_hash[device.phone_id] = current_hash
                return True

            changed = current_hash != last_hash
            self._last_screenshot_hash[device.phone_id] = current_hash

            logger.info(
                f"Screenshot verification: {'CHANGED' if changed else 'UNCHANGED'}"
            )
            return changed

        except ADBError as e:
            logger.warning(f"Screenshot verification failed: {e}")
            return False

    def _verify_manual_confirm(
        self, device: Device, step: ActionStep
    ) -> bool:
        """Pause execution and wait for manual confirmation.

        Args:
            device: Target device
            step: Action step being verified

        Returns:
            True if user confirms, False otherwise
        """
        logger.warning(
            f"Manual confirmation required for step '{step.id}' on device {device.phone_id}"
        )
        response = input("Continue? (y/n): ").strip().lower()
        return response == "y"

    def execute_step(
        self,
        phone_id: str,
        step: ActionStep,
        context: Optional[Dict[str, Any]] = None,
    ) -> StepResult:
        """Execute a single action step.

        Args:
            phone_id: Device identifier
            step: Action step to execute
            context: Optional execution context (e.g., job data)

        Returns:
            StepResult with execution outcome

        Raises:
            ActionExecutionError: If device not found or not ready
        """
        if context is None:
            context = {}

        start_time = time.time()
        screenshot_path = None
        error = None

        try:
            # Get device configuration
            device = self.device_registry.get_device(phone_id)
            if device is None:
                raise ActionExecutionError(f"Device {phone_id} not found in registry")

            # Check device connectivity
            if not check_device_connectivity(device.adb_serial):
                raise ActionExecutionError(
                    f"Device {phone_id} (ADB: {device.adb_serial}) is not connected"
                )

            logger.info(
                f"Executing step '{step.id}' (action: {step.action.value}) on device {phone_id}"
            )

            # Execute action based on type
            if step.action == ActionType.TAP:
                self._execute_tap(device, step, context)
            elif step.action == ActionType.SWIPE:
                self._execute_swipe(device, step, context)
            elif step.action == ActionType.INPUT_TEXT:
                self._execute_input_text(device, step, context)
            elif step.action == ActionType.WAIT:
                self._execute_wait(device, step, context)
            elif step.action == ActionType.SCREENSHOT:
                screenshot_path = self._execute_screenshot(device, step, context)
            elif step.action == ActionType.OPEN_APP:
                self._execute_open_app(device, step, context)
            elif step.action == ActionType.BACK:
                self._execute_back(device, step, context)
            elif step.action == ActionType.HOME:
                self._execute_home(device, step, context)
            else:
                raise ActionExecutionError(
                    f"Unsupported action type: {step.action.value}"
                )

            # Wait after action if specified
            if step.wait_after > 0:
                logger.debug(f"Waiting {step.wait_after}s after action")
                time.sleep(step.wait_after)

            # Perform verification
            verification_passed = True
            if step.verify == VerifyType.SCREENSHOT_CHANGED:
                verification_passed = self._verify_screenshot_changed(device, step)
                if not verification_passed:
                    logger.warning(
                        f"Verification failed: screenshot did not change for step '{step.id}'"
                    )
            elif step.verify == VerifyType.MANUAL_CONFIRM:
                verification_passed = self._verify_manual_confirm(device, step)
                if not verification_passed:
                    raise ActionExecutionError("Manual confirmation rejected")

            duration = time.time() - start_time
            logger.info(
                f"Step '{step.id}' completed successfully in {duration:.2f}s"
            )

            return StepResult(
                step_id=step.id,
                success=True,
                duration=duration,
                screenshot_path=screenshot_path,
                metadata={"verification_passed": verification_passed},
            )

        except Exception as e:
            duration = time.time() - start_time
            error = str(e)
            logger.error(f"Step '{step.id}' failed after {duration:.2f}s: {error}")

            # Capture failure screenshot
            try:
                device = self.device_registry.get_device(phone_id)
                if device:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{phone_id}_FAIL_{step.id}_{timestamp}.png"
                    screenshot_path = str(self.screenshots_dir / filename)
                    capture_screenshot(device.adb_serial, screenshot_path)
                    logger.info(f"Failure screenshot saved: {screenshot_path}")
            except Exception as screenshot_error:
                logger.warning(f"Failed to capture failure screenshot: {screenshot_error}")

            return StepResult(
                step_id=step.id,
                success=False,
                duration=duration,
                error=error,
                screenshot_path=screenshot_path,
            )

    def execute_flow(
        self,
        phone_id: str,
        flow_id: str,
        job_data: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute a complete automation flow.

        Args:
            phone_id: Device identifier
            flow_id: Flow identifier to execute
            job_data: Optional job-specific data to pass to steps

        Returns:
            FlowResult with execution outcome
        """
        started_at = datetime.now().isoformat()
        start_time = time.time()
        step_results: List[StepResult] = []

        logger.info(f"Starting flow '{flow_id}' on device {phone_id}")

        try:
            # Load flow definition
            flow = load_flow(flow_id)

            # Prepare execution context
            context = {"job_data": job_data or {}, "flow_id": flow_id}

            # Execute each step
            for step in flow.steps:
                result = self.execute_step(phone_id, step, context)
                step_results.append(result)

                # Stop on first failure unless continue_on_error is set
                if not result.success and not step.metadata.get("continue_on_error", False):
                    logger.error(
                        f"Flow '{flow_id}' stopped at step '{step.id}' due to failure"
                    )
                    break

            # Determine overall success
            success = all(r.success for r in step_results)

            total_duration = time.time() - start_time
            completed_at = datetime.now().isoformat()

            logger.info(
                f"Flow '{flow_id}' {'completed successfully' if success else 'failed'} "
                f"in {total_duration:.2f}s ({len(step_results)}/{len(flow.steps)} steps)"
            )

            return FlowResult(
                flow_id=flow_id,
                phone_id=phone_id,
                success=success,
                step_results=step_results,
                total_duration=total_duration,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            total_duration = time.time() - start_time
            completed_at = datetime.now().isoformat()

            logger.error(f"Flow '{flow_id}' failed with exception: {e}")

            return FlowResult(
                flow_id=flow_id,
                phone_id=phone_id,
                success=False,
                step_results=step_results,
                total_duration=total_duration,
                started_at=started_at,
                completed_at=completed_at,
            )

    def cleanup(self):
        """Clean up resources (disconnect CH9329 controllers)."""
        logger.info("Cleaning up action executor resources")
        for phone_id, controller in self._ch9329_cache.items():
            try:
                controller.disconnect()
                logger.debug(f"Disconnected CH9329 controller for {phone_id}")
            except Exception as e:
                logger.warning(
                    f"Error disconnecting CH9329 for {phone_id}: {e}"
                )
        self._ch9329_cache.clear()
