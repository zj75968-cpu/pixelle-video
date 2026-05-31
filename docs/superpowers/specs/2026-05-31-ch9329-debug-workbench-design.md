# CH9329 Debug Workbench Design

## Context

Physical phone publishing through CH9329 needs reliable coordinate acquisition and repeatable hardware debugging. The existing project already has CH9329 low-level control, calibration profile concepts, action DSL, config flows, and a basic calibration page. The missing piece is a focused web workbench that lets the operator observe the phone screen, capture or upload screenshots, mark coordinates, test CH9329 actions, and save per-device calibration profiles.

## Goal

Add a dedicated `CH9329 调试台` page that makes it easy to debug physical phones connected through CH9329, especially when onboarding multiple phones. ADB is used as the preferred observation channel for screenshots; CH9329 is used as the execution channel for clicks and input. Manual screenshot upload is the fallback when ADB is unavailable.

## Primary user flow

1. Operator opens `CH9329 调试台` from the sidebar.
2. Operator selects a device.
3. The page shows device metadata: display name, COM port, optional ADB serial, and screen size.
4. Operator clicks `获取截图`.
   - If ADB screenshot succeeds, the screenshot is saved under `runtime/debug_screens/` and displayed.
   - If ADB screenshot fails, the page shows a clear warning and an upload control.
5. Operator enters a semantic point name, such as `xhs.publish.submit_button`.
6. Operator reads coordinates from the displayed screenshot and enters pixel `x` / `y`.
7. The page computes `x_ratio` and `y_ratio` from the configured screen width and height.
8. Operator clicks `测试点击` to send a CH9329 tap to the selected COM port.
9. Operator saves the point into the device calibration profile.
10. Operator repeats for additional points and phones.

## Page location and navigation

Create a new Streamlit page:

```text
web/views/12_CH9329_Debug.py
```

Add it to the main sidebar navigation as:

```text
CH9329 调试台
```

This keeps the debugging experience separate from `发布管理` and avoids making the publish page too large.

## Screenshot strategy

### Preferred path: ADB screenshot

If the selected device has an ADB serial, the workbench attempts to capture a screenshot using the existing screenshot utilities where available. ADB is only for observing the current phone screen. It is not the primary execution path.

The page should clearly state:

```text
ADB 用于截图观察；CH9329 用于真实点击/输入。
```

### Fallback path: manual upload

If ADB is not configured, disconnected, unauthorized, or fails, the page offers a manual upload control for PNG/JPG screenshots. Uploaded screenshots are saved under:

```text
runtime/debug_screens/
```

The fallback must not block coordinate calibration.

## Device model

The workbench should support existing project device data as much as possible:

- device id / serial
- display name
- CH9329 COM port
- optional ADB serial
- screen width / height
- existing calibration profile path if configured

If no full device-farm device record is available, the page can still use the existing publish device registry and CH9329 hardware config as a fallback:

- COM port from `xhs_publish.hardware.com_port`
- screen size defaulting to `1080x2400`

## Calibration profile format

Use one canonical profile location for new saves:

```text
config/calibration_profiles/<device_id>.yaml
```

First version profile shape:

```yaml
device_id: vivo_x100_pro
name: Vivo X100 Pro
screen:
  width: 1080
  height: 2400
ch9329_port: COM5
adb_serial: 10ACBE28M70044L
points:
  xhs.publish.submit_button:
    x: 540
    y: 2180
    x_ratio: 0.5
    y_ratio: 0.908333
    description: 发布按钮
    updated_at: "2026-05-31T10:00:00"
```

The profile stores both pixel coordinates and ratios. Pixel coordinates are best for the exact calibrated device. Ratios make it easier to migrate to phones with different resolutions later.

## Coordinate capture UI

The first version does not need true image-click coordinate capture if Streamlit limitations make it expensive. It should still display the screenshot and provide explicit coordinate entry fields:

- point key
- description
- x pixel
- y pixel
- computed x ratio
- computed y ratio

If a lightweight image-click component is already available in the environment, it may be used, but manual coordinate entry is sufficient for the first version.

## CH9329 action debugging

The first version supports these hardware actions:

- test tap at current point
- long press at current point
- input text
- back/home style key actions if already supported by the controller

Each action writes a visible session log entry:

```text
10:32:14 COM5 tap x=540 y=2180 ratio=(0.5000,0.9083) OK
```

Failures should show:

- COM port used
- action attempted
- exception message
- suggested next check, such as checking COM port or reconnecting the controller

## Relationship to ADB and CH9329

The workbench must avoid implying that ADB is required for publishing. The intended mental model is:

```text
ADB = observe / screenshot / convenience
CH9329 = physical control / click / input
manual upload = fallback observation path
```

This is important because some phones may not have stable ADB, while CH9329 can still physically operate them.

## Testing strategy

### Unit / page smoke tests

Add Streamlit page smoke coverage that imports/renders the new page using stubs or `AppTest` where practical. The test should verify the page renders key text:

- `CH9329 调试台`
- `ADB 用于截图观察`
- `CH9329 用于真实点击`
- `手动上传截图`
- `测试点击`

### Profile save tests

Add a focused test for profile serialization if helper functions are extracted. The test should verify:

- point pixel coordinates are stored
- ratios are computed from screen width/height
- existing points are preserved when saving a new point

### Runtime verification

After implementation, run the Streamlit app and open the new page in a browser. Capture screenshots under:

```text
runtime/verification/
```

Verify:

- sidebar contains `CH9329 调试台`
- page opens without errors
- device selector renders
- screenshot controls render
- coordinate form renders
- action buttons render

If physical CH9329 hardware is connected and safe to test, perform a single test tap on a harmless coordinate. If not safe, skip the hardware action and state why.

## Out of scope for first version

- Full action DSL editor.
- Multi-step recording timeline.
- Automatic computer-vision element detection.
- Rewriting existing `ActionExecutor`.
- Resolving all legacy profile format inconsistencies.
- Guaranteed screenshot support without ADB or manual upload.

## Future extensions

After the first version is useful, it can grow into:

- click-on-image coordinate capture
- action sequence recording and replay
- profile import/export between phones
- per-point before/after screenshots
- batch point verification across multiple devices
- integration with `config/flows/xhs_publish_note_v1.yaml`
