# CH9329 + MS2130 Verification Design

## Context

The current CH9329 debugging flow treats ADB as the observation path: ADB is used to capture or refresh the phone screen, while CH9329 performs physical input. The new target architecture abandons ADB as the main projection/observation channel. MS2130 HDMI capture becomes the "eye" of the system, and CH9329 remains the physical "hand" that clicks, swipes, and types.

The goal is not only to display a live phone image. The system must verify that CH9329 actions actually work by observing MS2130 frames before and after each action, applying rule-based checks, and returning structured evidence for the visual workbench and the automated publish pipeline.

## Goals

1. Replace the ADB-centered observation model with MS2130 HDMI capture through OpenCV DirectShow/UVC.
2. Keep CH9329 as the physical control path for tap, swipe, key, and text input.
3. Build a reusable verification foundation shared by the MS2130 workbench and the automated publish pipeline.
4. Implement three-layer verification:
   - coordinate closed-loop verification,
   - screen-change verification,
   - business semantic verification.
5. Use YAML as the source of truth for capture profiles, projection calibration, semantic points, verification rules, and failure policies.
6. Save evidence artifacts for debugging and audit.
7. Treat ADB as optional legacy/debug tooling only, not as a required runtime dependency.

## Non-goals for the first version

- Full OCR or vision-model semantic recognition.
- A complete GUI rule editor.
- Guaranteed support for every HDMI scaling/cropping/rotation case on day one.
- Immediate fully unattended publishing for destructive/final publish actions.
- Removing every legacy ADB utility from the repository in the first change.

## Recommended rollout

Use a phased approach:

```text
Phase 1: Minimal shared verification foundation
Phase 2: MS2130 visual verification workbench
Phase 3: Automated publish pipeline integration
```

This avoids two failure modes:

- directly patching the existing workbench into another one-off UI script;
- pushing unproven MS2130 capture and calibration assumptions into the unattended publish pipeline.

## Mental model

```text
MS2130 = eye / observation / projection / screenshot source
CH9329 = hand / physical click / physical swipe / keyboard input
YAML = calibration and verification truth
VerificationEngine = rule evaluator
ActionVerifier = action + observation + verification orchestrator
ADB = optional legacy/debug adapter, not the main path
```

## High-level architecture

```text
                ┌──────────────────────────────┐
                │ YAML Device / Verification    │
                │ Profiles                      │
                │ - capture hints               │
                │ - projection transform         │
                │ - semantic points / ROIs       │
                │ - rules / thresholds           │
                │ - failure policy               │
                └──────────────┬───────────────┘
                               │
                               ▼
┌──────────────┐       ┌────────────────┐       ┌──────────────────┐
│ MS2130 HDMI  │──────▶│ FrameProvider  │──────▶│ NormalizedFrame   │
│ UVC Capture  │       │ OpenCV/DSHOW   │       │ + Projection Map  │
└──────────────┘       └────────────────┘       └─────────┬────────┘
                                                            │
                                                            ▼
┌──────────────┐       ┌────────────────┐       ┌──────────────────┐
│ CH9329       │◀──────│ ActionVerifier │──────▶│ VerificationEngine│
│ Physical I/O │       │ before/action/ │       │ 3-layer rules     │
└──────────────┘       │ after/verify   │       └─────────┬────────┘
                       └────────────────┘                 │
                                                            ▼
                                  ┌────────────────────────────────┐
                                  │ VerificationResult             │
                                  │ PASS / RETRYABLE / MANUAL /    │
                                  │ HARD_FAIL + evidence artifacts │
                                  └────────────────────────────────┘
```

## Core package

Create a shared verification package:

```text
pixelle_video/device_farm/verification/
```

The package should hold reusable logic only. UI code and publish-flow code should call into it instead of duplicating capture, rule, or evidence logic.

## Core components

### `FrameProvider`

`FrameProvider` abstracts where frames come from.

Primary implementation:

```text
MS2130FrameProvider
```

It opens the MS2130 capture device as a Windows UVC camera:

```python
cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
```

Conceptual interface:

```python
class FrameProvider:
    def open(self) -> None: ...
    def close(self) -> None: ...
    def get_frame(self) -> NormalizedFrame: ...
    def get_metadata(self) -> CaptureMetadata: ...
    def health_check(self) -> CaptureHealth: ...
```

First-version responsibilities:

- open and close the MS2130 capture device;
- read frames;
- expose camera index, name hint, raw resolution, FPS, timestamp, and freshness;
- detect empty frames, black frames, stale frames, and unexpected resolution;
- release resources reliably.

Optional implementations:

```text
ADBFrameProvider     # legacy/debug only
FileFrameProvider    # deterministic tests
ReplayFrameProvider  # recorded sessions
```

