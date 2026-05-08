# AnimateDiff Session Handoff

## Scope
This handoff is for continuing AnimateDiff local ComfyUI validation in a new session.

## Current Status
- Validation script exists and is runnable:
  - `scripts/validate_animatediff_smoke.py`
- Latest normal run is completed and report is updated:
  - `output/animatediff_smoke_report.json`
- Current result:
  - `STATUS: FAIL`
  - `CLASSIFICATION: model`

## Latest Failure Details
ComfyUI prompt validation fails before execution with `value_not_in_list`:
- `CheckpointLoaderSimple.ckpt_name`: `v1-5-pruned-emaonly.safetensors` not in list
- `ADE_AnimateDiffLoaderGen1.model_name`: `mm_sd_v15_v2.ckpt` not in list

## Required Files
- `v1-5-pruned-emaonly.safetensors`
- `mm_sd_v15_v2.ckpt`

## Candidate Model Directories to Check
- `C:/ComfyUI/models/checkpoints`
- `C:/ComfyUI/models/animatediff_models`
- `D:/ComfyUI-Data/models/checkpoints`
- `D:/ComfyUI-Data/models/animatediff_models`

## Commands for New Session
From workspace root `D:/vscocde file/github-video-项目/Pixelle-Video`.

1) Optional precheck:

```powershell
uv run python scripts/validate_animatediff_smoke.py --dry-run
```

2) Normal validation (required):

```powershell
uv run python scripts/validate_animatediff_smoke.py --timeout 600 --report-file output/animatediff_smoke_report.json
```

## Pass Criteria
- `STATUS: PASS`
- Normal mode returns a prompt result and non-empty output path list (or completed history item)

## If Still Failing
1. Re-open ComfyUI and verify model dropdown values include the exact two filenames.
2. Verify ComfyUI is using the expected model root (extra model paths config may override).
3. Re-run the normal command and compare `result` + `checks.filesystem_hits` in report JSON.

## Quick Resume Prompt (for new session)
"Read `docs/HANDOFF_ANIMATEDIFF_SESSION.md`, run normal validation, and report only the JSON `result` field and next blocking cause."
