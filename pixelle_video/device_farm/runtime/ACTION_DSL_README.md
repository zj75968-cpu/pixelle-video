# Action DSL - Device Farm Automation Flow Definition

## Overview

The Action DSL provides a YAML-based declarative language for defining device automation flows. It enables device-agnostic automation by using semantic point references instead of hardcoded coordinates.

## Module Location

- **Parser Module**: `F:/codex project/小红书/pixelle_video/device_farm/runtime/action_dsl.py`
- **Flow Definitions**: `F:/codex project/小红书/config/flows/`
- **Tests**: `F:/codex project/小红书/tests/test_action_dsl.py`

## Core Components

### ActionType Enum

Supported action types:
- `tap` - Tap on a point
- `swipe` - Swipe gesture
- `input_text` - Enter text input
- `wait` - Wait for duration
- `screenshot` - Capture screenshot
- `open_app` - Launch application
- `back` - Press back button
- `home` - Press home button

### VerifyType Enum

Verification strategies:
- `none` - No verification
- `screenshot_changed` - Verify screen changed after action
- `manual_confirm` - Require manual confirmation

### ActionStep

Represents a single automation step.

**Fields:**
- `id` (str, required) - Unique step identifier
- `action` (ActionType, required) - Action to perform
- `point` (str, optional) - Semantic point name (e.g., "login_button")
- `wait_after` (float, default=0.0) - Seconds to wait after execution
- `verify` (VerifyType, default=none) - Verification strategy
- `value` (str, optional) - Input value for `input_text` actions
- `metadata` (dict, optional) - Additional action-specific parameters

### Flow

Represents a complete automation flow.

**Fields:**
- `flow_id` (str, required) - Unique flow identifier
- `steps` (List[ActionStep], required) - Ordered list of steps
- `metadata` (dict, optional) - Flow-level metadata (description, version, etc.)

## API Usage

### Loading Flows

```python
from pixelle_video.device_farm.runtime import load_flow, get_step

# Load a flow from YAML
flow = load_flow("xiaohongshu_publish")

# Access flow properties
print(flow.flow_id)
print(f"Flow has {len(flow.steps)} steps")

# Iterate through steps
for step in flow.steps:
    print(f"Step {step.id}: {step.action.value}")
```

### Retrieving Specific Steps

```python
# Get a specific step from a flow
step = flow.get_step("tap_publish_button")
if step:
    print(f"Action: {step.action}")
    print(f"Point: {step.point}")
    print(f"Wait after: {step.wait_after}s")

# Or use the convenience function
step = get_step("xiaohongshu_publish", "tap_publish_button")
```

### Custom Flow Directory

```python
# Load from custom directory
flow = load_flow("my_flow", flows_dir="/path/to/flows")
```

## YAML Flow Definition Format

### Basic Structure

```yaml
flow_id: example_flow
description: Optional flow description
version: "1.0"

steps:
  - id: step1
    action: tap
    point: button_name
    wait_after: 1.0
    verify: screenshot_changed

  - id: step2
    action: input_text
    point: text_field
    value: "Hello World"
    wait_after: 0.5
    verify: none
```

### Complete Example

```yaml
flow_id: xiaohongshu_publish
description: Xiaohongshu video publishing flow
version: "1.0"
app_package: com.xingin.xhs

steps:
  - id: open_xhs
    action: open_app
    point: xhs_launcher
    wait_after: 3.0
    verify: screenshot_changed

  - id: tap_publish_button
    action: tap
    point: publish_button
    wait_after: 2.0
    verify: screenshot_changed

  - id: select_video
    action: tap
    point: video_thumbnail
    wait_after: 1.5
    verify: screenshot_changed

  - id: input_title
    action: input_text
    point: title_field
    value: "Amazing content!"
    wait_after: 0.5
    verify: none

  - id: tap_publish
    action: tap
    point: publish_confirm_button
    wait_after: 5.0
    verify: screenshot_changed

  - id: verify_published
    action: screenshot
    wait_after: 2.0
    verify: manual_confirm
```

### Extended Metadata

Steps can include additional metadata fields for action-specific parameters:

```yaml
steps:
  - id: swipe_up
    action: swipe
    point: screen_center
    direction: up
    distance: 500
    duration: 0.3
    wait_after: 1.0
```

These extra fields are stored in `step.metadata` and can be accessed by the executor.

## Design Principles

### Device-Agnostic Automation

The DSL uses **semantic point names** instead of hardcoded coordinates:

```yaml
# Good - device-agnostic
point: login_button

# Bad - device-specific (don't do this in DSL)
x: 540
y: 960
```

Point names are resolved to actual coordinates by the calibration system based on the target device profile.

### Declarative Flow Definition

Flows describe **what** to do, not **how** to do it:

```yaml
- id: login
  action: tap
  point: login_button
  verify: screenshot_changed
```

The executor handles the implementation details (coordinate lookup, touch simulation, verification).

### Composable and Reusable

Flows are self-contained YAML files that can be:
- Version controlled
- Shared across devices
- Composed into larger workflows
- Modified without code changes

## Error Handling

The parser provides clear error messages:

```python
# Missing required field
ValueError: Step must have an 'id' field

# Invalid action type
ValueError: Invalid action 'invalid_action' in step 'step1'. 
Valid actions: ['tap', 'swipe', 'input_text', ...]

# Flow file not found
FileNotFoundError: Flow file not found: my_flow.yaml or my_flow.yml in /path/to/flows

# Flow ID mismatch
ValueError: Flow ID mismatch: file is 'test_flow' but flow_id is 'different_id'
```

## Flow Registry and Caching

Loaded flows are cached in memory for performance:

```python
# First load - reads from disk
flow1 = load_flow("my_flow")

# Second load - returns cached instance
flow2 = load_flow("my_flow")

assert flow1 is flow2  # Same object

# Clear cache if needed (e.g., for testing)
from pixelle_video.device_farm.runtime.action_dsl import clear_registry
clear_registry()
```

## Integration with Device Farm

The Action DSL integrates with other device farm components:

1. **Calibration System** - Resolves semantic point names to device-specific coordinates
2. **CH9329 Controller** - Executes physical touch actions
3. **ADB Observer** - Captures screenshots for verification
4. **Job Logger** - Records execution results

## Testing

Run the test suite:

```bash
cd "F:/codex project/小红书"
python -m pytest tests/test_action_dsl.py -v
```

All 30 tests pass, covering:
- ActionStep parsing and serialization
- Flow parsing and validation
- File loading with .yaml and .yml extensions
- Error handling for invalid inputs
- Flow registry caching
- Step retrieval by ID

## Example Flows

Two example flows are provided:

1. **example_login.yaml** - Generic login flow demonstrating all features
2. **xiaohongshu_publish.yaml** - Real-world Xiaohongshu video publishing flow

## Next Steps

To use the Action DSL in automation:

1. Define flows in `config/flows/*.yaml`
2. Calibrate semantic points for target devices
3. Implement flow executor that:
   - Loads flow using `load_flow()`
   - Iterates through steps
   - Resolves points via calibration system
   - Executes actions via CH9329 controller
   - Performs verification checks
   - Logs results via JobLogger
