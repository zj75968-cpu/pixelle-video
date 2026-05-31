# Device Farm - CH9329 Hardware Automation System

A production-grade device farm system for automated mobile app testing and content publishing using CH9329 USB HID controllers.

## Overview

The device farm enables precise, hardware-level control of Android devices through:
- **CH9329 USB HID Controllers**: Hardware mouse/touch emulation
- **ADB Integration**: Screen capture and device monitoring
- **Calibration System**: Semantic UI point mapping
- **Action DSL**: High-level automation scripting
- **Job Execution**: Reliable task orchestration with logging

## Architecture

```
device_farm/
├── hardware/           # Hardware abstraction layer
│   ├── ch9329_controller.py   # CH9329 USB HID control
│   └── adb_observer.py         # ADB screen capture & monitoring
├── registry/           # Device configuration management
│   └── device_registry.py      # YAML-based device registry
├── calibration/        # UI calibration system
│   ├── workbench.py           # Interactive calibration tool
│   └── profile_manager.py     # Profile persistence
└── runtime/            # Job execution engine
    ├── action_dsl.py          # Action definition DSL
    ├── action_executor.py     # Action execution engine
    └── job_logger.py          # Structured job logging
```

## Quick Start

### 1. Hardware Setup

**Requirements:**
- Android device with USB debugging enabled
- CH9329 USB HID controller connected to device
- USB cable for ADB connection
- Windows/Linux host machine

**Connections:**
```
[Host PC] --USB--> [CH9329 Controller] --USB--> [Android Device]
    |                                                |
    +----------------ADB USB Cable-----------------+
```

### 2. Device Registration

Create `config/devices.yaml` from the example:

```bash
cp config/devices.example.yaml config/devices.yaml
```

Edit with your device details:

```yaml
devices:
  - phone_id: "my_device_001"
    name: "My Test Device"
    adb_serial: "YOUR_ADB_SERIAL"      # Get from: adb devices
    ch9329_port: "COM3"                # Windows: COMx, Linux: /dev/ttyUSBx
    screen:
      width: 1080
      height: 2400
    status: "idle"
    calibration_profile: null          # Set after calibration
```

**Find ADB Serial:**
```bash
adb devices
# Output: 1A2B3C4D5E6F    device
```

**Find CH9329 Port:**
- Windows: Device Manager → Ports (COM & LPT)
- Linux: `ls /dev/ttyUSB*`

### 3. Device Calibration

Calibration maps semantic UI points (e.g., "xhs.home.publish_button") to physical screen coordinates.

**Start Interactive Calibration:**

```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench

workbench = CalibrationWorkbench()
session = workbench.start_calibration("my_device_001", profile_name="my_profile")

# Capture current screen
workbench.capture_screen(session)

# Save a UI point
workbench.save_point(
    session,
    name="xhs.home.publish_button",
    x=540, y=2200,
    description="Main publish button"
)

# Test the point
workbench.test_point(session, "xhs.home.publish_button")

# Save profile
workbench.save_profile(session)
workbench.end_calibration(session)
```

**Calibration Workflow:**

1. **Capture Screen**: Take screenshot of target UI state
2. **Identify Coordinates**: Use image viewer to find pixel coordinates
3. **Save Point**: Store with semantic name
4. **Test Point**: Verify tap accuracy
5. **Iterate**: Repeat for all UI elements
6. **Save Profile**: Persist calibration data

