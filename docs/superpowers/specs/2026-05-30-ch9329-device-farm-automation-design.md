# CH9329 Device Farm Automation Design

**Date:** 2026-05-30

**Goal:** Build a practical CH9329-based phone automation system that is easy to debug on one phone and can later scale to 10+ phones on one Windows control host.

**Core decision:** Use ADB/screenshot as the observation channel during debugging and calibration, while using CH9329 HID input as the primary execution channel for production automation.

---

## 1. Context and Problem

The project currently controls Xiaohongshu publishing through a hardware-oriented path where the phone is driven via CH9329 serial/HID input. This is attractive because CH9329 behaves like real user input and does not depend on Android UI automation internals. However, pure CH9329 control is difficult to debug because it is effectively blind: it can click, swipe, and type, but it cannot see the current UI state.

The target operating model is more ambitious than a single-phone script. The system should eventually control more than 10 phones from one Windows machine, where each phone has its own CH9329 device/COM port. That requires explicit device identity, calibration profiles, execution isolation, status tracking, and failure diagnosis.

The main risk is hard-coding pixel coordinates into publishing scripts. That approach may work for one phone, but it breaks down when phones differ by model, resolution, navigation mode, app version, font scaling, or UI layout.

---

## 2. Design Principle: ADB as Eyes, CH9329 as Hands

The automation system should split phone automation into two channels:

```text
ADB / screenshot / resolution / orientation / health checks = eyes
CH9329 / HID tap / swipe / input / Home / Back             = hands
```

ADB is allowed during debugging and calibration for:

- taking screenshots;
- reading screen size and orientation;
- checking whether the phone is connected;
- collecting failure evidence;
- optionally assisting with text input where CH9329 keyboard input is not practical.

CH9329 remains the core control mechanism for:

- tapping;
- swiping;
- pressing Back/Home if supported;
- interacting with Xiaohongshu like a physical user.

This gives the operator an observable debugging loop without abandoning the CH9329-based production model.

---

## 3. Recommended Architecture: Single-Host Device Farm

The first production target should be a single Windows control host managing multiple phones. Do not start with a distributed multi-host farm; that would add unnecessary complexity around agent heartbeats, remote upgrades, network partitions, and central orchestration.

Recommended architecture:

```text
Pixelle-Video API / Web UI
        │
        ▼
Local Device Farm
        │
        ├── Device Registry
        │   └── stores phone identity and ADB/CH9329 binding
        │
        ├── ADB Observer
        │   └── screenshots, resolution, orientation, health checks
        │
        ├── CH9329 Controller
        │   └── tap, swipe, input, Home/Back via HID
        │
        ├── Calibration Workbench
        │   └── creates per-phone or per-model coordinate profiles
        │
        ├── Action Runtime
        │   └── translates semantic actions into CH9329 operations
        │
        └── Batch Scheduler
            └── runs jobs across phones with locks and failure isolation
```

The design should preserve a future upgrade path to a distributed model:

```text
Central Server
    ├── Windows Agent 1 -> phones 1..N
    ├── Windows Agent 2 -> phones N..M
    └── Windows Agent 3 -> phones M..K
```

For the first implementation phase, `LocalDeviceFarm` is sufficient.

---

## 4. Device Registry

Every phone must be represented by a stable logical identity, not just a COM port.

Example device record:

```yaml
phone_id: phone_001
name: Redmi Note 12 - account A
adb_serial: 8da9xxxx
ch9329_port: COM3
screen:
  width: 1080
  height: 2400
  orientation: portrait
  navigation_mode: gesture
status:
  enabled: true
  state: idle
calibration_profile: xiaomi_redmi_note12_xhs_v1
```

The registry exists to answer:

- which phone this is;
- which ADB serial observes it;
- which CH9329 COM port controls it;
- what screen geometry it uses;
- which calibration profile applies;
- whether it is idle, running, blocked, offline, or disabled.

The first version should use manual binding: the operator chooses an ADB device and a CH9329 COM port and saves them as one `phone_id`.

---

## 5. Phone Debugging and Calibration Workflow

A new phone should follow this onboarding flow:

1. Connect the phone and its CH9329 controller to the Windows host.
2. Scan ADB devices.
3. Scan serial COM ports.
4. Manually bind `adb_serial + ch9329_port` into a `phone_id`.
5. Capture baseline information:
   - screen width and height;
   - orientation;
   - navigation mode;
   - status bar and bottom safe area if available;
   - phone model/name if available.
