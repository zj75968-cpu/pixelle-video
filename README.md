<h1 align="center">🎬 Pixelle-Video —— AI 全自动短视频引擎</h1>

<p align="center"><a href="README_EN.md">English</a> | <b>中文</b></p>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1WzyGBnEVp/?vd_source=e7e7d4ca8db9a18c80f17a24a6582fca" target="_blank"><img src="https://img.shields.io/badge/🎥 视频教程-EA4C89" alt="视频教程"></a>
  <a href="https://github.com/AIDC-AI/Pixelle-Video/releases" target="_blank"><img src="https://img.shields.io/badge/📦 Windows包-50C878" alt="Windows整合包"></a>
  <a href="https://aidc-ai.github.io/Pixelle-Video/zh" target="_blank"><img src="https://img.shields.io/badge/📘 使用文档-4A90E2" alt="使用文档"></a>
  <a href="https://github.com/AIDC-AI/Pixelle-Video/stargazers"><img src="https://img.shields.io/github/stars/AIDC-AI/Pixelle-Video.svg" alt="Stargazers"></a>
  <a href="https://github.com/AIDC-AI/Pixelle-Video/issues"><img src="https://img.shields.io/github/issues/AIDC-AI/Pixelle-Video.svg" alt="Issues"></a>
  <a href="https://github.com/AIDC-AI/Pixelle-Video/network/members"><img src="https://img.shields.io/github/forks/AIDC-AI/Pixelle-Video.svg" alt="Forks"></a>
  <a href="https://github.com/AIDC-AI/Pixelle-Video/blob/main/LICENSE"><img src="https://img.shields.io/github/license/AIDC-AI/Pixelle-Video.svg" alt="License"></a>
</p>

https://github.com/user-attachments/assets/a42e7457-fcc8-40da-83fc-784c45a8b95d

<br/>

只需输入一个 **主题**，Pixelle-Video 就能自动完成：
- ✍️ 撰写视频文案  
- 🎨 生成 AI 配图/视频  
- 🗣️ 合成语音解说  
- 🎵 添加背景音乐  
- 🎬 一键合成视频  

**零门槛，零剪辑经验**，让视频创作成为一句话的事！


## 🖥️ Web 界面预览

![Web UI界面](resources/webui.png)


## 📋 最近更新

- ✅ **2026-01-26**: 新增「动作迁移」模块，上传参考视频和图片进行动作迁移
- ✅ **2026-01-14**: 新增「数字人口播」和「图生视频」流水线，新增多语言 TTS 音色支持
- ✅ **2026-01-06**: 新增 RunningHub 48G 显存机器调用支持
- ✅ **2025-12-28**: 支持 RunningHub 并发限制可配置，优化 LLM 返回结构化数据的逻辑
- ✅ **2025-12-17**: 支持 ComfyUI API Key 配置，支持 Nano Banana 模型调用，API 接口支持模板自定义参数
- ✅ **2025-12-10**: 侧边栏内置 FAQ，锁定 edge-tts 版本修复 TTS 服务不稳定问题
- ✅ **2025-12-08**: 支持固定脚本多种分割方式(段落/行/句子)，优化模板选择交互逻辑支持直接预览选择
- ✅ **2025-12-06**: 修复视频生成 API 返回 URL 路径处理，支持跨平台兼容
- ✅ **2025-12-05**: 新增 Windows 整合包下载，优化图片与视频反推工作流
- ✅ **2025-12-04**: 新增「自定义素材」功能，支持用户上传自己的照片和视频，AI 智能分析生成脚本
- ✅ **2025-11-18**: 优化 RunningHub 服务调用支持并行处理，新增历史记录页面，支持批量创建视频任务


## ✨ 功能亮点

