# Device Farm Quick Start Guide

## 🎯 Your Setup Status

✅ **Hardware Verified**
- ADB: Connected (Vivo V2199A - 10ACBE28M70044L)
- CH9329: Connected (COM5)
- All tests passed

✅ **Configuration Files Created**
- `config/devices.yaml` - Device registry
- `config/flows/test_basic_navigation.yaml` - Test flow
- `scripts/01_calibrate_device.py` - Calibration wizard
- `scripts/02_test_automation.py` - Automation test suite

---

## 📋 Quick Start Steps

### Step 1: Calibrate Your Device (5-10 minutes)

Run the calibration wizard:

```bash
cd "F:/codex project/小红书"
python scripts/01_calibrate_device.py
```

**What it does:**
1. ✓ Checks hardware connectivity
2. 📸 Captures reference screenshots of your app screens
3. 🎯 Lets you save UI point coordinates interactively
4. 💾 Generates calibration profile YAML

**Interactive commands:**
- `save home.publish_button 540 2100` - Save a point
- `test 540 2100` - Test tap at coordinates
- `list` - Show saved points
- `done` - Finish and save profile

**Tips:**
- Open screenshots in Paint/GIMP to find coordinates
- Hover over UI elements to see pixel positions
- Save at least 3-5 key points for your workflow

---

### Step 2: Test Automation (2-3 minutes)

Run the automation test suite:

```bash
python scripts/02_test_automation.py
```

**What it tests:**
1. ✓ Basic tap actions
2. ✓ Swipe gestures (home navigation)
3. ✓ Long press
4. ✓ Screenshot capture
5. ✓ Combined ADB + CH9329 workflow

**Watch your device screen** - you'll see the automation in action!

---

### Step 3: Create Your First Flow

Edit `config/flows/my_first_flow.yaml`:

```yaml
flow_id: "my_first_flow"
name: "My First Automation"
description: "Open app and navigate"

steps:
  - id: "step_1"
    action: "swipe_up_home"
    wait_after: 2.0

  - id: "step_2"
    action: "tap"
    point: "home.app_icon"  # Use your calibrated point
    wait_after: 1.0

  - id: "step_3"
    action: "screenshot"
    metadata:
      filename: "result.png"
```

---

## 🛠️ Available Tools

### Interactive CH9329 Control
```bash
python test_ch9329_debug.py -i COM5
```
Commands: `tap 0.5 0.5`, `move 0.2 0.8`, `cal`, `home`, `quit`

### ADB Screenshot Test
```bash
python test_adb_integration.py 10ACBE28M70044L
```

### Hardware Status Check
```bash
python test_ch9329_debug.py COM5
python test_adb_integration.py
```

---

## 📁 Project Structure

```
F:/codex project/小红书/
├── config/
│   ├── devices.yaml                    # Your device configuration
│   ├── flows/                          # Automation flow definitions
│   │   └── test_basic_navigation.yaml
│   └── calibration_profiles/           # Calibration data (generated)
│
├── scripts/
│   ├── 01_calibrate_device.py         # Calibration wizard
│   └── 02_test_automation.py          # Test suite
│
├── runtime/
│   ├── calibration_screenshots/        # Reference screenshots
│   └── test_results/                   # Test output
│
├── test_ch9329_debug.py               # CH9329 debugging tool
├── test_adb_integration.py            # ADB testing tool
└── README_QUICKSTART.md               # This file
```

---

## 🎮 Common Workflows

### Calibrate a New Screen
```bash
# 1. Navigate to the screen on your device
# 2. Run calibration wizard
python scripts/01_calibrate_device.py

# 3. In the wizard:
calibrate> save xhs.home.publish_button 540 2100
calibrate> test 540 2100  # Verify it works
calibrate> list
calibrate> done
```

### Test a Specific Point
```bash
python test_ch9329_debug.py -i COM5

> tap 0.5 0.5      # Center
> tap 0.5 0.875    # Bottom (2100/2400)
> move 0.25 0.25   # Top-left
> home             # Return to home
> quit
```