6. Pull an ADB screenshot.
7. In a calibration workbench, click on the screenshot to select semantic points.
8. Save each semantic point into a calibration profile.
9. Immediately test the point through CH9329.
10. Capture a screenshot after the click.
11. Compare before/after screenshots to confirm that the click reached the expected UI.
12. Repeat until the minimal Xiaohongshu publish path is calibrated.

The important loop is:

```text
screenshot -> mark point -> CH9329 test click -> screenshot -> adjust/save
```

This prevents blind coordinate guessing.

---

## 6. Calibration Profiles and Semantic Points

Publishing flows must not hard-code pixel coordinates. They should refer to semantic points.

Instead of:

```text
tap(531, 2210)
```

Use:

```text
tap("xhs.home.publish_button")
```

Example calibration profile:

```yaml
profile_id: xiaomi_redmi_note12_xhs_v1
screen:
  width: 1080
  height: 2400
  safe_top: 80
  safe_bottom: 120
  navigation_mode: gesture

points:
  xhs.home.publish_button:
    type: absolute
    x: 540
    y: 2240
    description: Xiaohongshu home publish button

  xhs.publish.album_tab:
    type: absolute
    x: 210
    y: 2180
    description: Album tab in publish flow

  xhs.publish.next_button:
    type: absolute
    x: 960
    y: 110
    description: Next button

  xhs.publish.title_input:
    type: absolute
    x: 160
    y: 420
    description: Title input field

  xhs.publish.content_input:
    type: absolute
    x: 140
    y: 620
    description: Content input field

  xhs.publish.submit_button:
    type: absolute
    x: 930
    y: 2220
    description: Submit button
```

The first version may implement absolute points only. The data model should still reserve a `type` field so future profile types can be added without migration pain.

Future coordinate types:

```yaml
# Absolute coordinate
point_a:
  type: absolute
  x: 540
  y: 2240

# Ratio coordinate
point_b:
  type: relative
  x_ratio: 0.5
  y_ratio: 0.933

# Safe-area coordinate
point_c:
  type: safe_area_relative
  anchor: bottom_center
  dx: 0
  dy: -80
```

---

## 7. Action DSL

The publish flow should be described as a device-independent action DSL. The runtime resolves semantic points through the selected phone's calibration profile and executes them through CH9329.

Example flow:

```yaml
flow_id: xhs_publish_note_v1
steps:
  - id: open_xhs
    action: open_app
    package: com.xingin.xhs
    observe:
      screenshot: after

  - id: tap_publish
    action: tap
    point: xhs.home.publish_button
    wait_after: 1.5
    verify:
      type: screenshot_changed

  - id: choose_album
    action: tap
    point: xhs.publish.album_tab
    wait_after: 1.0

  - id: select_first_image
    action: tap
    point: xhs.publish.first_image
    wait_after: 1.0

  - id: tap_next_1
    action: tap
    point: xhs.publish.next_button
    wait_after: 1.5
    verify:
      type: screenshot_changed

  - id: input_title
    action: input_text
    point: xhs.publish.title_input
    value: job.title

  - id: input_content
    action: input_text
    point: xhs.publish.content_input
    value: job.content

  - id: submit
    action: tap
    point: xhs.publish.submit_button
    wait_after: 3.0
    verify:
      type: screenshot_changed
```

First-version action types:

```text
tap(point)
swipe(from_point, to_point)
input_text(point, value)
wait(seconds)
screenshot(label)
open_app(package)
back()
home()
```

First-version verification types:

```text
none
screenshot_changed
manual_confirm
```

First-version failure handling:

```text
retry_step_once
mark_device_blocked
mark_needs_calibration
save_failure_screenshot
```

---

## 8. Text Input Strategy

Chinese text input through CH9329 keyboard emulation is likely to be slow and unstable. The action runtime should support multiple text input strategies:

```yaml
input_methods:
  preferred: adb_clipboard
  fallback:
    - ch9329_keyboard
    - manual_prompt
```

Recommended first-version behavior:

- tap the input field via CH9329;
- use ADB clipboard or another helper method for bulk text insertion when available;
- fall back to CH9329 keyboard only for short/simple input;
- record which method was used in the action log.

This keeps the main UI interaction CH9329-based while avoiding text input as a bottleneck.

---

## 9. Batch Scheduling and Isolation

For 10+ phones, each phone needs its own state and queue. The same phone must execute serially; different phones may execute concurrently.

Example state:

```yaml
phone_001:
  state: idle
  queue:
    - publish_job_001
    - publish_job_008

phone_002:
  state: running
  current_job: publish_job_002

phone_003:
  state: blocked
  current_job: publish_job_003
  reason: waiting for manual captcha handling
```