- ✅ **全自动生成** - 输入主题，自动生成完整视频
- ✅ **AI 智能文案** - 根据主题智能创作解说词，无需自己写脚本
- ✅ **AI 生成配图** - 每句话都配上精美的 AI 插图
- ✅ **AI 生成视频** - 支持通过本地视频工作流创建动态视频内容
- ✅ **AI 生成语音** - 支持 Edge-TTS、Index-TTS 等众多主流 TTS 方案
- ✅ **背景音乐** - 支持添加 BGM，让视频更有氛围
- ✅ **视觉风格** - 多种模板可选，打造独特视频风格
- ✅ **灵活尺寸** - 支持竖屏、横屏等多种视频尺寸
- ✅ **多种 AI 模型** - 支持 GPT、通义千问、DeepSeek、Ollama 等
- ✅ **原子能力灵活组合** - 基于 ComfyUI 架构，可使用预置工作流，也可自定义任意能力（如替换生图模型为 FLUX、替换 TTS 为 ChatTTS 等）


## 📊 视频生成流程

Pixelle-Video 采用模块化设计，整个视频生成流程清晰简洁：

![视频生成流程图](resources/flow.png)

从输入文本到最终视频输出，整个流程简洁清晰：**文案生成 → 配图规划 → 逐帧处理 → 视频合成**

每个环节都支持灵活定制，可选择不同的 AI 模型、音频引擎、视觉风格等，满足个性化创作需求。


## 🎬 视频示例

以下是使用 Pixelle-Video 生成的实际案例，展示了不同主题和风格的视频效果：

### 📱 扩展模块视频展示

<table>
<tr>
<td width="33%">
<h3>👤 数字人口播</h3>
<video src="https://github.com/user-attachments/assets/7c122563-c2e0-4dcd-a73c-25ba1d4fa2dd" controls width="100%"></video>
<p align="center"><b>韩语数字人口播</b></p>
</td>
<td width="33%">
<h3>🖼️ 图生视频</h3>
<video src="https://github.com/user-attachments/assets/5b4eef17-07d0-4bde-9748-2ed68cc9888e" controls width="100%"></video>
<p align="center"><b>卡通视频</b></p>
</td>
<td width="33%">
<h3>💃 动作迁移</h3>
<video src="https://github.com/user-attachments/assets/7b1240bc-e965-434c-b343-118ec4793d4f" controls width="100%"></video>
<p align="center"><b>跳舞小猫</b></p>
</td>
</tr>
</table>


### 📱 竖屏视频展示

<table>
<tr>
<td width="33%">
<h3>🌄 人文纪实类 - 视频默认模版</h3>
<video src="https://github.com/user-attachments/assets/e6716c1d-78de-453d-84c2-10873c8c595f" controls width="100%"></video>
<p align="center"><b>旅行路上的风景让人流连忘返</b></p>
</td>
<td width="33%">
<h3>🔍 文化解构类 - 视频默认模版</h3>
<video src="https://github.com/user-attachments/assets/f5de75f6-135a-4ab4-9f5f-079f649764d5" controls width="100%"></video>
<p align="center"><b>Santa ID</b></p>
</td>
<td width="33%">
<h3>🔭 科学思辨类 - 视频默认模版</h3>
<video src="https://github.com/user-attachments/assets/ceb8b0df-8331-4e1f-88e7-db5b295a1c1d" controls width="100%"></video>
<p align="center"><b>为什么我们还没有找到外星文明？</b></p>
</td>
</tr>
<tr>
<td width="33%">
<h3>🌱 个人成长类 - 克隆音色</h3>
<video src="https://github.com/user-attachments/assets/1bad9a49-df83-4905-9cc8-9a7640e9c7d8" controls width="100%"></video>
<p align="center"><b>如何提升自己</b></p>
</td>
<td width="33%">
<h3>🧠 深度思考类 - 默认模板</h3>
<video src="https://github.com/user-attachments/assets/663b705a-2aea-44bc-b266-4bb27aa255a8" controls width="100%"></video>
<p align="center"><b>如何理解反脆弱</b></p>
</td>
<td width="33%">
<h3>🏯 历史文化类 - 固定画面</h3>
<video src="https://github.com/user-attachments/assets/56e0a018-fa99-47eb-a97f-fc2fa8915724" controls width="100%"></video>
<p align="center"><b>资治通鉴</b></p>
</td>
</tr>
<tr>
<td width="33%">
<h3>☀️ 情感类 - 克隆音色</h3>
<video src="https://github.com/user-attachments/assets/4687df95-dd21-4a7b-b01e-f33a7b646644" controls width="100%"></video>
<p align="center"><b>冬日暖阳</b></p>
</td>
<td width="33%">
<h3>📜 小说解说类 - 自创脚本</h3>
<video src="https://github.com/user-attachments/assets/d354465e-3fa8-40b4-93e9-61ad75ef0697" controls width="100%"></video>
<p align="center"><b>斗破苍穹</b></p>
</td>
<td width="33%">
<h3>🧬 知识科普类 - Qwen生图</h3>
<video src="https://github.com/user-attachments/assets/8ac21768-41ce-4d41-acdd-e3dd3eb9725a" controls width="100%"></video>
<p align="center"><b>养生知识</b></p>
</td>
</tr>
</table>

