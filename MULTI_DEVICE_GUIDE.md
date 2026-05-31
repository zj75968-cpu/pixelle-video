# Multi-Device Management Guide

## 🎯 Overview

This guide helps you quickly add and calibrate multiple devices for your device farm.

---

## 🚀 Quick Start: Adding New Devices

### **Step 1: Add New Device (2 minutes)**

```bash
python scripts/00_add_new_device.py
```

**What it does:**
- 🔍 Auto-detects all connected ADB devices
- 🔍 Auto-detects all CH9329 controllers (COM ports)
- 📝 Interactive wizard to configure the device
- 💾 Saves configuration to `config/devices.yaml`
- 📄 Creates calibration template

**Example workflow:**
```
[ADB Devices]
  [1] Serial: 10ACBE28M70044L
      Model: V2199A
      Resolution: 1080x2400
  [2] Serial: ABC123DEF456
      Model: Pixel 6
      Resolution: 1080x2400

Select device [1-2]: 2

[CH9329 Controllers]
  [1] COM5 - USB-SERIAL CH340 ← CH9329
  [2] COM3 - Bluetooth Serial

Select port [1-2]: 1

Device ID: pixel_6_001
Device name [Pixel 6]: My Pixel 6

✓ Device added successfully!
```

---

### **Step 2: Quick Calibration (5 minutes)**

#### **Option A: Copy from Reference Device (Recommended)**

If you already have one calibrated device, copy its calibration:

```bash
# Copy calibration from vivo_v2199a_001 to new device
python scripts/03_quick_calibrate.py \
    --device pixel_6_002 \
    --reference vivo_v2199a_001
```

**What it does:**
- ✓ Copies all calibration points from reference device
- ✓ Auto-scales points if screen resolutions differ
- ✓ Batch tests all points (visual mode - just moves cursor)
- ✓ Saves calibration profile

**Testing modes:**
- `--test-mode visual` - Moves cursor to each point (default, safe)
- `--test-mode tap` - Actually taps each point (verify positions)
- `--test-mode skip` - Skip testing, just save

#### **Option B: Manual Calibration**

For the first device or if you need custom points:

```bash
python scripts/01_calibrate_device.py --device pixel_6_002
```

---

### **Step 3: Test Automation (2 minutes)**

```bash
python scripts/02_test_automation.py --device pixel_6_002
```

Verifies the device is ready for automation.

---

## 📋 Multi-Device Workflow

### **Scenario: Adding 5 New Devices**

```bash
# 1. Connect all devices via USB and CH9329
# 2. Add first device and calibrate manually
python scripts/00_add_new_device.py
python scripts/01_calibrate_device.py --device device_001

# 3. Add remaining devices
python scripts/00_add_new_device.py  # device_002
python scripts/00_add_new_device.py  # device_003
python scripts/00_add_new_device.py  # device_004
python scripts/00_add_new_device.py  # device_005

# 4. Quick calibrate all from reference
python scripts/03_quick_calibrate.py --device device_002 --reference device_001
python scripts/03_quick_calibrate.py --device device_003 --reference device_001
python scripts/03_quick_calibrate.py --device device_004 --reference device_001
python scripts/03_quick_calibrate.py --device device_005 --reference device_001

# 5. Test all devices
python scripts/02_test_automation.py --device device_002
python scripts/02_test_automation.py --device device_003
python scripts/02_test_automation.py --device device_004
python scripts/02_test_automation.py --device device_005
```

**Time estimate:**
- First device: ~10 minutes (manual calibration)
- Each additional device: ~3 minutes (quick calibration)
- **Total for 5 devices: ~22 minutes**

---

## 🔧 Device Configuration

### **config/devices.yaml Structure**

```yaml
devices:
  - phone_id: "vivo_v2199a_001"
    name: "Vivo V2199A #1"
    adb_serial: "10ACBE28M70044L"
    ch9329_port: "COM5"
    screen:
      width: 1080
      height: 2400
    status: "idle"
    calibration_profile: "vivo_v2199a_001_default"
    
  - phone_id: "pixel_6_001"
    name: "Pixel 6 #1"
    adb_serial: "ABC123DEF456"
    ch9329_port: "COM6"
    screen:
      width: 1080
      height: 2400
    status: "idle"
    calibration_profile: "pixel_6_001_default"
```

### **Calibration Profile Structure**

```yaml
# config/calibration_profiles/vivo_v2199a_001_default.yaml
profile_id: "vivo_v2199a_001_default"
phone_id: "vivo_v2199a_001"
screen:
  width: 1080
  height: 2400

points:
  - name: "xhs.home.publish_button"
    x: 540
    y: 2100
    x_ratio: 0.5000
    y_ratio: 0.8750
    description: "Publish button"
```

---

## 🎯 Calibration Point Naming Convention

Use consistent naming across all devices:

