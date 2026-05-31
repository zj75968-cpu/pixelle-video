# -*- coding: utf-8 -*-
"""
Calibration Workbench API/Service for interactive device calibration.

Provides orchestration for:
- Loading devices by phone_id
- Capturing screenshots via ADB
- Accepting click coordinates on screenshots
- Saving semantic points with name and description
- Testing points immediately via CH9329
- Capturing after-click screenshots for verification
- Comparing before/after screenshots (basic change detection)
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from loguru import logger

from pixelle_video.device_farm.registry.device_registry import DeviceRegistry, Device
from pixelle_video.device_farm.hardware.adb_observer import capture_screenshot, check_device_connectivity, ADBError
from pixelle_video.utils.ch9329 import CH9329Controller


class CalibrationError(Exception):
    """Base exception for calibration-related errors."""
    pass


@dataclass
class SemanticPoint:
    """Represents a calibrated semantic point on the device screen."""
    name: str
    x: int  # Pixel coordinates
    y: int
    x_ratio: float  # Normalized ratio (0.0-1.0)
    y_ratio: float
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_tested: Optional[str] = None
    test_success: Optional[bool] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SemanticPoint':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CalibrationProfile:
    """Calibration profile containing semantic points for a device."""
    phone_id: str
    profile_name: str
    screen_width: int
    screen_height: int
    points: Dict[str, SemanticPoint] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_point(self, point: SemanticPoint) -> None:
        """Add or update a semantic point."""
        self.points[point.name] = point
        self.last_modified = datetime.now().isoformat()

    def get_point(self, name: str) -> Optional[SemanticPoint]:
        """Get a semantic point by name."""
        return self.points.get(name)

    def remove_point(self, name: str) -> bool:
        """Remove a semantic point by name."""
        if name in self.points:
            del self.points[name]
            self.last_modified = datetime.now().isoformat()
            return True
        return False

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['points'] = {name: point.to_dict() for name, point in self.points.items()}
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'CalibrationProfile':
        """Create from dictionary."""
        data = data.copy()
        points_data = data.pop('points', {})
        profile = cls(**data)
        profile.points = {name: SemanticPoint.from_dict(point_data)
                         for name, point_data in points_data.items()}
        return profile


@dataclass
class CalibrationSession:
    """Active calibration session state."""
    phone_id: str
    device: Device
    profile: CalibrationProfile
    ch9329: CH9329Controller
    screenshots_dir: Path
    current_screenshot: Optional[bytes] = None
    current_screenshot_path: Optional[str] = None
    last_action_screenshot: Optional[bytes] = None
    last_action_screenshot_path: Optional[str] = None
    session_start: str = field(default_factory=lambda: datetime.now().isoformat())


class CalibrationWorkbench:
    """
    Orchestration service for interactive device calibration.

    Manages calibration sessions, coordinates between device registry,
    ADB observer, CH9329 controller, and profile persistence.
    """

    def __init__(
        self,
        device_registry: Optional[DeviceRegistry] = None,
        profiles_dir: Optional[str] = None,
        screenshots_dir: Optional[str] = None
    ):
        """
        Initialize calibration workbench.

        Args:
            device_registry: Device registry instance (creates default if None)
            profiles_dir: Directory for calibration profiles (default: config/calibration_profiles)
            screenshots_dir: Directory for calibration screenshots (default: runtime/calibration_screenshots)
        """
        self.device_registry = device_registry or DeviceRegistry()

        # Set up profiles directory
        if profiles_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            profiles_dir = project_root / "config" / "calibration_profiles"
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Set up screenshots directory
        if screenshots_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            screenshots_dir = project_root / "runtime" / "calibration_screenshots"
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Active sessions
        self._sessions: Dict[str, CalibrationSession] = {}

        logger.info(f"CalibrationWorkbench initialized: profiles={self.profiles_dir}, screenshots={self.screenshots_dir}")

    def start_calibration(self, phone_id: str, profile_name: Optional[str] = None) -> CalibrationSession:
        """
        Start a calibration session for a device.

        Args:
            phone_id: Device identifier
            profile_name: Optional profile name (defaults to phone_id)

        Returns:
            CalibrationSession object

        Raises:
            CalibrationError: If device not found or not ready
        """
        # Load device from registry
        device = self.device_registry.get_device(phone_id)
        if device is None:
            raise CalibrationError(f"Device not found: {phone_id}")

        # Check ADB connectivity
        if not check_device_connectivity(device.adb_serial):
            raise CalibrationError(f"Device not connected or not ready: {phone_id} (serial: {device.adb_serial})")

        # Initialize CH9329 controller
        ch9329 = CH9329Controller(port=device.ch9329_port)
        ch9329.screen_width = device.screen['width']
        ch9329.screen_height = device.screen['height']

        if not ch9329.connect():
            raise CalibrationError(f"Failed to connect to CH9329 on port {device.ch9329_port}")

        # Load or create calibration profile
        if profile_name is None:
            profile_name = phone_id

        profile = self._load_profile(phone_id, profile_name)
        if profile is None:
            profile = CalibrationProfile(
                phone_id=phone_id,
                profile_name=profile_name,
                screen_width=device.screen['width'],
                screen_height=device.screen['height']
            )
            logger.info(f"Created new calibration profile: {profile_name}")
        else:
            logger.info(f"Loaded existing calibration profile: {profile_name}")

        # Create session-specific screenshots directory
        session_screenshots_dir = self.screenshots_dir / phone_id / datetime.now().strftime("%Y%m%d_%H%M%S")
        session_screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Create session
        session = CalibrationSession(
            phone_id=phone_id,
            device=device,
            profile=profile,
            ch9329=ch9329,
            screenshots_dir=session_screenshots_dir
        )

        self._sessions[phone_id] = session
        logger.info(f"Started calibration session for {phone_id}")

        return session

    def stop_calibration(self, phone_id: str, save_profile: bool = True) -> None:
        """
        Stop a calibration session.

        Args:
            phone_id: Device identifier
            save_profile: Whether to save the profile before stopping

        Raises:
            CalibrationError: If no active session found
        """
        session = self._get_session(phone_id)

        if save_profile:
            self._save_profile(session.profile)

        # Disconnect CH9329
        session.ch9329.disconnect()

        # Remove session
        del self._sessions[phone_id]
        logger.info(f"Stopped calibration session for {phone_id}")

    def capture_screen(self, phone_id: str) -> Tuple[bytes, str]:
        """
        Capture current screenshot from device.

        Args:
            phone_id: Device identifier

        Returns:
            Tuple of (image_data, screenshot_path)

        Raises:
            CalibrationError: If capture fails
        """
        session = self._get_session(phone_id)

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            screenshot_path = session.screenshots_dir / f"screen_{timestamp}.png"

            img_data = capture_screenshot(session.device.adb_serial, str(screenshot_path))

            session.current_screenshot = img_data
            session.current_screenshot_path = str(screenshot_path)

            logger.info(f"Captured screenshot for {phone_id}: {screenshot_path}")
            return img_data, str(screenshot_path)

        except ADBError as e:
            raise CalibrationError(f"Failed to capture screenshot: {e}")

    def save_point(
        self,
        phone_id: str,
        name: str,
        x: int,
        y: int,
        description: str = ""
    ) -> SemanticPoint:
        """
        Save a semantic point with name and description.

        Args:
            phone_id: Device identifier
            name: Semantic name for the point (e.g., "home_button", "search_icon")
            x: X coordinate in pixels
            y: Y coordinate in pixels
            description: Optional description of the point

        Returns:
            SemanticPoint object

        Raises:
            CalibrationError: If coordinates are invalid
        """
        session = self._get_session(phone_id)

        # Validate coordinates
        if x < 0 or x >= session.profile.screen_width:
            raise CalibrationError(f"Invalid x coordinate: {x} (screen width: {session.profile.screen_width})")
        if y < 0 or y >= session.profile.screen_height:
            raise CalibrationError(f"Invalid y coordinate: {y} (screen height: {session.profile.screen_height})")

        # Calculate normalized ratios
        x_ratio = x / session.profile.screen_width
        y_ratio = y / session.profile.screen_height

        # Create semantic point
        point = SemanticPoint(
            name=name,
            x=x,
            y=y,
            x_ratio=x_ratio,
            y_ratio=y_ratio,
            description=description
        )

        # Add to profile
        session.profile.add_point(point)
        logger.info(f"Saved point '{name}' at ({x}, {y}) -> ratio ({x_ratio:.4f}, {y_ratio:.4f})")

        return point

    def test_point(self, phone_id: str, name: str, capture_after: bool = True) -> Dict:
        """
        Test a semantic point by clicking it via CH9329.

        Args:
            phone_id: Device identifier
            name: Name of the point to test
            capture_after: Whether to capture screenshot after clicking

        Returns:
            Dict with test results including success status and screenshot paths

        Raises:
            CalibrationError: If point not found or test fails
        """
        session = self._get_session(phone_id)

        # Get point from profile
        point = session.profile.get_point(name)
        if point is None:
            raise CalibrationError(f"Point not found: {name}")

        logger.info(f"Testing point '{name}' at ratio ({point.x_ratio:.4f}, {point.y_ratio:.4f})")

        # Capture before screenshot
        before_screenshot = None
        before_path = None
        if session.current_screenshot is None:
            before_screenshot, before_path = self.capture_screen(phone_id)
        else:
            before_screenshot = session.current_screenshot
            before_path = session.current_screenshot_path

        # Click the point via CH9329
        try:
            success = session.ch9329.click(point.x_ratio, point.y_ratio)

            # Update point test status
            point.last_tested = datetime.now().isoformat()
            point.test_success = success

            if not success:
                logger.warning(f"CH9329 click failed for point '{name}'")
                return {
                    'success': False,
                    'point': point.to_dict(),
                    'before_screenshot': before_path,
                    'after_screenshot': None,
                    'error': 'CH9329 click command failed'
                }

            logger.info(f"Successfully clicked point '{name}'")

        except Exception as e:
            logger.error(f"Error testing point '{name}': {e}")
            point.test_success = False
            raise CalibrationError(f"Failed to test point '{name}': {e}")

        # Capture after screenshot
        after_screenshot = None
        after_path = None
        if capture_after:
            time.sleep(0.5)  # Wait for UI to update
            try:
                after_screenshot, after_path = self.capture_screen(phone_id)
                session.last_action_screenshot = after_screenshot
                session.last_action_screenshot_path = after_path
            except CalibrationError as e:
                logger.warning(f"Failed to capture after-click screenshot: {e}")

        return {
            'success': True,
            'point': point.to_dict(),
            'before_screenshot': before_path,
            'after_screenshot': after_path,
            'timestamp': datetime.now().isoformat()
        }

    def compare_screenshots(
        self,
        phone_id: str,
        before_path: Optional[str] = None,
        after_path: Optional[str] = None
    ) -> Dict:
        """
        Compare before/after screenshots for basic change detection.

        Args:
            phone_id: Device identifier
            before_path: Path to before screenshot (uses session current if None)
            after_path: Path to after screenshot (uses session last_action if None)

        Returns:
            Dict with comparison results including change percentage

        Raises:
            CalibrationError: If screenshots not available or comparison fails
        """
        session = self._get_session(phone_id)

        # Determine screenshot paths
        if before_path is None:
            before_path = session.current_screenshot_path
        if after_path is None:
            after_path = session.last_action_screenshot_path

        if before_path is None or after_path is None:
            raise CalibrationError("Both before and after screenshots are required for comparison")

        try:
            # Read screenshots
            before_data = Path(before_path).read_bytes()
            after_data = Path(after_path).read_bytes()

            # Basic comparison: check if files are identical
            identical = before_data == after_data

            # Calculate simple change metric (byte-level difference)
            if identical:
                change_percentage = 0.0
            else:
                # Count differing bytes
                min_len = min(len(before_data), len(after_data))
                diff_count = sum(1 for i in range(min_len) if before_data[i] != after_data[i])
                diff_count += abs(len(before_data) - len(after_data))
                change_percentage = (diff_count / max(len(before_data), len(after_data))) * 100

            result = {
                'identical': identical,
                'change_percentage': round(change_percentage, 2),
                'before_screenshot': before_path,
                'after_screenshot': after_path,
                'before_size': len(before_data),
                'after_size': len(after_data)
            }

            logger.info(f"Screenshot comparison: {change_percentage:.2f}% change")
            return result

        except Exception as e:
            raise CalibrationError(f"Failed to compare screenshots: {e}")

    def get_profile(self, phone_id: str) -> CalibrationProfile:
        """
        Get the calibration profile for an active session.

        Args:
            phone_id: Device identifier

        Returns:
            CalibrationProfile object

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        return session.profile

    def list_points(self, phone_id: str) -> List[Dict]:
        """
        List all semantic points in the current profile.

        Args:
            phone_id: Device identifier

        Returns:
            List of point dictionaries

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        return [point.to_dict() for point in session.profile.points.values()]

    def remove_point(self, phone_id: str, name: str) -> bool:
        """
        Remove a semantic point from the profile.

        Args:
            phone_id: Device identifier
            name: Name of the point to remove

        Returns:
            True if removed, False if not found

        Raises:
            CalibrationError: If no active session
        """
        session = self._get_session(phone_id)
        removed = session.profile.remove_point(name)
        if removed:
            logger.info(f"Removed point '{name}' from profile")
        return removed

    def _get_session(self, phone_id: str) -> CalibrationSession:
        """Get active session or raise error."""
        session = self._sessions.get(phone_id)
        if session is None:
            raise CalibrationError(f"No active calibration session for {phone_id}. Call start_calibration() first.")
        return session

    def _load_profile(self, phone_id: str, profile_name: str) -> Optional[CalibrationProfile]:
        """Load calibration profile from disk."""
        profile_path = self.profiles_dir / f"{phone_id}_{profile_name}.yaml"

        if not profile_path.exists():
            return None

        try:
            import yaml
            with open(profile_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            profile = CalibrationProfile.from_dict(data)
            logger.info(f"Loaded profile from {profile_path}")
            return profile

        except Exception as e:
            logger.error(f"Failed to load profile from {profile_path}: {e}")
            return None

    def _save_profile(self, profile: CalibrationProfile) -> None:
        """Save calibration profile to disk."""
        profile_path = self.profiles_dir / f"{profile.phone_id}_{profile.profile_name}.yaml"

        try:
            import yaml
            profile.last_modified = datetime.now().isoformat()

            with open(profile_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(
                    profile.to_dict(),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )

            logger.info(f"Saved profile to {profile_path}")

        except Exception as e:
            logger.error(f"Failed to save profile to {profile_path}: {e}")
            raise CalibrationError(f"Failed to save profile: {e}")