### 🖥️ 横屏视频展示

<table>
<tr>
<td width="50%">
<h3>💰 副业赚钱 - 电影模板</h3>
<video src="https://github.com/user-attachments/assets/c9209d4e-73a6-4b82-aaad-cf102248c9e2" controls width="100%"></video>
<p align="center"><b>副业赚钱</b></p>
</td>
<td width="50%">
<h3>🏛️ 历史解说 - 自定义模板</h3>
<video src="https://github.com/user-attachments/assets/a767c452-d5f1-4cff-bb34-b80fff0d4c3e" controls width="100%"></video>
<p align="center"><b>资治通鉴启示录</b></p>
</td>
</tr>
</table>

> 💡 **提示**: 这些视频都是通过输入一个主题关键词，由 AI 全自动生成的，无需任何视频剪辑经验！


<div id="tutorial-start" />


## 🚀 快速开始

### ✅ 本机快速跑通（当前工作区）

本仓库已在本机路径 `D:\vscocde file\github-video-项目\Pixelle-Video` 下准备好源码环境，适合直接从源码启动和调试。

#### 1. 环境检查

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
uv --version
.\ffmpeg-temp\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe -version
```

项目自带 FFmpeg 位于 `ffmpeg-temp\ffmpeg-8.1-essentials_build\bin`。如果系统 PATH 中没有 `ffmpeg`，源码运行仍会优先尝试加载这个本地目录。

#### 2. 启动 Pixelle-Video Web

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY
uv run streamlit run web/app.py --server.port 8501
```

打开浏览器访问：

```text
http://localhost:8501
```

#### 3. 配置 LLM

在「⚙️ 系统配置（必需）」中填写：

- 快速选择：`DeepSeek` 或 `Custom`
- API Key：填入你的 DeepSeek API Key
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-chat`

点击「🔌 测试」确认 LLM 可用，再点击「💾 保存配置」。

DeepSeek API Key 获取入口：登录 DeepSeek 开放平台，进入 API Keys 页面创建密钥。参考：[DeepSeek API Docs](https://api-docs.deepseek.com/api/deepseek-api/)。

#### 4. 启动并测试 ComfyUI

本机 ComfyUI 服务地址使用：

```text
http://127.0.0.1:8188
```

优先启动桌面脚本：

```powershell
& "C:\Users\Administrator\Desktop\启动 ComfyUI（FLUX）.bat"
```

如果桌面脚本依赖路径缺失，可用本机安装器修复：

```powershell
& "C:\Users\Administrator\AppData\Local\@comfyorgcomfyui-electron-updater\installer.exe" /S
```

服务启动后验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats
```

