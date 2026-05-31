"""
Calibration Profile Manager

Manages device calibration profiles with screen dimensions and UI element coordinates.
Profiles are stored as YAML files in config/profiles/ directory.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml


class CalibrationPoint:
    """Represents a calibrated UI element coordinate."""

    def __init__(self, name: str, type: str, x: int, y: int, description: str = ""):
        """
        Initialize a calibration point.

        Args:
            name: Point identifier (e.g., "xhs.home.publish_button")
            type: Coordinate type (e.g., "absolute")
            x: X coordinate in pixels
            y: Y coordinate in pixels
            description: Human-readable description of the point
        """
        self.name = name
        self.type = type
        self.x = x
        self.y = y
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Convert point to dictionary for serialization."""
        return {
            'name': self.name,
            'type': self.type,
            'x': self.x,
            'y': self.y,
            'description': self.description
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CalibrationPoint':
        """Create point from dictionary."""
        return cls(
            name=data['name'],
            type=data['type'],
            x=data['x'],
            y=data['y'],
            description=data.get('description', '')
        )


class ScreenConfig:
    """Screen configuration for a device profile."""

    def __init__(self, width: int, height: int, safe_top: int = 0,
                 safe_bottom: int = 0, navigation_mode: str = "gesture"):
        """
        Initialize screen configuration.

        Args:
            width: Screen width in pixels
            height: Screen height in pixels
            safe_top: Top safe area offset (status bar, notch)
            safe_bottom: Bottom safe area offset (navigation bar)
            navigation_mode: Navigation type ("gesture" or "buttons")
        """
        self.width = width
        self.height = height
        self.safe_top = safe_top
        self.safe_bottom = safe_bottom
        self.navigation_mode = navigation_mode

    def to_dict(self) -> Dict[str, Any]:
        """Convert screen config to dictionary."""
        return {
            'width': self.width,
            'height': self.height,
            'safe_top': self.safe_top,
            'safe_bottom': self.safe_bottom,
            'navigation_mode': self.navigation_mode
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScreenConfig':
        """Create screen config from dictionary."""
        return cls(
            width=data['width'],
            height=data['height'],
            safe_top=data.get('safe_top', 0),
            safe_bottom=data.get('safe_bottom', 0),
            navigation_mode=data.get('navigation_mode', 'gesture')
        )


class CalibrationProfile:
    """Complete calibration profile for a device."""

    def __init__(self, profile_id: str, screen: ScreenConfig, points: List[CalibrationPoint]):
        """
        Initialize calibration profile.

        Args:
            profile_id: Unique profile identifier
            screen: Screen configuration
            points: List of calibrated points
        """
        self.profile_id = profile_id
        self.screen = screen
        self.points = points
        self._points_index = {point.name: point for point in points}

    def get_point(self, point_name: str) -> Optional[CalibrationPoint]:
        """
        Get a calibration point by name.

        Args:
            point_name: Name of the point to retrieve

        Returns:
            CalibrationPoint if found, None otherwise
        """
        return self._points_index.get(point_name)

    def add_point(self, point: CalibrationPoint) -> None:
        """Add or update a calibration point."""
        if point.name in self._points_index:
            # Update existing point
            for i, p in enumerate(self.points):
                if p.name == point.name:
                    self.points[i] = point
                    break
        else:
            # Add new point
            self.points.append(point)
        self._points_index[point.name] = point

    def to_dict(self) -> Dict[str, Any]:
        """Convert profile to dictionary for serialization."""
        return {
            'profile_id': self.profile_id,
            'screen': self.screen.to_dict(),
            'points': [point.to_dict() for point in self.points]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CalibrationProfile':
        """Create profile from dictionary."""
        screen = ScreenConfig.from_dict(data['screen'])
        points = [CalibrationPoint.from_dict(p) for p in data.get('points', [])]
        return cls(
            profile_id=data['profile_id'],
            screen=screen,
            points=points
        )


class ProfileManager:
    """Manages calibration profiles with YAML persistence."""

    def __init__(self, profiles_dir: Optional[str] = None):
        """
        Initialize profile manager.

        Args:
            profiles_dir: Directory for profile storage. Defaults to config/profiles/
        """
        if profiles_dir is None:
            # Default to config/profiles/ relative to project root
            project_root = Path(__file__).parent.parent.parent.parent
            profiles_dir = project_root / "config" / "profiles"

        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _get_profile_path(self, profile_id: str) -> Path:
        """Get the file path for a profile."""
        return self.profiles_dir / f"{profile_id}.yaml"

    def save_profile(self, profile: CalibrationProfile) -> None:
        """
        Save a calibration profile to YAML file.

        Args:
            profile: Profile to save
        """
        profile_path = self._get_profile_path(profile.profile_id)

        with open(profile_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(profile.to_dict(), f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)

    def load_profile(self, profile_id: str) -> Optional[CalibrationProfile]:
        """
        Load a calibration profile from YAML file.

        Args:
            profile_id: ID of the profile to load

        Returns:
            CalibrationProfile if found, None otherwise
        """
        profile_path = self._get_profile_path(profile_id)

        if not profile_path.exists():
            return None

        with open(profile_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return CalibrationProfile.from_dict(data)

    def get_point(self, profile_id: str, point_name: str) -> Optional[CalibrationPoint]:
        """
        Get a specific calibration point from a profile.

        Args:
            profile_id: ID of the profile
            point_name: Name of the point to retrieve

        Returns:
            CalibrationPoint if found, None otherwise
        """
        profile = self.load_profile(profile_id)
        if profile is None:
            return None

        return profile.get_point(point_name)

    def list_profiles(self) -> List[str]:
        """
        List all available profile IDs.

        Returns:
            List of profile IDs
        """
        if not self.profiles_dir.exists():
            return []

        return [p.stem for p in self.profiles_dir.glob("*.yaml")]

    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a calibration profile.

        Args:
            profile_id: ID of the profile to delete

        Returns:
            True if deleted, False if not found
        """
        profile_path = self._get_profile_path(profile_id)

        if not profile_path.exists():
            return False

        profile_path.unlink()
        return True