Device states:

```text
offline            ADB or CH9329 unavailable
idle               ready for work
running            executing a job
needs_calibration  profile no longer matches current UI/device
blocked            needs manual handling, such as login/captcha/popup
cooldown           recently finished; temporarily unavailable
disabled           manually excluded from scheduling
```

Scheduling rules for the first version:

- same phone: one job at a time;
- different phones: jobs can run in parallel;
- failure on one phone does not stop other phones;
- jobs are assigned to explicit `phone_id` first;
- automatic best-device selection is deferred.

---

## 10. Logging, Screenshots, and Failure Diagnosis

Every job should record step-level execution details:

```yaml
job_id: publish_job_001
phone_id: phone_003
status: failed
failed_step: xhs.publish.submit_button
error: no screenshot change within 10 seconds after tapping submit
screenshots:
  - before_open_xhs.png
  - after_tap_publish_button.png
  - failure_submit_timeout.png
action_log:
  - 10:01:02 tap xhs.home.publish_button -> ok
  - 10:01:06 tap xhs.publish.album_tab -> ok
  - 10:01:10 tap xhs.publish.next_button -> ok
  - 10:01:15 tap xhs.publish.submit_button -> no screen change
```

Failure handling policy:

```text
ordinary UI timeout:
  retry 1-2 times

no screenshot change:
  retry current action once

suspected captcha/account risk/login issue:
  mark phone as blocked
  save screenshot
  stop assigning work to this phone

suspected coordinate drift:
  mark phone as needs_calibration

CH9329 or COM port failure:
  mark phone as offline or hardware_error
```

Manual recovery actions:

```text
retry current step
continue current job after manual handling
skip current job
recalibrate phone
disable phone
```

---

## 11. Operator UI

The most useful first interface is a device table.

Example:

```text
Device     ADB      CH9329  State     Current Job   Last Screenshot  Actions
phone_001  online   COM3    running   publish_001   view             pause
phone_002  online   COM4    idle      -             view             assign
phone_003  online   COM5    blocked   publish_003   view             handle
phone_004  offline  COM6    offline   -             -                check
```

Device detail view:

```text
phone_003
  state: blocked
  reason: suspected captcha/popup
  current_job: publish_003
  current_step: xhs.publish.submit_button
  last_screenshot: failure_submit_timeout.png

Actions:
  [refresh screenshot]
  [test click]
  [retry current step]
  [mark handled and continue]
  [recalibrate]
  [disable]
```

This interface is more important than a one-click batch start button. At scale, visibility and manual recovery determine whether the system is operable.

---

## 12. Implementation Priority

### P0: Hardware connectivity tools

- scan COM ports;
- connect to CH9329;
- send a test tap;
- scan ADB devices;
- capture screenshot;
- save device binding.

### P1: Calibration workbench

- display ADB screenshot;
- click screenshot to read coordinates;
- save semantic points;
- test point via CH9329;
- compare before/after screenshots.

### P2: Action runtime

- load device profile;
- load calibration profile;
- execute `tap`, `wait`, `input_text`, `screenshot`;
- record per-step logs;
- save failure screenshots.

### P3: Xiaohongshu publish flow

- migrate the current hard-coded publish path into DSL;
- support only the core happy path first;
- mark popups/captcha/account issues as `blocked`, not auto-solved.

### P4: Multi-device batch control

- device table;
- per-device locks;
- explicit device assignment;
- parallel execution across phones;
- failure isolation.

### P5: Enhanced recognition

Add later:

- OCR;
- template matching;
- popup recognition;
- account-risk detection;
- automatic device selection;
- multi-Windows-host agent mode.

---

## 13. MVP Definition

The minimum viable version is:

- bind one phone's `adb_serial` to one CH9329 `COM` port;
- capture and display screenshots;
- click screenshot coordinates and save semantic points;
- test saved points through CH9329;
- execute a simple DSL flow from saved points;
- record step logs and failure screenshots.

Once this MVP works for one phone, the same model can be expanded to 3, 5, 10, and more phones by adding device profiles, per-device locks, and a batch scheduler.

---

## 14. Non-Goals for the First Version

The first version should not attempt:

- fully automatic UI recognition;
- fully unattended captcha or account-risk handling;
- multi-host distributed control;
- automatic best-device assignment;
- complete replacement of existing publishing code;
- CH9329-only debugging with no screenshot feedback.

These can be added later after the calibration/debugging loop is stable.