Web 页面中点击「ComfyUI 配置」里的「测试连接」，看到连接成功即可。ComfyUI 本地 API Key 通常留空；只有使用 Comfy Cloud/平台鉴权节点时才需要。Comfy Cloud API Key 可在登录后从 Comfy 平台创建，参考：[Comfy Cloud API Overview](https://docs.comfy.org/development/cloud/overview)。

> 当前本机注意事项：如果 `D:\ComfyUI-Data\models` 或具体模型权重不存在，`selfhost` 生图/生视频工作流可能失败。此时先选择「📄 静态样式」模板跑通主视频流程；修复模型后再切回「🖼️ 生成插图」或「🎬 生成视频」。
>
> 如果命令行访问 `system_stats` 正常，但 Web UI 测试 ComfyUI 失败或出现 502，通常是本机代理拦截了 `127.0.0.1`。按第 2 步设置 `NO_PROXY=127.0.0.1,localhost` 后重启 Streamlit。
>
> Windows 下如果生成静态模板时报 `HTML rendering failed:`，检查 `web/utils/async_helpers.py` 是否使用 Proactor event loop；Playwright Chromium 渲染 HTML 截图需要支持 subprocess 的事件循环。修改后需重启 Streamlit。

#### 5. 生成一条最小测试视频

1. 在首页打开「⚡ 快速创作」。
2. 选择「💡 AI 创作」，输入一个短主题，例如：`三个提升专注力的小方法`。
3. 将分镜数调到 `3`。
4. 配音合成保持「本地合成」。
5. 如果 ComfyUI 模型未确认完整，分镜类型选择「📄 静态样式」。
6. 点击「🎬 生成视频」。
7. 生成完成后到「📚 History」查看记录，视频文件会保存到 `output/`。

#### 6. 批量生成动态短视频

如果需要一次生成多条可交付的动态 MP4，可使用本仓库的本机批量生成脚本：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
uv run python scripts\generate_dynamic_samples.py --count 10
```

脚本会输出竖屏动态短视频到 `output/dynamic_<时间戳>_*/final.mp4`，并同步生成预览拼图、批量清单和 History 索引。当前本机已生成一批样片：

```text
output/dynamic_20260507_012313_*/final.mp4
```

更详细的交付级操作文档见：[动态视频生成操作手册.md](动态视频生成操作手册.md)。这份文档包含启动、配置、ComfyUI 插件、模型文件、生成视频、查看历史和常见错误处理。

#### 7. 批量生成复杂场景动画

如果需要的不是“图形动效模板”，而是有角色、场景、道具、镜头运动和分段动作的复杂 2D 动画，使用：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
uv run python scripts\generate_complex_animation_samples.py --count 10
```

脚本会输出竖屏复杂动画 MP4 到 `output/complex_<时间戳>_*/final.mp4`，并同步生成预览拼图、批量清单和 History 索引。当前本机已生成一批复杂动画样片：

```text
output/complex_20260507_091150_*/final.mp4
```

#### 8. 生成 20 秒 ComfyUI 合成版复杂动画

如果需要 20 秒长视频，并且要求最终视频封装走 ComfyUI，可使用：

```powershell
cd "D:\vscocde file\github-video-项目\Pixelle-Video"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY
uv run python scripts\generate_comfy_complex_20s.py --duration 20
```

这个脚本会先生成 20 秒、15fps 的复杂逐帧动画序列，再通过 ComfyUI 的 `VHS_LoadImagesPath`、`VHS_LoadAudio`、`VHS_VideoCombine` 合成 MP4。当前本机已生成：

```text
output/comfy_complex_20260507_110924_01_journey_20s/final.mp4
```

> 注意：当前本机仍未安装 AnimateDiff/FLUX 等大模型权重，所以这里使用的是 ComfyUI VideoHelperSuite 做帧序列与音频合成；如需 ComfyUI 直接 AI 生视频，需要先补齐对应模型文件。

#### 9. RunningHub 云端可选方案

如果不想维护本地 ComfyUI，可在「RunningHub 云端」填写 RunningHub API Key，并使用 `runninghub/...` 工作流。RunningHub API Key 可在官网登录后从右上角资料菜单查看，参考：[RunningHub API Instructions](https://www.runninghub.ai/runninghub-api-doc-en/doc-8287463)。

### 🪟 Windows 一键整合包（推荐 Windows 用户使用）

**无需安装 Python、uv 或 ffmpeg，一键开箱即用！**

👉 **[下载 Windows 一键整合包](https://github.com/AIDC-AI/Pixelle-Video/releases/latest)**

1. 下载最新的 Windows 一键整合包并解压
2. 双击运行 `start.bat` 启动 Web 界面
3. 浏览器会自动打开 http://localhost:8501
4. 在「⚙️ 系统配置」中配置 LLM API 和图像生成服务
5. 开始生成视频！

> 💡 **提示**: 整合包已包含所有依赖，无需手动安装任何环境。首次使用只需配置 API 密钥即可。


### 从源码安装（适合 macOS / Linux 用户或需要自定义的用户）

#### 前置环境依赖

在开始之前，需要先安装 Python 包管理器 `uv` 和视频处理工具 `ffmpeg`：

##### 安装 uv

请访问 uv 官方文档查看适合你系统的安装方法：  
👉 **[uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/)**

安装完成后，在终端中运行 `uv --version` 验证安装成功。

##### 安装 ffmpeg

**macOS**
```bash
brew install ffmpeg
```

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Windows**
- 下载地址：https://ffmpeg.org/download.html
- 下载后解压，将 `bin` 目录添加到系统环境变量 PATH 中

安装完成后，在终端中运行 `ffmpeg -version` 验证安装成功。


#### 第一步：下载项目

```bash
git clone https://github.com/AIDC-AI/Pixelle-Video.git
cd Pixelle-Video
```

#### 第二步：启动 Web 界面

```bash
# 使用 uv 运行（推荐，会自动安装依赖）
uv run streamlit run web/app.py
```

浏览器会自动打开 http://localhost:8501

#### 第三步：在 Web 界面配置

首次使用时，展开「⚙️ 系统配置」面板，填写：
- **LLM 配置**: 选择 AI 模型（如通义千问、GPT 等）并填入 API Key
- **图像配置**: 如需生成图片，配置 ComfyUI 地址或 RunningHub API Key

配置好后点击「保存配置」，就可以开始生成视频了！

<div id="tutorial-end" />

## 💻 使用方法

打开 Web 界面后，你会看到三栏布局，下面详细讲解每个部分：


### ⚙️ 系统配置（首次必填）

首次使用时需要配置，点击展开「⚙️ 系统配置」面板：

#### 1. LLM 配置（大语言模型）
用于生成视频文案的 AI。

**快速选择预设**  
- 通过下拉菜单选择预设模型（通义千问、GPT-4o、DeepSeek 等）
- 选择后会自动填充 base_url 和 model
- 点击「🔑 获取 API Key」链接去注册并获取密钥

**手动配置**  
- API Key: 填入你的密钥
- Base URL: API 地址
- Model: 模型名称

#### 2. 图像配置
用于生成视频配图的 AI。

**本地部署（推荐）**  
- ComfyUI URL: 本地 ComfyUI 服务地址（默认 http://127.0.0.1:8188）
- 点击「测试连接」确认服务可用

**云端部署**  
- RunningHub API Key: 云端图像生成服务的密钥

配置完成后点击「保存配置」。


### 📝 内容输入（左侧栏）

#### 生成模式
- **AI 生成内容**: 输入主题，AI 自动创作文案
  - 适合：想快速生成视频，让 AI 写稿
  - 例如：「为什么要养成阅读习惯」
- **固定文案内容**: 直接输入完整文案，跳过 AI 创作
  - 适合：已有现成文案，直接生成视频

#### 背景音乐（BGM）
- **无 BGM**: 纯人声解说
- **内置音乐**: 选择预置的背景音乐（如 default.mp3）
- **自定义音乐**: 将你的音乐文件（MP3/WAV 等）放到 `bgm/` 文件夹
- 点击「试听 BGM」可以预览音乐


### 🎤 语音设置（中间栏）

#### TTS 工作流
- 从下拉菜单选择 TTS 工作流（支持 Edge-TTS、Index-TTS 等）
- 系统会自动扫描 `workflows/` 文件夹中的 TTS 工作流
- 如果懂 ComfyUI，可以自定义 TTS 工作流

#### 参考音频（可选）
- 上传参考音频文件用于声音克隆（支持 MP3/WAV/FLAC 等格式）
- 适用于支持声音克隆的 TTS 工作流（如 Index-TTS）
- 上传后可以直接试听

#### 预览功能
- 输入测试文本，点击「预览语音」即可试听效果
- 支持使用参考音频进行预览


### 🎨 视觉设置（中间栏）

#### 图像生成
决定 AI 生成什么风格的配图。

**ComfyUI 工作流**  
- 从下拉菜单选择图像生成工作流
- 支持本地部署（selfhost）和云端（RunningHub）工作流
- 默认使用 `image_flux.json`
- 如果懂 ComfyUI，可以放自己的工作流到 `workflows/` 文件夹

**图像尺寸**  
- 设置生成图像的宽度和高度（单位：像素）
- 默认 1024x1024，可根据需要调整
- 注意：不同的模型对尺寸有不同的限制

**提示词前缀（Prompt Prefix）**  
- 控制图像的整体风格（语言需要是英文的）
- 例如：Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style
- 点击「预览风格」可以测试效果

#### 视频模板
决定视频画面的布局和设计。

**模板命名规范**  
- `static_*.html`: 静态模板（无需AI生成媒体，纯文字样式）
- `image_*.html`: 图片模板（使用AI生成的图片作为背景）
- `video_*.html`: 视频模板（使用AI生成的视频作为背景）

**使用方法**  
- 从下拉菜单选择模板，按尺寸分组显示（竖屏/横屏/方形）
- 点击「预览模板」可以自定义参数测试效果
- 如果懂 HTML，可以在 `templates/` 文件夹创建自己的模板
- 🔗 [查看所有模板效果图](https://aidc-ai.github.io/Pixelle-Video/zh/user-guide/templates/#_3)


### 🎬 视频生成工作流（中间栏 - 当选择"video"模板时出现）

#### 什么是 AnimateDiff？

**AnimateDiff** 是一个 Stable Diffusion 的运动模块，可以将静态图像转变为具有自然运动的视频片段。在 Pixelle-Video 中，AnimateDiff 被集成为默认的视频生成工作流，提供：

- ✨ **流畅的动画运动** - 为 AI 生成的图像添加自然的动画效果
- 🎥 **动态镜头感** - 支持缩放、平移等镜头运动
- ⚡ **快速生成** - 本地 GPU 加速，速度快
- 💰 **完全免费** - 支持本地 ComfyUI 部署

#### 如何在界面中使用 AnimateDiff？

**第一步：选择"video"模板类型**

在「🎨 视觉设置」部分，模板类型选择器中选择 **【视频】** 标签：

```
[ 静态 ]  [ 图片 ]  [ 视频 ] ← 点击这个
```

**第二步：选择 AnimateDiff 工作流**

选择"视频"模板后，会自动出现"ComfyUI 工作流"选择器，列出所有可用的视频生成工作流。选择：

```
video_animatediff_sd15.json - Selfhost
```

这个工作流使用 Stable Diffusion 1.5 + AnimateDiff 运动模块的组合。

**第三步：配置其他参数**

- **图像尺寸**：设置生成视频的分辨率（默认 512x768）
- **提示词前缀**：控制视频的整体风格和质量
- **其他设置**：帧率、时长等在系统配置中调整

**第四步：生成视频**

点击「🎬 生成视频」按钮，系统会：

1. 根据主题生成文案
2. 为每个分镜生成配图
3. 使用 AnimateDiff 将静止图像转换为动画视频
4. 合成语音和 BGM
5. 输出最终视频

#### API 调用示例

如果你更倾向于直接调用 API，可以使用以下 PowerShell 脚本：

```powershell
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY

$body = @{
    mode = "generate"
    text = "一个人在办公室工作的场景"
    frame_template = "1080x1920/video_default.html"
    media_workflow = "selfhost/video_animatediff_sd15.json"
    video_fps = 24
    n_scenes = 3
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8001/api/video/generate/sync" `
    -Body $body `
    -ContentType "application/json"
```

**关键参数说明：**

| 参数 | 说明 | 示例 |
|------|------|------|
| `media_workflow` | 视频工作流标识 | `selfhost/video_animatediff_sd15.json` |
| `frame_template` | 视频模板路径 | `1080x1920/video_default.html` |
| `video_fps` | 视频帧率 | `24` (推荐 16-24) |
| `n_scenes` | 分镜数 | `3-5` (数越多效果越好但耗时越长) |

#### 前置条件与配置

为了使用 AnimateDiff，请确保以下条件满足：

1. **ComfyUI 已安装** 
   - 本地 ComfyUI 运行在 `http://127.0.0.1:8188`
   - 已安装 `ComfyUI-AnimateDiff-Evolved` 自定义节点

2. **模型文件已下载**
   - Stable Diffusion 1.5 检查点：`models/checkpoints/v1-5-pruned-emaonly.safetensors`
   - AnimateDiff 运动模块：`models/animatediff_models/mm_sd_v15_v2.ckpt`
   
   如果模型缺失，运行以下命令下载：
   
   ```powershell
   cd "d:\vscocde file\github-video-项目\Pixelle-Video"
   uv run python scripts/download_animatediff_models.ps1
   ```

3. **系统配置已完成**
   - LLM 已配置并测试通过
   - ComfyUI 连接已测试通过（点击"测试连接"）

#### 常见问题

**Q: 为什么我选择了"video"模板但看不到工作流选择器？**

A: 检查以下几点：
- 确保 ComfyUI 已启动并在 `http://127.0.0.1:8188` 可访问
- 浏览器刷新页面，重新选择"video"模板类型
- 查看浏览器开发者工具中的报错信息

**Q: 生成的视频为什么效果不好？**

A: 尝试以下优化方案：
- **增加分镜数**：从 3 分镜增加到 5-7 分镜，让 AI 有更多表达空间
- **改进提示词**：在"图像尺寸"下方修改"提示词前缀"，使用更具体的描述
- **调整帧率**：尝试 16fps 或 24fps，根据内容选择合适的速度
- **使用不同的模板**：尝试 `video_default.html` 等其他视频模板

**Q: AnimateDiff 和图片模板的区别是什么？**

A: 

| 特性 | 图片模板 | 视频模板（AnimateDiff） |
|------|--------|----------------------|
| 生成方式 | 每分镜生成一张静态图片 | 每分镜生成一段动画视频 |
| 视觉效果 | 分镜式、静态感 | 流畅、动画感、更生动 |
| 处理速度 | 快 | 中等（取决于分镜数和时长） |
| 文件大小 | 小 | 较大 |
| 适用场景 | 知识科普、信息呈现 | 故事叙述、产品演示、动画讲述 |

**Q: 我想用其他的 SD 模型（如 SD 2.1）或其他视频生成模型，怎么办？**

A: 

1. 在 ComfyUI 中安装对应的模型加载节点
2. 复制 `workflows/selfhost/video_animatediff_sd15.json` 为新文件
3. 修改 JSON 中的模型检查点和节点参数
4. 重启 Streamlit，新工作流会自动出现在工作流列表中

#### 故障排查

如果遇到"工作流不可用"或"节点缺失"的错误，可以运行验证脚本：

```powershell
cd "d:\vscocde file\github-video-项目\Pixelle-Video"
uv run python scripts/validate_animatediff_smoke.py
```

脚本会检查：
- ✅ ComfyUI 连接状态
- ✅ AnimateDiff 节点是否安装
- ✅ 所需模型文件是否存在
- ✅ 工作流 JSON 有效性

如有问题，脚本会给出具体的修复建议。


### 🎬 生成视频（右侧栏）

#### 生成按钮
- 配置好所有参数后，点击「🎬 生成视频」
- 会显示实时进度（生成文案 → 生成配图 → 合成语音 → 合成视频）
- 生成完成后自动显示视频预览

#### 进度显示
- 实时显示当前步骤
- 例如：「分镜 3/5 - 生成插图」

#### 视频预览
- 生成完成后自动播放
- 显示视频时长、文件大小、分镜数等信息
- 视频文件保存在 `output/` 文件夹


### ❓ 常见问题

**Q: 第一次使用需要多久？**  
A: 生成时长取决于视频分镜数量、网络状况和 AI 推理速度，通常几分钟内即可完成。

**Q: 视频效果不满意怎么办？**  
A: 可以尝试：
1. 更换 LLM 模型（不同模型文案风格不同）
2. 调整图像尺寸和提示词前缀（改变配图风格）
3. 更换 TTS 工作流或上传参考音频（改变语音效果）
4. 尝试不同的视频模板和尺寸

**Q: 费用大概多少？**  
A: **本项目完全支持免费运行！**

- **完全免费方案**: LLM 使用 Ollama（本地运行）+ ComfyUI 本地部署 = 0 元
- **推荐方案**: LLM 使用通义千问（成本极低，性价比高）+ ComfyUI 本地部署
- **云端方案**: LLM 使用 OpenAI + 图像使用 RunningHub（费用较高但无需本地环境）

**选择建议**：本地有显卡建议完全免费方案，否则推荐使用通义千问（性价比高）


## 🤝 参考项目

Pixelle-Video 的设计受到以下优秀开源项目的启发：

- [Pixelle-MCP](https://github.com/AIDC-AI/Pixelle-MCP) - ComfyUI MCP 服务器，让 AI 助手直接调用 ComfyUI
- [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) - 优秀的视频生成工具
- [NarratoAI](https://github.com/linyqh/NarratoAI) - 影视解说自动化工具
- [MoneyPrinterPlus](https://github.com/ddean2009/MoneyPrinterPlus) - 视频创作平台
- [ComfyKit](https://github.com/puke3615/ComfyKit) - ComfyUI 工作流封装库

感谢这些项目的开源精神！🙏


## 💬 社区交流

扫描下方二维码加入我们的社区，获取最新动态和技术支持：

| 微信群 | Discord 社区 |
| ---- | ---- |
| <img src="resources/wechat.png" alt="微信交流群" width="250" /> | <img src="resources/discord.png" alt="Discord 社区" width="250" /> |


## 📢 反馈与支持

- 🐛 **遇到问题**: 提交 [Issue](https://github.com/AIDC-AI/Pixelle-Video/issues)
- 💡 **功能建议**: 提交 [Feature Request](https://github.com/AIDC-AI/Pixelle-Video/issues)
- ⭐ **给个 Star**: 如果这个项目对你有帮助，欢迎给个 Star 支持一下！


## 📝 许可证

本项目采用 Apache 2.0 许可证，详情请查看 [LICENSE](LICENSE) 文件。


## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=AIDC-AI/Pixelle-Video&type=Date)](https://star-history.com/#AIDC-AI/Pixelle-Video&Date)