ADB must not be required by the main MS2130 + CH9329 path.

### `NormalizedFrame`

MS2130 output may not match the phone's logical coordinate space. A normalized frame records both the raw capture and the mapped logical phone frame.

Fields:

```text
raw_frame
normalized_image
raw_size
logical_screen_size
timestamp
provider_id
projection_transform
quality_flags
latency_ms
```

The normalized frame is the unit consumed by the verification engine.

### `ProjectionCalibration`

`ProjectionCalibration` maps between four coordinate spaces:

```text
Tkinter canvas coordinate
MS2130 raw frame coordinate
normalized phone logical pixel coordinate
CH9329 ratio coordinate
```

The first version can support simple stretch mapping, but the schema must allow future correction for:

- rotation;
- crop;
- letterboxing;
- non-uniform scaling;
- HDMI output resolution mismatch;
- portrait/landscape changes.

If projection calibration is wrong, verification must stop early with `MANUAL_REQUIRED` or `HARD_FAIL`, because continuing to click can cause destructive misoperation.

### `VerificationEngine`

`VerificationEngine` evaluates rules. It must be pure and testable: it receives frames, action metadata, projection metadata, and rules, then returns structured results.

It should not:

- call CH9329;
- open OpenCV devices;
- read UI state;
- directly mutate YAML.

Inputs:

```text
before_frame
after_frame or after_frame_window
action_metadata
verification_rules
projection_calibration
```

Output:

```text
VerificationResult
```

First-version rule types:

- `region_diff`
- `template_match`
- `color_probe`
- `touch_feedback`
- `stable_screen`

Reserved rule types:

- `ocr_text`
- `state_machine`
- `vision_model`
- `gesture_trace`

### `ActionVerifier`

`ActionVerifier` orchestrates a complete CH9329 action verification:

```text
capture stable before frame
execute CH9329 action
wait for post-action frames
run VerificationEngine
save evidence
return VerificationResult
```

Conceptual use:

```python
result = action_verifier.verify_action(
    action=Tap(point="xhs.publish.submit_button"),
    rules=["tap_feedback_near_target", "editor_page_marker_visible"],
)
```

The publish pipeline should eventually call:

```python
result = action_verifier.verify_step("xhs.home.tap_publish")
```

The pipeline should not manage OpenCV frames, diff images, template matching, or evidence file details itself.

### `VerificationResult`

Return a structured result rather than a boolean.

Statuses:

```text
PASS
UNKNOWN
RETRYABLE_FAIL
RECOVERABLE_FAIL
MANUAL_REQUIRED
HARD_FAIL
```

Fields:

```text
status
confidence
reason
matched_rules
failed_rules
evidence
suggested_action
provider_metadata
action_metadata
metrics
```

Evidence examples:

```text
before_frame_path
after_frame_path
diff_image_path
roi_paths
result_json_path
```

### `FailurePolicy`

Failure policy maps rule failures to operational decisions.

Default handling:

```text
coordinate closed-loop failure -> MANUAL_REQUIRED or HARD_FAIL
screen-change failure          -> RETRYABLE_FAIL
business semantic failure      -> RECOVERABLE_FAIL or MANUAL_REQUIRED
MS2130 capture failure         -> HARD_FAIL
destructive/final publish risk -> MANUAL_REQUIRED by default
```

## Three-layer verification

### Layer 1: coordinate closed-loop

Purpose: prove that the intended coordinate is valid and that the MS2130 projection mapping is trustworthy.

Checks:

- semantic point exists;
- point lies inside logical screen bounds;
- projection transform maps the point into visible normalized frame bounds;
- optional local touch feedback or local-region change appears near the target;
- capture profile identity matches the selected device/profile.

Failure handling:

```text
MANUAL_REQUIRED
```

Rationale: if coordinate mapping is wrong, repeated clicking can make things worse.

### Layer 2: screen-change verification

Purpose: prove that the UI reacted after CH9329 input.

Checks:

- `region_diff` exceeds threshold;
- page becomes stable after action;
- forbidden screens do not appear;
- expected loading/progress/change region updates.

Failure handling:

```text
RETRYABLE_FAIL
```

Rationale: no change may be caused by latency, missed tap, app lag, or capture timing. A limited retry is useful.

### Layer 3: business semantic verification

Purpose: prove that the resulting page/state is the intended business state.

Checks:

- template marker visible;
- expected button state or color appears;
- expected error modal is absent;
- success marker appears;
- optional OCR or model checks later.

Failure handling depends on action risk:

```text
safe action        -> recoverable or retryable
reversible action  -> recoverable
publish_final      -> manual_required
destructive action -> manual_required or hard_fail
```

## YAML configuration

YAML is the source of truth. The GUI may generate or edit YAML later, but runtime should consume YAML directly.