```
app.screen.element_name

Examples:
  xhs.home.publish_button       - 小红书主页发布按钮
  xhs.home.search_bar           - 搜索栏
  xhs.publish.album_option      - 发布页面相册选项
  xhs.publish.camera_option     - 发布页面拍摄选项
  xhs.album.first_image         - 相册第一张图片
  xhs.album.confirm_button      - 相册确认按钮
  xhs.edit.title_field          - 编辑页标题输入框
  xhs.edit.content_field        - 编辑页内容输入框
  xhs.edit.publish_button       - 编辑页发布按钮
  
  common.back_button            - 通用返回按钮
  common.home_button            - 通用主页按钮
  screen.center                 - 屏幕中心
  screen.top_left               - 屏幕左上角
```

**Benefits:**
- ✓ Easy to understand across devices
- ✓ Reusable in automation flows
- ✓ Quick calibration copying works better

---

## 🛠️ Advanced Features

### **Resolution Scaling**

When copying calibration between different resolutions:

```python
# Automatic scaling example:
# Source: 1080x2400, Point at (540, 2100)
# Target: 1440x3200
# Scaled: (720, 2800)

# Ratio preserved: (0.5, 0.875) → (0.5, 0.875)
```

### **Batch Operations**

List all devices:
```bash
python -c "
import yaml
with open('config/devices.yaml') as f:
    config = yaml.safe_load(f)
    for d in config['devices']:
        print(f\"{d['phone_id']}: {d['name']} - {d['status']}\")
"
```

Test all devices:
```bash
for device in vivo_v2199a_001 pixel_6_001 pixel_6_002; do
    echo "Testing $device..."
    python scripts/02_test_automation.py --device $device
done
```

### **Profile Management**

Copy profile manually:
```bash
cp config/calibration_profiles/device_001_default.yaml \
   config/calibration_profiles/device_002_default.yaml

# Edit device_002_default.yaml to update phone_id
```

---

## 📊 Device Status Management

### **Status Values**

- `idle` - Ready for tasks
- `running` - Currently executing a task
- `disabled` - Temporarily disabled
- `offline` - Not connected
- `needs_calibration` - Calibration required

### **Update Status**

```python
from pixelle_video.device_farm.registry.device_registry import DeviceRegistry

registry = DeviceRegistry("config/devices.yaml")
registry.update_device_status("pixel_6_001", "disabled")
```

---

## 🔍 Troubleshooting

### **Device Not Detected**

```bash
# Check ADB
adb devices

# Check COM ports
python test_ch9329_debug.py
```

### **Calibration Points Off**

```bash
# Test individual point
python test_ch9329_debug.py -i COM5
> test 540 2100

# Recalibrate specific points
python scripts/01_calibrate_device.py --device device_001
```

### **Different Screen Sizes**

For devices with different aspect ratios, manual calibration may be better than copying:

```bash
# 16:9 device (1080x1920)
python scripts/01_calibrate_device.py --device device_16_9

# 20:9 device (1080x2400)  
python scripts/01_calibrate_device.py --device device_20_9
```

---

## 📈 Scaling to Many Devices

### **10+ Devices Strategy**

1. **Group by model** - Same model = same calibration
2. **Master calibration** - One perfect calibration per model
3. **Quick clone** - Copy to all devices of same model
4. **Spot check** - Test 20% of devices thoroughly
5. **Monitor** - Track success rates, recalibrate if needed

### **Example: 20 Devices, 4 Models**

```bash
# Master calibrations (4 devices × 10 min = 40 min)
python scripts/01_calibrate_device.py --device vivo_v2199a_001
python scripts/01_calibrate_device.py --device pixel_6_001
python scripts/01_calibrate_device.py --device xiaomi_13_001
python scripts/01_calibrate_device.py --device samsung_s23_001

# Quick clone (16 devices × 3 min = 48 min)
for i in {002..005}; do
    python scripts/03_quick_calibrate.py \
        --device vivo_v2199a_$i \
        --reference vivo_v2199a_001
done

# ... repeat for other models

# Total time: ~90 minutes for 20 devices
```

---

## 🎉 Summary

**Tools:**
- `00_add_new_device.py` - Add devices quickly
- `03_quick_calibrate.py` - Copy calibration from reference
- `01_calibrate_device.py` - Manual calibration
- `02_test_automation.py` - Test device automation

**Workflow:**
1. Add device (2 min)
2. Quick calibrate from reference (3 min)
3. Test automation (2 min)
4. **Total: ~7 minutes per device**

**Best Practices:**
- ✓ Calibrate one device perfectly first
- ✓ Use consistent point naming
- ✓ Group devices by model
- ✓ Test in visual mode first
- ✓ Keep calibration profiles in version control

---

Ready to add your next device? Start with:

```bash
python scripts/00_add_new_device.py
```