### Capture Screenshots
```python
from pixelle_video.device_farm.hardware.adb_observer import capture_screenshot

capture_screenshot("10ACBE28M70044L", "my_screenshot.png")
```

### Execute Automation
```python
from pixelle_video.utils.ch9329 import CH9329Controller

controller = CH9329Controller(port="COM5")
controller.connect()

# Your automation
controller.swipe_up_to_home()
controller.click(0.5, 0.875)  # Tap publish button
controller.long_press(0.5, 0.5, duration=2.0)

controller.disconnect()
```

---

## 🔧 Configuration Reference

### Device Configuration (`config/devices.yaml`)

```yaml
devices:
  - phone_id: "vivo_v2199a_001"      # Unique ID
    name: "Vivo V2199A"               # Display name
    adb_serial: "10ACBE28M70044L"    # From: adb devices
    ch9329_port: "COM5"               # From: test_ch9329_debug.py
    screen:
      width: 1080                     # Screen resolution
      height: 2400
    status: "idle"                    # idle|running|disabled
    calibration_profile: null         # Profile name after calibration
```

### Calibration Profile (`config/calibration_profiles/*.yaml`)

```yaml
profile_id: "vivo_v2199a_001_default"
phone_id: "vivo_v2199a_001"
screen:
  width: 1080
  height: 2400

points:
  - name: "xhs.home.publish_button"
    type: "absolute"
    x: 540
    y: 2100
    x_ratio: 0.5000
    y_ratio: 0.8750
    description: "Publish button at bottom center"
```

### Flow Definition (`config/flows/*.yaml`)

```yaml
flow_id: "example_flow"
name: "Example Automation Flow"
description: "Description of what this flow does"

steps:
  - id: "step_1"
    action: "tap"                    # tap|long_press|swipe|input|wait|screenshot
    point: "xhs.home.publish_button" # Calibrated point name
    wait_after: 1.0                  # Seconds to wait after action

  - id: "step_2"
    action: "input"
    text: "Hello World"
    point: "xhs.edit.title_field"

  - id: "step_3"
    action: "screenshot"
    metadata:
      filename: "result.png"
```

---

## 🐛 Troubleshooting

### CH9329 Not Responding
```bash
# 1. Check connection
python test_ch9329_debug.py COM5

# 2. Try different port
python test_ch9329_debug.py COM3

# 3. Reconnect USB cable
```

### ADB Device Not Found
```bash
# 1. Check connection
adb devices

# 2. Restart ADB server
adb kill-server
adb start-server
adb devices

# 3. Accept USB debugging on device
```

### Tap Missing Target
```bash
# 1. Recalibrate the point
python scripts/01_calibrate_device.py

# 2. Test in interactive mode
python test_ch9329_debug.py -i COM5
> test 540 2100

# 3. Adjust coordinates
calibrate> save point_name 540 2110  # Try +/- 10 pixels
```

### Screen Resolution Mismatch
```bash
# Check actual resolution
adb shell wm size

# Update config/devices.yaml with correct values
```

---

## 📚 Next Steps

1. ✅ **Complete calibration** - Run `scripts/01_calibrate_device.py`
2. ✅ **Test automation** - Run `scripts/02_test_automation.py`
3. 📝 **Create your flows** - Define automation in `config/flows/`
4. 🚀 **Start automating** - Execute your flows programmatically
5. 🌐 **Optional: REST API** - Run `python -m pixelle_video.device_farm.api.rest_api`

---

## 💡 Pro Tips

- **Calibrate in good lighting** - Consistent screen brightness helps
- **Use descriptive point names** - `xhs.home.publish_button` not `button1`
- **Test points immediately** - Use `test` command after `save`
- **Save multiple profiles** - Different profiles for different app versions
- **Version control** - Commit calibration profiles to git
- **Screenshot everything** - Helps debug when automation fails
- **Start simple** - Test basic taps before complex workflows

---

## 🎉 You're Ready!

Your device farm is fully configured and tested. Start with:

```bash
python scripts/01_calibrate_device.py
```

Happy automating! 🚀
