# Workflow Customization

How to customize ComfyUI workflows to achieve specific functionality.

---

## Workflow Introduction

Pixelle-Video is built on the ComfyUI architecture and supports custom workflows.

---

## Workflow Types

### TTS Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

Used for Text-to-Speech, supporting various TTS engines:
- Edge-TTS
- Index-TTS (supports voice cloning)
- Other ComfyUI-compatible TTS nodes

### Image Generation Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

Used for generating static images as video backgrounds:
- FLUX series models
- Stable Diffusion series models
- Other image generation models

### Video Generation Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

**New Feature**: Supports AI video generation to create dynamic video content.

**Preset Workflows**:
- `selfhost/video_animatediff_sd15.json`: Local workflow
  - Requires local ComfyUI environment
  - Requires AnimateDiff and VideoHelperSuite video nodes
  - Suitable for users with local GPU

**Use Cases**:
- Works with `video_*.html` templates
- Automatically generates dynamic video backgrounds based on scripts
- Enhances visual expressiveness and viewing experience

---

## Custom Workflows

1. Design your workflow in ComfyUI
2. Export as JSON file
3. Place in `workflows/` directory
4. Select and use in Web interface

---

## More Information

Detailed workflow customization guide coming soon.

---

## AnimateDiff + ComfyUI Local Integration (SD1.5)

To generate true dynamic AI video locally, use the new workflow:

- `selfhost/video_animatediff_sd15.json`

It follows the `video_` naming convention, so it is auto-discovered by the project workflow scanner.

### 1. Install ComfyUI custom nodes

Install these nodes into your ComfyUI `custom_nodes` directory:

1. ComfyUI-AnimateDiff-Evolved
2. ComfyUI-VideoHelperSuite
3. ComfyUI-Custom-Scripts (optional, useful for debugging)

You can also run the Windows helper script from this repository:

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
powershell -ExecutionPolicy Bypass -File .\scripts\install_animatediff_comfyui_windows.ps1 -ComfyUIRoot "D:\ComfyUI_windows_portable\ComfyUI"
```

Restart ComfyUI and verify AnimateDiff/VHS nodes are visible.

### 2. Prepare model files

Minimum required models:

1. SD1.5 checkpoint: `v1-5-pruned-emaonly.safetensors`
2. AnimateDiff motion module: `mm_sd_v15_v2.ckpt`

Recommended placement:

1. SD checkpoint in ComfyUI checkpoints directory
2. motion module in AnimateDiff model directory (commonly `models/animatediff_models`)

If your filenames differ from the workflow defaults, open the workflow in ComfyUI, update node values, then save.

### 3. Enable in project config

Update your `config.yaml`:

```yaml
comfyui:
  comfyui_url: http://127.0.0.1:8188
  video:
    default_workflow: selfhost/video_animatediff_sd15.json
```

If your machine uses a local proxy, set bypass variables before starting the app:

```powershell
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY
```

### 4. Low-VRAM starter settings

For first successful runs on smaller GPUs:

1. Resolution: start at `512x768`
2. Frame count: `16` to `24`
3. Steps: `20` to `25`

### 5. Common issues

1. Missing `ADE_*` nodes: AnimateDiff-Evolved not installed or version mismatch.
2. Missing motion model: `mm_sd_v15_v2.ckpt` is missing or in wrong folder.
3. Out-of-memory: lower resolution, frame count, and steps.
4. Local ComfyUI URL fails (127.0.0.1): check proxy and `NO_PROXY` settings.

