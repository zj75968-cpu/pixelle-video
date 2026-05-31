# Calibration Workbench

Interactive calibration API/service for defining and testing semantic UI points on physical Android devices via CH9329 hardware control.

## Overview

The Calibration Workbench provides a complete orchestration layer for:

- **Device Management**: Load devices from registry with ADB and CH9329 configuration
- **Screenshot Capture**: Capture current device screen via ADB
- **Point Definition**: Define semantic points with names, coordinates, and descriptions
- **Hardware Testing**: Test points immediately via CH9329 physical mouse control
- **Verification**: Capture before/after screenshots and detect UI changes
- **Profile Persistence**: Save/load calibration profiles as YAML files

## Architecture

```
CalibrationWorkbench
├── DeviceRegistry (device configuration)
├── ADB Observer (screenshot capture)
├── CH9329Controller (hardware control)
└── Profile Manager (persistence)
```

## Quick Start

```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench

# Initialize workbench
workbench = CalibrationWorkbench()

# Start calibration session
session = workbench.start_calibration("phone_001")

# Capture screenshot
img_data, path = workbench.capture_screen("phone_001")

# Save semantic point
point = workbench.save_point(
    phone_id="phone_001",
    name="home_button",
    x=540,
    y=2300,
    description="Main home button"
)

# Test point via CH9329
result = workbench.test_point("phone_001", "home_button")

# Compare before/after screenshots
comparison = workbench.compare_screenshots("phone_001")
print(f"Change: {comparison['change_percentage']:.2f}%")

# Stop session and save profile
workbench.stop_calibration("phone_001", save_profile=True)
```

## API Reference

### CalibrationWorkbench

Main orchestration service for calibration sessions.

#### `__init__(device_registry=None, profiles_dir=None, screenshots_dir=None)`

Initialize the workbench.

**Parameters:**
- `device_registry` (DeviceRegistry, optional): Device registry instance
- `profiles_dir` (str, optional): Directory for calibration profiles (default: `config/calibration_profiles`)
- `screenshots_dir` (str, optional): Directory for screenshots (default: `runtime/calibration_screenshots`)

#### `start_calibration(phone_id, profile_name=None) -> CalibrationSession`

Start a calibration session for a device.

**Parameters:**
- `phone_id` (str): Device identifier from registry
- `profile_name` (str, optional): Profile name (defaults to phone_id)

**Returns:** `CalibrationSession` object

**Raises:** `CalibrationError` if device not found or not ready

#### `stop_calibration(phone_id, save_profile=True)`

Stop a calibration session.

**Parameters:**
- `phone_id` (str): Device identifier
- `save_profile` (bool): Whether to save profile before stopping (default: True)

#### `capture_screen(phone_id) -> Tuple[bytes, str]`

Capture current screenshot from device.

**Parameters:**
- `phone_id` (str): Device identifier

**Returns:** Tuple of `(image_data, screenshot_path)`

**Raises:** `CalibrationError` if capture fails

#### `save_point(phone_id, name, x, y, description="") -> SemanticPoint`

Save a semantic point with name and description.

**Parameters:**
- `phone_id` (str): Device identifier
- `name` (str): Semantic name (e.g., "home_button", "search_icon")
- `x` (int): X coordinate in pixels
- `y` (int): Y coordinate in pixels
- `description` (str, optional): Human-readable description

**Returns:** `SemanticPoint` object

**Raises:** `CalibrationError` if coordinates are invalid

#### `test_point(phone_id, name, capture_after=True) -> Dict`

Test a semantic point by clicking it via CH9329.

**Parameters:**
- `phone_id` (str): Device identifier
- `name` (str): Name of the point to test
- `capture_after` (bool): Whether to capture screenshot after clicking (default: True)

**Returns:** Dict with test results:
```python
{
    'success': bool,
    'point': dict,  # Point data
    'before_screenshot': str,  # Path to before screenshot
    'after_screenshot': str,  # Path to after screenshot
    'timestamp': str
}
```

**Raises:** `CalibrationError` if point not found or test fails

#### `compare_screenshots(phone_id, before_path=None, after_path=None) -> Dict`