Recommended split:

```text
config/capture_profiles/<device_id>.yaml
config/verification_profiles/<flow_name>.yaml
```

### Capture profile example

```yaml
schema_version: 1

device:
  id: vivo_v2199a_001
  name: Vivo V2199A 001
  logical_screen:
    width: 1080
    height: 2400

observation:
  provider: ms2130_opencv
  ms2130:
    camera_index: 1
    name_hint: "MS2130"
    api: "CAP_DSHOW"
    expected_raw_size:
      width: 1920
      height: 1080
    expected_fps: 30

projection:
  rotation: 0
  crop:
    left: 0
    top: 0
    right: 1920
    bottom: 1080
  normalized_size:
    width: 1080
    height: 2400
  scale_mode: stretch

ch9329:
  port: COM5
  baudrate: 9600

health_checks:
  black_frame:
    enabled: true
    max_black_ratio: 0.95
  stale_frame:
    enabled: true
    max_age_ms: 500
  min_resolution:
    width: 1280
    height: 720
```

### Verification profile example

```yaml
schema_version: 1

flow:
  id: xhs_publish_note_v1
  name: 小红书图文/视频发布流程

defaults:
  timeout_ms: 3000
  stable_window_ms: 500
  retry_count: 2
  evidence_dir: runtime/verification

rules:
  tap_publish_button_reacts:
    description: 点击发布按钮后，发布区域应发生明显变化
    layer: screen_change
    type: region_diff
    region:
      x: 300
      y: 1800
      width: 500
      height: 500
    threshold:
      min_changed_ratio: 0.05
    timing:
      wait_after_action_ms: 500
      timeout_ms: 3000
    on_fail: retryable

  editor_page_marker_visible:
    description: 进入编辑页后，应出现编辑页顶部标识
    layer: business_semantic
    type: template_match
    template: templates/xhs/editor_page_header.png
    region:
      x: 0
      y: 0
      width: 1080
      height: 400
    threshold:
      min_score: 0.85
    on_fail: recoverable

  submit_button_enabled:
    description: 发布按钮应为可点击状态
    layer: business_semantic
    type: color_probe
    probes:
      - x: 960
        y: 2200
        expected:
          color_near: "#ff2442"
          tolerance: 35
    on_fail: manual_required

  tap_feedback_near_target:
    description: 点击点附近应出现局部反馈或画面变化
    layer: coordinate_closed_loop
    type: touch_feedback
    radius: 80
    threshold:
      min_changed_ratio: 0.015
    on_fail: manual_required
```

### Step binding example

```yaml
bindings:
  xhs.home.tap_publish:
    action:
      type: tap
      point: xhs.home.publish_button
      risk: reversible
    verify:
      - tap_feedback_near_target
      - tap_publish_button_reacts
      - editor_page_marker_visible
    failure_policy:
      coordinate_closed_loop: manual_required
      screen_change: retryable
      business_semantic: recoverable

  xhs.editor.tap_submit:
    action:
      type: tap
      point: xhs.editor.submit_button
      risk: publish_final
    verify:
      - tap_feedback_near_target
      - submit_button_enabled
    failure_policy:
      coordinate_closed_loop: manual_required
      screen_change: retryable
      business_semantic: manual_required
```

## Rule vocabulary

### `region_diff`

Compares before/after pixel changes in a region.

Use for:

- page transitions;
- modal appearance;
- upload/progress changes;
- list movement.

### `template_match`

Checks whether a known visual marker appears in a bounded region.

Use for:

- page headers;
- known buttons;
- success/failure markers;
- modal titles.

### `color_probe`

Checks one or more points or regions for expected color/brightness.

Use for:

- enabled button color;
- disabled state;
- brand-color markers;
- error indicators.

### `touch_feedback`

Checks local change near the intended tap coordinate.

Use for:

- coordinate closed-loop confidence;
- projection drift detection;
- calibration sanity checks.

This rule is useful but not always definitive because some Android screens do not show visible touch feedback.

### `stable_screen`

Checks that frame differences remain below a threshold for a time window.

Use before semantic verification to avoid checking during animations or loading.

## Action data flow

For one action such as `xhs.home.tap_publish`:

```text
1. Load capture profile and verification profile.
2. Open MS2130 FrameProvider.
3. Run capture health checks.
4. Capture stable before frame.
5. Resolve semantic point to logical x/y and CH9329 ratio.
6. Execute CH9329 action.
7. Capture post-action frame window.
8. Evaluate L1 coordinate closed-loop rules.
9. Evaluate L2 screen-change rules.
10. Evaluate L3 business semantic rules.
11. Aggregate rule results into VerificationResult.
12. Apply FailurePolicy.
13. Save evidence artifacts.
14. Return result to workbench or publish pipeline.
```