See [Calibration Guide](#calibration-guide) for detailed workflow.

### 4. Run Automation Job

**Define Actions (YAML DSL):**

```yaml
# jobs/publish_xhs_post.yaml
job_id: "publish_xhs_post"
description: "Publish a post to XiaohongShu"

steps:
  - id: "open_publish"
    action: "tap"
    point: "xhs.home.publish_button"
    wait_after: 1.0

  - id: "select_album"
    action: "tap"
    point: "xhs.publish.album_option"
    wait_after: 0.5

  - id: "select_first_image"
    action: "tap"
    point: "xhs.album.first_image"
    wait_after: 0.3

  - id: "confirm_selection"
    action: "tap"
    point: "xhs.album.confirm_button"
    wait_after: 2.0

  - id: "enter_title"
    action: "input"
    text: "My Amazing Post Title"
    point: "xhs.edit.title_field"
    wait_after: 0.5

  - id: "publish"
    action: "tap"
    point: "xhs.edit.publish_button"
    verify:
      type: "screen_change"
      timeout: 5.0
```

**Execute Job:**

```python
from pixelle_video.device_farm import DeviceRegistry, ProfileManager, ActionExecutor
from pixelle_video.device_farm.runtime import load_action_flow

# Initialize components
registry = DeviceRegistry()
profile_mgr = ProfileManager()
executor = ActionExecutor(registry, profile_mgr)

# Load job definition
flow = load_action_flow("jobs/publish_xhs_post.yaml")

# Execute on device
device = registry.get_device("my_device_001")
result = executor.execute_flow(device, flow)

if result.success:
    print(f"Job completed: {result.steps_completed}/{result.total_steps} steps")
else:
    print(f"Job failed at step {result.failed_step}: {result.error}")
```

## Calibration Guide

### Calibration Workflow

The calibration process maps semantic UI element names to physical screen coordinates.

#### Step 1: Prepare Device

1. Ensure device is connected via ADB and CH9329
2. Navigate to the target app screen (e.g., XHS home)
3. Verify screen is stable (no animations)

#### Step 2: Start Calibration Session

```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench

workbench = CalibrationWorkbench()
session = workbench.start_calibration(
    phone_id="my_device_001",
    profile_name="xhs_main_profile"
)
```

#### Step 3: Capture Reference Screenshot

```python
# Capture current screen state
screenshot_path = workbench.capture_screen(session)
print(f"Screenshot saved: {screenshot_path}")
```

Open the screenshot in an image viewer that shows pixel coordinates (e.g., GIMP, Photoshop, or Windows Paint).

#### Step 4: Identify and Save Points

For each UI element you want to automate:

1. **Hover over the element** in your image viewer to get coordinates
2. **Save the point** with a semantic name:

```python
workbench.save_point(
    session,
    name="xhs.home.publish_button",
    x=540,
    y=2200,
    description="Main publish button at bottom center"
)
```

**Naming Convention:**
- Format: `app.screen.element_name`
- Examples:
  - `xhs.home.publish_button`
  - `xhs.edit.title_field`
  - `common.back_button`

#### Step 5: Test Point Accuracy

```python
# Test the saved point
workbench.test_point(session, "xhs.home.publish_button")
```

This will:
1. Move cursor to the point
2. Perform a tap
3. Capture screenshot after tap
4. Display both before/after screenshots

**Verify:**
- Cursor lands on the correct element
- Tap triggers expected action
- Adjust coordinates if needed

#### Step 6: Calibrate Multiple Screens

For multi-screen workflows:

```python
# Navigate to next screen manually or via test tap
workbench.test_point(session, "xhs.home.publish_button")

# Capture new screen
workbench.capture_screen(session)

# Continue calibrating points on this screen
workbench.save_point(session, "xhs.publish.album_option", x=270, y=1200)
```

#### Step 7: Save and Validate Profile

```python
# Save profile to disk
workbench.save_profile(session)

# End session
workbench.end_calibration(session)

# Validate profile
profile = workbench.load_profile("my_device_001", "xhs_main_profile")
print(f"Profile has {len(profile.points)} calibrated points")
```

### Calibration Best Practices

1. **Stable UI State**: Calibrate when UI is fully loaded and stable
2. **Center of Elements**: Aim for the center of tappable areas
3. **Safe Zones**: Avoid status bar and navigation bar areas
4. **Test Thoroughly**: Test each point after saving
5. **Document Points**: Use descriptive names and descriptions
6. **Version Control**: Commit calibration profiles to git
7. **Device-Specific**: Create separate profiles for different screen sizes

### Calibration Profile Structure

Profiles are stored as YAML in `config/calibration_profiles/`:

```yaml
profile_id: "pixel6_xhs_profile"
screen:
  width: 1080
  height: 2400
  safe_top: 100
  safe_bottom: 120
  navigation_mode: "gesture"
points:
  - name: "xhs.home.publish_button"
    type: "absolute"
    x: 540
    y: 2200
    description: "Main publish button"
```

### Recalibration Triggers

Recalibrate when:
- App UI changes (updates)
- Screen resolution changes
- Device orientation changes
- Tap accuracy degrades
- New features added to automation

## Job Submission Process

### Job Definition Format

Jobs are defined in YAML using the Action DSL:

```yaml
job_id: "unique_job_identifier"
description: "Human-readable job description"
metadata:
  author: "your_name"
  version: "1.0"
  tags: ["xhs", "publish"]

steps:
  - id: "step_1"
    action: "tap"              # Action type
    point: "semantic.point"    # Calibrated point name
    wait_after: 1.0            # Delay after action (seconds)
    
  - id: "step_2"
    action: "input"
    text: "Text to input"
    point: "input.field"
    metadata:
      clear_first: true        # Clear field before input
    
  - id: "step_3"
    action: "swipe"
    metadata:
      from: "swipe.start"
      to: "swipe.end"
      duration: 0.5
    
  - id: "step_4"
    action: "wait"
    duration: 2.0
    
  - id: "step_5"
    action: "screenshot"
    metadata:
      filename: "result.png"
    verify:
      type: "screen_change"    # Verification method
      timeout: 5.0
```

### Action Types

| Action | Description | Required Fields | Optional Fields |
|--------|-------------|-----------------|-----------------|
| `tap` | Single tap at point | `point` | `wait_after`, `verify` |
| `long_press` | Long press at point | `point`, `duration` | `wait_after` |
| `swipe` | Swipe gesture | `metadata.from`, `metadata.to` | `metadata.duration`, `wait_after` |
| `input` | Text input | `text`, `point` | `metadata.clear_first`, `wait_after` |
| `wait` | Delay execution | `duration` | - |
| `screenshot` | Capture screen | - | `metadata.filename` |

### Verification Types

- `screen_change`: Verify screen content changed
- `screen_stable`: Verify screen stopped changing
- `point_visible`: Verify point is visible (future)
- `text_present`: Verify text appears (future)

### Job Execution

**Programmatic Execution:**

```python
from pixelle_video.device_farm import DeviceRegistry, ProfileManager, ActionExecutor
from pixelle_video.device_farm.runtime import load_action_flow, JobLogger

# Setup
registry = DeviceRegistry()
profile_mgr = ProfileManager()
executor = ActionExecutor(registry, profile_mgr)
logger = JobLogger(logs_dir="runtime/job_logs")

# Load job
flow = load_action_flow("jobs/my_job.yaml")
device = registry.get_device("my_device_001")

# Execute with logging
job_id = logger.start_job(flow.job_id, device.phone_id, flow.to_dict())

try:
    result = executor.execute_flow(device, flow, context={})
    
    if result.success:
        logger.complete_job(job_id, result.to_dict())
        print(f"Success: {result.steps_completed} steps completed")
    else:
        logger.fail_job(job_id, result.error, result.to_dict())
        print(f"Failed at step {result.failed_step}: {result.error}")
        
except Exception as e:
    logger.fail_job(job_id, str(e), {"exception": type(e).__name__})
    raise
```

**CLI Execution (Future):**

```bash
# Execute job on specific device
python -m pixelle_video.device_farm.cli run \
    --job jobs/publish_xhs_post.yaml \
    --device my_device_001

# Execute on any available device
python -m pixelle_video.device_farm.cli run \
    --job jobs/publish_xhs_post.yaml \
    --auto-assign
```

### Job Logging

All job executions are logged to `runtime/job_logs/`:

```
runtime/job_logs/
├── job_20260530_210000_abc123.json
└── job_20260530_210500_def456.json
```

**Log Structure:**

```json
{
  "job_id": "publish_xhs_post",
  "execution_id": "abc123",
  "device_id": "my_device_001",
  "status": "completed",
  "started_at": "2026-05-30T21:00:00",
  "completed_at": "2026-05-30T21:02:30",
  "duration_seconds": 150,
  "steps_completed": 8,
  "total_steps": 8,
  "result": {
    "success": true,
    "screenshots": ["runtime/screenshots/step_5.png"]
  }
}
```

## Recovery Procedures

### Device Becomes Unresponsive

**Symptoms:**
- ADB commands timeout
- CH9329 commands don't execute
- Device screen frozen

**Recovery Steps:**

1. **Check ADB Connection:**
```bash
adb devices
# If device missing or "unauthorized":
adb kill-server
adb start-server
adb devices
```

2. **Check CH9329 Connection:**
```python
from pixelle_video.device_farm.hardware import CH9329Controller

controller = CH9329Controller(port="COM3")
if not controller.connect():
    print("CH9329 connection failed - check USB cable and port")
    # Try reconnecting
    controller.disconnect()
    time.sleep(2)
    controller.connect()
```

3. **Restart Device:**
```bash
adb reboot
# Wait 30 seconds for reboot
adb wait-for-device
```

4. **Update Device Status:**
```python
from pixelle_video.device_farm import DeviceRegistry, DeviceStatus

registry = DeviceRegistry()
registry.update_device_status("my_device_001", DeviceStatus.OFFLINE)
# After recovery:
registry.update_device_status("my_device_001", DeviceStatus.IDLE)
```

### Job Execution Fails

**Symptoms:**
- Job stops mid-execution
- Steps fail verification
- Unexpected screen state

**Recovery Steps:**

1. **Check Job Logs:**
```python
from pixelle_video.device_farm.runtime import JobLogger

logger = JobLogger()
job_log = logger.get_job_log("execution_id")
print(f"Failed at step: {job_log['failed_step']}")
print(f"Error: {job_log['error']}")
```

2. **Review Screenshots:**
```bash
# Check screenshots directory
ls runtime/screenshots/
# Open last screenshot before failure
```

3. **Verify Calibration:**
```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench

workbench = CalibrationWorkbench()
session = workbench.start_calibration("my_device_001")
workbench.capture_screen(session)

# Test the failing point
workbench.test_point(session, "xhs.home.publish_button")
```

4. **Manual Recovery:**
```python
# Manually navigate device back to known state
from pixelle_video.device_farm import DeviceRegistry, ProfileManager, ActionExecutor

registry = DeviceRegistry()
profile_mgr = ProfileManager()
executor = ActionExecutor(registry, profile_mgr)
device = registry.get_device("my_device_001")

# Tap back button multiple times
from pixelle_video.device_farm.runtime import ActionStep, ActionType

back_step = ActionStep(
    id="recovery_back",
    action=ActionType.TAP,
    point="common.back_button"
)

for _ in range(3):
    executor._execute_tap(device, back_step, {})
    time.sleep(0.5)
```

### Calibration Drift

**Symptoms:**
- Taps miss target elements
- Actions trigger wrong UI elements
- Previously working jobs now fail

**Recovery Steps:**

1. **Verify Screen Resolution:**
```bash
adb shell wm size
# Should match device.screen in devices.yaml
```

2. **Check for App Updates:**
- UI layouts may change after app updates
- Compare current screen with calibration screenshots

3. **Recalibrate Affected Points:**
```python
from pixelle_video.device_farm.calibration import CalibrationWorkbench

workbench = CalibrationWorkbench()
session = workbench.start_calibration("my_device_001", profile_name="existing_profile")

# Capture current screen
workbench.capture_screen(session)

# Update drifted points
workbench.save_point(session, "xhs.home.publish_button", x=540, y=2210)  # Adjusted Y
workbench.test_point(session, "xhs.home.publish_button")

workbench.save_profile(session)
workbench.end_calibration(session)
```

4. **Bulk Recalibration:**
- If many points drifted, recalibrate entire profile
- Create new profile version: `profile_name_v2`

### CH9329 Hardware Issues

**Symptoms:**
- Mouse movements erratic
- Taps not registering
- USB connection unstable

**Recovery Steps:**

1. **Check USB Cable:**
- Try different USB cable
- Ensure cable supports data transfer (not charge-only)

2. **Check USB Port:**
- Try different USB port on host
- Avoid USB hubs if possible

3. **Reset CH9329:**
```python
from pixelle_video.device_farm.hardware import CH9329Controller

controller = CH9329Controller(port="COM3")
controller.disconnect()
time.sleep(5)  # Wait for hardware reset
controller.connect()
```

4. **Verify Baudrate:**
```python
# Try different baudrates if default fails
for baudrate in [9600, 115200, 57600]:
    controller = CH9329Controller(port="COM3", baudrate=baudrate)
    if controller.connect():
        print(f"Connected at {baudrate} baud")
        break
```

5. **Check Device Manager (Windows):**
- Open Device Manager
- Look for CH9329 under "Ports (COM & LPT)"
- Update driver if needed

### Emergency Stop

**To immediately stop all automation:**

```python
from pixelle_video.device_farm import DeviceRegistry, DeviceStatus

registry = DeviceRegistry()

# Mark all devices as blocked
for device in registry.list_devices():
    registry.update_device_status(device.phone_id, DeviceStatus.BLOCKED)

# Disconnect all CH9329 controllers
from pixelle_video.device_farm.hardware import CH9329Controller

# Controllers will be in executor cache
# Force disconnect by creating new instances
for device in registry.list_devices():
    try:
        controller = CH9329Controller(port=device.ch9329_port)
        controller.disconnect()
    except:
        pass
```

## Configuration Reference

### devices.yaml

```yaml
devices:
  - phone_id: string          # Unique device identifier
    name: string              # Human-readable name
    adb_serial: string        # ADB serial number
    ch9329_port: string       # Serial port (COM3, /dev/ttyUSB0)
    screen:
      width: int              # Screen width in pixels
      height: int             # Screen height in pixels
    status: string            # offline|idle|running|needs_calibration|blocked|cooldown|disabled
    calibration_profile: string|null  # Profile name or null
    last_updated: string      # ISO timestamp
    metadata: object          # Custom metadata
```

### Calibration Profile YAML

```yaml
profile_id: string            # Unique profile identifier
screen:
  width: int                  # Screen width
  height: int                 # Screen height
  safe_top: int               # Status bar height
  safe_bottom: int            # Navigation bar height
  navigation_mode: string     # gesture|buttons
points:
  - name: string              # Semantic point name
    type: string              # absolute|relative
    x: int                    # X coordinate
    y: int                    # Y coordinate
    description: string       # Human-readable description
```

## Troubleshooting

### Common Issues

**Issue: "Device not found in registry"**
- Solution: Register device in `config/devices.yaml`

**Issue: "Calibration profile not found"**
- Solution: Run calibration or check profile name in devices.yaml

**Issue: "Point not found in profile"**
- Solution: Add point to calibration profile or fix point name in job

**Issue: "CH9329 connection failed"**
- Solution: Check COM port, USB cable, and device manager

**Issue: "ADB device unauthorized"**
- Solution: Accept USB debugging prompt on device, or `adb kill-server && adb start-server`

**Issue: "Screen dimensions mismatch"**
- Solution: Update device.screen in devices.yaml to match actual resolution

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now all device farm operations will log detailed info
```

### Health Check

```python
from pixelle_video.device_farm import DeviceRegistry
from pixelle_video.device_farm.hardware import check_device_connectivity, CH9329Controller

registry = DeviceRegistry()

for device in registry.list_devices():
    print(f"\nDevice: {device.name} ({device.phone_id})")
    
    # Check ADB
    adb_ok = check_device_connectivity(device.adb_serial)
    print(f"  ADB: {'OK' if adb_ok else 'FAILED'}")
    
    # Check CH9329
    controller = CH9329Controller(port=device.ch9329_port)
    ch9329_ok = controller.connect()
    print(f"  CH9329: {'OK' if ch9329_ok else 'FAILED'}")
    controller.disconnect()
    
    # Check calibration
    has_profile = device.calibration_profile is not None
    print(f"  Calibration: {'OK' if has_profile else 'MISSING'}")
```

## API Reference

See individual module documentation:
- `hardware/`: Hardware control layer
- `registry/`: Device management
- `calibration/`: Calibration system
- `runtime/`: Job execution engine

## Contributing

When adding new features:
1. Update this README
2. Add example configurations
3. Document recovery procedures
4. Add health check support

## License

Internal use only - Pixelle Video project.
