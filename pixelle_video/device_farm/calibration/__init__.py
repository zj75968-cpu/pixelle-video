"""Calibration module for device farm."""

from .profile_manager import (
    CalibrationPoint,
    CalibrationProfile as LegacyCalibrationProfile,
    ProfileManager as LegacyProfileManager,
    ScreenConfig,
)

from .workbench import (
    CalibrationWorkbench,
    CalibrationSession,
    CalibrationProfile,
    SemanticPoint,
    CalibrationError
)

__all__ = [
    # Legacy profile manager (existing)
    'CalibrationPoint',
    'LegacyCalibrationProfile',
    'LegacyProfileManager',
    'ScreenConfig',
    # New workbench API
    'CalibrationWorkbench',
    'CalibrationSession',
    'CalibrationProfile',
    'SemanticPoint',
    'CalibrationError'
]