## Evidence storage

Store minimal evidence for every verification run:

```text
runtime/verification/
  <device_id>/
    <run_id>/
      <step_id>/
        before.png
        after.png
        diff.png
        roi_<rule_id>.png
        result.json
```

`result.json` should include:

```json
{
  "status": "RETRYABLE_FAIL",
  "confidence": 0.42,
  "action": {
    "type": "tap",
    "point": "xhs.home.publish_button",
    "x_ratio": 0.5,
    "y_ratio": 0.91
  },
  "rules": [
    {
      "id": "tap_publish_button_reacts",
      "status": "FAIL",
      "metric": {
        "changed_ratio": 0.012,
        "threshold": 0.05
      }
    }
  ],
  "provider": {
    "type": "ms2130_opencv",
    "camera_index": 1,
    "raw_size": [1920, 1080],
    "fps": 30
  },
  "suggested_action": "retry"
}
```

## Workbench integration

The existing `scripts/ch9329_visual_debug.py` should become a client of the shared verification core.

Rename the mental model from:

```text
CH9329 & ADB physical phone coordinate workbench
```

to:

```text
CH9329 & MS2130 verification workbench
```

First useful UI scope:

- select MS2130 camera device;
- show live MS2130 preview;
- show capture health diagnostics;
- freeze/snapshot current frame;
- show logical coordinate hover and ratio;
- click frame to send CH9329 tap;
- run selected YAML rule;
- show PASS/FAIL/UNKNOWN result log;
- save before/after/diff evidence.

Later UI scope:

- draw ROI;
- save template images;
- tune thresholds;
- generate YAML rules;
- edit capture projection interactively;
- preview publish-flow bindings.

## Publish pipeline integration

The automated publish pipeline should use the same `ActionVerifier` as the workbench.

Pipeline behavior:

```text
PASS             -> continue
UNKNOWN          -> wait/retry or pause depending on rule
RETRYABLE_FAIL   -> retry current action within policy limits
RECOVERABLE_FAIL -> run recovery steps, then re-check
MANUAL_REQUIRED  -> pause device/job and save evidence
HARD_FAIL        -> abort job/device and notify
```

The pipeline must not depend on the workbench window being open.

Final publish or destructive actions should default to conservative handling. If semantic verification is ambiguous, the pipeline should pause rather than risking duplicate posts or accidental destructive operations.

## Testing strategy

### Unit tests without hardware

Use `FileFrameProvider` or `ReplayFrameProvider`.

Cover:

- YAML loading and validation;
- projection mapping;
- region diff thresholds;
- template match pass/fail;
- color probe tolerance;
- touch feedback ROI crop;
- stable screen detection;
- result aggregation;
- failure policy mapping.

### MS2130 integration tests

Require hardware and should not run in normal CI by default.

Cover:

- enumerate/open camera device;
- capture frame;
- detect black frame;
- validate resolution/FPS;
- save snapshot;
- release capture resources.

### Hardware closed-loop tests

Require MS2130 + CH9329 + a safe test phone state.

Cover:

- click safe coordinate;
- verify local feedback or region diff;
- swipe list and detect screen movement;
- run a full binding with evidence saved.

### Publish dry-run

Before fully unattended publishing:

- run through non-destructive steps;
- disable or manually gate final publish action;
- save evidence for each step;
- tune thresholds from actual MS2130 footage.

## Acceptance criteria

First version is acceptable when:

1. ADB is not required to view the phone screen.
2. MS2130 frames appear in the workbench through OpenCV DirectShow/UVC.
3. CH9329 still performs physical click/swipe/key actions.
4. The workbench can map a displayed MS2130 frame coordinate to logical phone coordinates and CH9329 ratios.
5. Capture profile YAML can be loaded.
6. Verification profile YAML can be loaded.
7. At least `region_diff`, `template_match`, and `color_probe` rules run against frames.
8. A CH9329 action can produce a structured `VerificationResult` using MS2130 before/after frames.
9. Evidence artifacts are saved under `runtime/verification/`.
10. Failure classes distinguish capture failure, coordinate failure, no screen change, and business semantic mismatch.
11. The publish pipeline can call the shared `ActionVerifier` without depending on Tkinter UI.

## Open questions

1. Which MS2130 identity is stable enough in the target Windows environment: camera index, friendly name substring, resolution/FPS, or a saved user-confirmed profile?
2. Which first 5-10 business states matter most for publish verification?
3. Which publish actions are irreversible or duplicate-risk and must never auto-retry?
4. Should ADB be kept as a hidden debug adapter, or fully removed from the workbench once MS2130 works?
5. What retention policy should evidence artifacts use for failed publish jobs?