Compare before/after screenshots for basic change detection.

**Parameters:**
- `phone_id` (str): Device identifier
- `before_path` (str, optional): Path to before screenshot (uses session current if None)
- `after_path` (str, optional): Path to after screenshot (uses session last_action if None)

**Returns:** Dict with comparison results:
```python
{
    'identical': bool,
    'change_percentage': float,  # 0-100
    'before_screenshot': str,
    'after_screenshot': str,
    'before_size': int,
    'after_size': int
}
```

**Raises:** `CalibrationError` if screenshots not available

#### `get_profile(phone_id) -> CalibrationProfile`

Get the calibration profile for an active session.

**Parameters:**
- `phone_id` (str): Device identifier

**Returns:** `CalibrationProfile` object

#### `list_points(phone_id) -> List[Dict]`

List all semantic points in the current profile.

**Parameters:**
- `phone_id` (str): Device identifier

**Returns:** List of point dictionaries

#### `remove_point(phone_id, name) -> bool`

Remove a semantic point from the profile.

**Parameters:**
- `phone_id` (str): Device identifier
- `name` (str): Name of the point to remove

**Returns:** True if removed, False if not found

### Data Models

#### SemanticPoint

Represents a calibrated semantic point on the device screen.

**Attributes:**
- `name` (str): Semantic identifier
- `x` (int): X coordinate in pixels
- `y` (int): Y coordinate in pixels
- `x_ratio` (float): Normalized X ratio (0.0-1.0)
- `y_ratio` (float): Normalized Y ratio (0.0-1.0)
- `description` (str): Human-readable description
- `created_at` (str): ISO timestamp of creation
- `last_tested` (str, optional): ISO timestamp of last test
- `test_success` (bool, optional): Result of last test

#### CalibrationProfile

Calibration profile containing semantic points for a device.

**Attributes:**
- `phone_id` (str): Device identifier
- `profile_name` (str): Profile name
- `screen_width` (int): Screen width in pixels
- `screen_height` (int): Screen height in pixels
- `points` (Dict[str, SemanticPoint]): Dictionary of semantic points
- `created_at` (str): ISO timestamp of creation
- `last_modified` (str): ISO timestamp of last modification

**Methods:**
- `add_point(point: SemanticPoint)`: Add or update a point
- `get_point(name: str) -> Optional[SemanticPoint]`: Get point by name
- `remove_point(name: str) -> bool`: Remove point by name

#### CalibrationSession

Active calibration session state.

**Attributes:**
- `phone_id` (str): Device identifier
- `device` (Device): Device configuration
- `profile` (CalibrationProfile): Current calibration profile
- `ch9329` (CH9329Controller): Hardware controller instance
- `screenshots_dir` (Path): Session screenshots directory
- `current_screenshot` (bytes, optional): Latest screenshot data
- `current_screenshot_path` (str, optional): Latest screenshot path
- `last_action_screenshot` (bytes, optional): Last action screenshot data
- `last_action_screenshot_path` (str, optional): Last action screenshot path
- `session_start` (str): ISO timestamp of session start

## Workflow Example

### Interactive Calibration Workflow

```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench, CalibrationError

workbench = CalibrationWorkbench()
phone_id = "phone_001"

try:
    # 1. Start session
    session = workbench.start_calibration(phone_id)
    print(f"Calibrating: {session.device.name}")
    print(f"Screen: {session.profile.screen_width}x{session.profile.screen_height}")
    
    # 2. Capture initial state
    img_data, path = workbench.capture_screen(phone_id)
    print(f"Screenshot: {path}")
    
    # 3. Define semantic points (coordinates from user interaction)
    points = [
        ("home_button", 540, 2300, "Main home button"),
        ("back_button", 50, 100, "Back navigation"),
        ("search_icon", 900, 100, "Search in top bar"),
        ("publish_button", 540, 2200, "Create/publish button"),
    ]
    
    for name, x, y, desc in points:
        point = workbench.save_point(phone_id, name, x, y, desc)
        print(f"Saved: {name} at ({x}, {y})")
    
    # 4. Test each point
    for name, _, _, _ in points:
        print(f"\nTesting: {name}")
        result = workbench.test_point(phone_id, name, capture_after=True)
        
        if result['success']:
            # Compare screenshots
            comparison = workbench.compare_screenshots(phone_id)
            change = comparison['change_percentage']
            
            if change > 1.0:
                print(f"  ✓ Point working ({change:.1f}% UI change)")
            else:
                print(f"  ⚠ No visible change ({change:.1f}%)")
        else:
            print(f"  ✗ Test failed: {result.get('error')}")
    
    # 5. Review profile
    profile = workbench.get_profile(phone_id)
    print(f"\nProfile complete: {len(profile.points)} points")
    
finally:
    # 6. Save and cleanup
    workbench.stop_calibration(phone_id, save_profile=True)
    print("Calibration saved")
```

