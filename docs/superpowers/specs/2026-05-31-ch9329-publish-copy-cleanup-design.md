# CH9329 Publish Management Copy Cleanup Design

## Context

The main branch now uses CH9329 serial hardware control as the primary local publish path. The publish management page still contains legacy ADB, USB debugging, WiFi ADB, and wireless pairing copy. This creates a misleading user experience: users see ADB setup instructions even though CH9329 hardware mode does not require ADB.

## Goal

Make the publish management UI describe one clear primary path: CH9329 serial COM control. Keep the client-agent concept as an advanced distribution option, but remove or hide legacy ADB device setup entry points from the main publish management flow.

## Scope

### In scope

- Update `web/views/4_Publish.py` copy for CH9329 serial mode.
- Remove the interactive legacy ADB setup tabs from publish management.
- Replace USB/WiFi/ADB device status text with CH9329 serial text.
- Keep the client-agent tab but make its wording provider-neutral: remote clients control their local publishing devices.
- Add/extend Streamlit UI regression coverage in `tests/test_app_baseline.py`.
- Re-run runtime browser verification for publish management and monitor dashboard.

### Out of scope

- Removing ADB-compatible methods from `DeviceManager`; they remain harmless compatibility shims.
- Reworking the monitor dashboard layout.
- Changing the actual CH9329 automation runtime.
- Adding a full ADB compatibility mode switch.

## Proposed UI behavior

### Device list

The device list caption should say that devices refresh periodically and CH9329 serial devices are registered from the configured COM port. Empty-state text should direct users to configure or register a COM port such as `COM3` or `COM5`.

### Add device

The add-device area should show one primary CH9329 serial form:

- Serial COM field
- Device name field
- Content theme field
- Register CH9329 serial device button

Legacy tabs for HarmonyOS manual WiFi and Android wireless pairing should be removed from the default page. This prevents users from following ADB instructions that are not functional in CH9329 mode.

### Publish settings

The existing ADB Server settings block should remain replaced by CH9329 serial settings:

- Serial COM
- Baudrate
- Unlock PIN
- Save serial button

Saving should persist under `xhs_publish.hardware` and register the COM device locally.

### Client-agent copy

Client-agent setup should remain available but avoid implying that the main web UI needs ADB. Wording should explain that a remote/local client controls its own connected publishing device and polls the control center for jobs.

## Error handling

- If there are no devices, show a CH9329-focused empty state rather than USB/ADB troubleshooting.
- Legacy `connect_wifi`, `pair_wireless`, and `scan_mdns` compatibility methods may still return explicit CH9329-mode messages, but the default UI should not lead users there.
- The publish page must not display `ADB 环境问题` in CH9329 mode.

## Testing

- Extend `test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb` to assert:
  - no `ADB 环境问题`
  - no `ADB Server 设置`
  - no visible `USB 调试`, `adb devices`, `无线配对`, or `ADB 端口`
  - visible `CH9329`, `COM`, `CH9329 串口设置`, and the baudrate input
- Keep lifecycle tests green, including the no-unawaited-coroutine regression.
- Runtime verification:
  - Launch Streamlit on a fresh port.
  - Register/login with a temporary account.
  - Click publish management and confirm CH9329 copy is visible and ADB error copy is absent.
  - Click monitor dashboard and confirm it displays the monitor wall and COM device cards.
  - Reload monitor dashboard and confirm no Traceback/Exception.

## Acceptance criteria

- Publish management presents CH9329 serial COM as the primary local publishing setup.
- No main-flow ADB/USB/WiFi setup instructions are visible on the publish management page.
- Monitor dashboard still opens and shows COM devices.
- Relevant tests pass.
- Runtime browser verification produces screenshots under `runtime/verification/`.
