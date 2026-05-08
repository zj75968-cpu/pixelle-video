# 工作流定制

如何自定义 ComfyUI 工作流以实现特定功能。

---

## 工作流简介

Pixelle-Video 基于 ComfyUI 架构，支持自定义工作流。

---

## 工作流类型

### TTS 工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

用于文本转语音（Text-to-Speech），支持多种 TTS 引擎：
- Edge-TTS
- Index-TTS（支持声音克隆）
- 其他 ComfyUI 兼容的 TTS 节点

### 图像生成工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

用于生成静态图像作为视频背景：
- FLUX 系列模型
- Stable Diffusion 系列模型
- 其他图像生成模型

### 视频生成工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

**新功能**：支持 AI 视频生成，创建动态视频内容。

**预置工作流**：
- `selfhost/video_animatediff_sd15.json`: 本地工作流
  - 需要本地 ComfyUI 环境
  - 需要安装 AnimateDiff 与 VideoHelperSuite 等视频生成节点
  - 适合有本地 GPU 的用户

**使用场景**：
- 配合 `video_*.html` 模板使用
- 自动根据文案生成动态视频背景
- 增强视频的视觉表现力和观看体验

---

## 自定义工作流

1. 在 ComfyUI 中设计你的工作流
2. 导出为 JSON 文件
3. 放置到 `workflows/` 目录
4. 在 Web 界面中选择使用

---

## 更多信息

即将推出更详细的工作流定制指南。

---

## AnimateDiff + ComfyUI 本地集成（SD1.5）

如果你要在本机生成真正动态 AI 视频，可以使用仓库内新增的工作流：

- `selfhost/video_animatediff_sd15.json`

该工作流会被系统自动识别为 `video_` 前缀视频工作流，并可在 Web 配置中选择。

### 1. 安装 ComfyUI 插件

在你的 ComfyUI `custom_nodes` 目录安装以下插件：

1. ComfyUI-AnimateDiff-Evolved
2. ComfyUI-VideoHelperSuite
3. ComfyUI-Custom-Scripts（可选，便于调试）

也可以直接使用项目内脚本一键安装/更新（Windows）：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
powershell -ExecutionPolicy Bypass -File .\scripts\install_animatediff_comfyui_windows.ps1 -ComfyUIRoot "D:\ComfyUI_windows_portable\ComfyUI"
```

安装后重启 ComfyUI，确认前端可看到 AnimateDiff 与 VHS 相关节点。

### 2. 准备模型文件

至少需要以下模型（示例命名）：

1. SD1.5 基础模型：`v1-5-pruned-emaonly.safetensors`
2. AnimateDiff motion module：`mm_sd_v15_v2.ckpt`

建议目录：

1. 基础模型放在 ComfyUI 的 checkpoints 目录
2. motion module 放在 AnimateDiff 对应模型目录（通常在 `models/animatediff_models`）

注意：如果你的模型文件名与工作流中不一致，请在 ComfyUI 打开并修改节点参数后重新保存工作流。

### 3. 在项目中启用工作流

修改 `config.yaml`：

```yaml
comfyui:
  comfyui_url: http://127.0.0.1:8188
  video:
    default_workflow: selfhost/video_animatediff_sd15.json
```

如果你在代理网络环境下运行本地 ComfyUI，请设置：

```powershell
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY
```

### 4. 低显存建议参数

如果显存不足，优先把以下参数压低：

1. 分辨率：先用 `512x768`
2. 帧数：先用 `16` 到 `24`
3. steps：先用 `20` 到 `25`

### 5. 常见问题

1. 报错找不到 `ADE_*` 节点：AnimateDiff-Evolved 未正确安装或版本不匹配。
2. 报错找不到 motion model：`mm_sd_v15_v2.ckpt` 未放到正确目录，或文件名不一致。
3. 生成失败且显存爆掉：降低分辨率、帧数和步数，关闭其他占用 GPU 的程序。
4. 本地 URL 访问异常（127.0.0.1:8188）：检查系统代理与 `NO_PROXY` 设置。

### 6. 补齐模型后的 一键复验

当你补齐以下两个文件后：

1. `v1-5-pruned-emaonly.safetensors`
2. `mm_sd_v15_v2.ckpt`

建议先跑一次项目内 smoke 脚本，确认服务、节点、模型和最小闭环：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
uv run python scripts\validate_animatediff_smoke.py --dry-run
```

如果 dry-run 通过，再执行最小闭环提交：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
uv run python scripts\validate_animatediff_smoke.py --timeout 600 --report-file output\animatediff_smoke_report.json
```

结果判读：

1. `STATUS: PASS`：通过，说明本次复验已闭环。
2. `CLASSIFICATION: model`：仍是模型层问题，查看 `MISSING_MODELS` 与 `MISSING_FILES_FROM_ERROR`。
3. `CLASSIFICATION: node`：节点层问题，通常是插件未安装或重启未生效。
4. `CLASSIFICATION: parameter`：参数层问题，优先检查工作流节点必填项。