## File Structure

```
config/calibration_profiles/
├── phone_001_phone_001.yaml
├── phone_002_phone_002.yaml
└── ...

runtime/calibration_screenshots/
├── phone_001/
│   ├── 20260530_143022/
│   │   ├── screen_20260530_143022_123.png
│   │   ├── screen_20260530_143025_456.png
│   │   └── ...
│   └── ...
└── ...
```

## Profile Format

Calibration profiles are stored as YAML files:

```yaml
phone_id: phone_001
profile_name: phone_001
screen_width: 1080
screen_height: 2400
created_at: '2026-05-30T14:30:22.123456'
last_modified: '2026-05-30T14:35:10.789012'
points:
  home_button:
    name: home_button
    x: 540
    y: 2300
    x_ratio: 0.5
    y_ratio: 0.9583
    description: Main home button
    created_at: '2026-05-30T14:30:25.123456'
    last_tested: '2026-05-30T14:32:10.789012'
    test_success: true
  search_icon:
    name: search_icon
    x: 900
    y: 100
    x_ratio: 0.8333
    y_ratio: 0.0417
    description: Search icon in top navigation bar
    created_at: '2026-05-30T14:30:30.123456'
    last_tested: '2026-05-30T14:33:15.789012'
    test_success: true
```

## Integration

### With Device Registry

The workbench automatically loads device configuration from the device registry:

```python
from pixelle_video.device_farm.registry import DeviceRegistry
from pixelle_video.device_farm.calibration import CalibrationWorkbench

# Use custom registry
registry = DeviceRegistry("path/to/devices.yaml")
workbench = CalibrationWorkbench(device_registry=registry)
```

### With ADB Observer

Screenshot capture uses the ADB observer module:

```python
# ADB observer is used internally
# Requires device.adb_serial to be valid and device connected
```

### With CH9329 Controller

Hardware control uses the CH9329 controller:

```python
# CH9329 controller is initialized automatically
# Requires device.ch9329_port to be valid (e.g., "COM3")
# Screen dimensions are set from device.screen configuration
```

## Error Handling

All operations raise `CalibrationError` on failure:

```python
from pixelle_video.device_farm.calibration import CalibrationError

try:
    workbench.start_calibration("invalid_phone")
except CalibrationError as e:
    print(f"Calibration failed: {e}")
```

Common error scenarios:
- Device not found in registry
- Device not connected via ADB
- CH9329 port not available
- Invalid coordinates (outside screen bounds)
- Point not found in profile
- Screenshot capture failure

## Best Practices

1. **Always use try/finally**: Ensure `stop_calibration()` is called to cleanup resources
2. **Capture before testing**: Call `capture_screen()` before `test_point()` for comparison
3. **Use semantic names**: Name points by function, not location (e.g., "home_button" not "button_540_2300")
4. **Add descriptions**: Document what each point does for future reference
5. **Test incrementally**: Test each point immediately after defining it
6. **Save frequently**: Set `save_profile=True` when stopping sessions

## See Also

- `example_usage.py`: Complete usage examples
- `workbench.py`: Full implementation
- `../registry/device_registry.py`: Device configuration
- `../hardware/adb_observer.py`: ADB integration
- `../../utils/ch9329.py`: CH9329 hardware control
