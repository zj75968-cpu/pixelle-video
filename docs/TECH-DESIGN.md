# TECH-DESIGN — 图文帖子流水线 + 小红书手机自动发布

**版本**: 1.0  
**日期**: 2026-05-03

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                     Web UI (Streamlit)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ 图文帖子页面  │  │  发布管理页面 │  │   现有视频页面       │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────────────────┘ │
└─────────┼────────────────┼────────────────────────────────────┘
          │ HTTP           │ HTTP
┌─────────▼────────────────▼────────────────────────────────────┐
│                    FastAPI Backend                              │
│  ┌────────────────────┐   ┌──────────────────────────────────┐ │
│  │  /post/* routers   │   │  /publish/* routers              │ │
│  └────────┬───────────┘   └──────────┬───────────────────────┘ │
│           │                          │                          │
│  ┌────────▼───────────┐   ┌──────────▼───────────────────────┐ │
│  │ImageTextPostPipeline│   │  PublishScheduler (APScheduler)  │ │
│  └────────┬───────────┘   └──────────┬───────────────────────┘ │
└──────────┼────────────────────────── ┼ ──────────────────────── ┘
           │                           │
    ┌──────▼──────┐            ┌────────▼──────────────┐
    │ ComfyUI /   │            │   ADB Manager          │
    │ 图片生成服务  │            │ (uiautomator2 + adb)   │
    └─────────────┘            └───────────┬────────────┘
                                           │ ADB (USB / WiFi)
                               ┌───────────▼────────────────┐
                               │   Android Devices           │
                               │  [Phone-1] [Phone-2] ...    │
                               └─────────────────────────────┘
```

---

## 2. 模块结构（新增文件）

```
pixelle_video/
  pipelines/
    image_text_post.py        # 新增：图文帖子流水线
  prompts/
    post_generation.py        # 新增：帖子文案生成提示词
  models/
    post.py                   # 新增：Post 数据模型

pixelle_video/publish/        # 新增：发布系统子包
  __init__.py
  adb_manager.py              # ADB 设备管理、图片推送
  xhs_publisher.py            # 小红书 UI 自动化操作
  scheduler.py                # APScheduler 队列管理
  models.py                   # PublishTask、DeviceConfig 模型

api/routers/
  post.py                     # 新增：图文帖子 API
  publish.py                  # 新增：发布管理 API

web/pages/
  3_📝_Post.py                # 新增：图文帖子 UI 页面
  4_📱_Publish.py             # 新增：发布管理 UI 页面
```

---

## 3. 图文帖子流水线

### 3.1 数据模型 (`pixelle_video/models/post.py`)

```python
@dataclass
class PostFrame:
    index: int
    image_prompt: str      # 英文图片提示词
    caption: str           # 该帧对应的中文说明（可选叠字）
    image_path: Optional[Path] = None

@dataclass
class PostContent:
    title: str             # 标题 ≤20 字
    body: str              # 正文 150-500 字
    hashtags: List[str]    # 话题标签，不含 #
    frames: List[PostFrame]

@dataclass
class PostGenerationResult:
    task_id: str
    output_dir: Path
    content: PostContent
    created_at: datetime
```

### 3.2 流水线步骤 (`ImageTextPostPipeline`)

| 步骤 | 方法 | 输入 | 输出 |
|------|------|------|------|
| 1 | `generate_post_content` | topic, params | `PostContent` |
| 2 | `generate_images` | `PostContent.frames` | 图片文件路径 |
| 3 | `save_post_json` | `PostContent` | `post.json` |
| 4 | `render_preview` | 图片 + 文案 | `post_preview.html` |

### 3.3 LLM 提示词结构（`post_generation.py`）

LLM 单次返回 JSON：
```json
{
  "title": "...",
  "body": "...",
  "hashtags": ["减肥餐", "健康饮食", ...],
  "frames": [
    { "image_prompt": "...(English)", "caption": "...(Chinese)" },
    ...
  ]
}
```

---

## 4. 手机自动发布系统

### 4.1 依赖

| 库 | 用途 | 安装 |
|----|------|------|
| `uiautomator2` | Android UI 自动化 | `pip install uiautomator2` |
| `APScheduler` | 发布队列调度 | `pip install apscheduler` |
| `adb` (系统) | 文件推送、设备管理 | 系统 PATH 中有 `adb` 命令 |

### 4.2 ADB 管理器 (`adb_manager.py`)

```python
class ADBManager:
    def list_devices() -> List[DeviceInfo]
    def connect_wifi(host: str, port: int = 5555) -> bool
    def push_images(serial: str, images: List[Path], dest_dir: str) -> bool
    def scan_media(serial: str, paths: List[str]) -> None
    def take_screenshot(serial: str) -> bytes
```

**图片推送流程：**
1. `adb -s <serial> push <local_img> /sdcard/DCIM/XhsAuto/<task_id>/`
2. `adb -s <serial> shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/XhsAuto/<task_id>/`
3. 等待 2 秒让媒体库扫描完成

### 4.3 小红书发布器 (`xhs_publisher.py`)

基于 `uiautomator2`，操作流程：

```
1. u2.connect(serial)
2. d.app_start("com.xingin.xhs")
3. 等待首页加载（等 "+"按钮可点击）
4. d(description="+").click()
5. d(text="图文").click()
6. 选相册 → 滑动到 XhsAuto 目录 → 按顺序选图
7. d(resourceId="...title_input").set_text(title)
8. d(resourceId="...content_input").set_text(body)
9. d(text="发布").click()
10. 等待跳回首页，截图
```

> **风险**：小红书 UI 元素 resourceId 可能随版本变化，需维护一个版本适配表（`xhs_ui_selectors.yaml`）。

### 4.4 调度器 (`scheduler.py`)

```python
class PublishScheduler:
    # 使用 APScheduler BackgroundScheduler
    def enqueue(task: PublishTask) -> str          # 返回 task_id
    def cancel(task_id: str) -> bool
    def list_tasks() -> List[PublishTask]
    def _execute_task(task: PublishTask) -> None    # 内部：调 xhs_publisher
```

**PublishTask 模型：**
```python
@dataclass
class PublishTask:
    task_id: str
    device_serial: str
    post_output_dir: Path
    scheduled_time: datetime
    status: Literal["pending", "running", "done", "failed"]
    retry_count: int = 0
    last_error: Optional[str] = None
    screenshot_path: Optional[Path] = None
```

**持久化**：任务列表 JSON 持久化到 `data/publish_queue.json`，服务重启后恢复未完成任务。

---

## 5. API 路由设计

### 5.1 图文帖子 (`/post`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/post/generate` | 创建图文帖子生成任务 |
| GET | `/post/{task_id}` | 获取任务状态/结果 |
| GET | `/post/{task_id}/preview` | 返回 HTML 预览 |

### 5.2 发布管理 (`/publish`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/publish/devices` | 列出 ADB 设备 |
| POST | `/publish/devices/connect` | WiFi ADB 连接 |
| GET | `/publish/devices/{serial}/config` | 获取设备配置 |
| PUT | `/publish/devices/{serial}/config` | 更新设备配置 |
| POST | `/publish/tasks` | 创建发布任务 |
| GET | `/publish/tasks` | 列出所有任务 |
| DELETE | `/publish/tasks/{task_id}` | 取消待执行任务 |
| GET | `/publish/tasks/{task_id}/screenshot` | 获取发布截图 |

---

## 6. 设备配置文件

配置存储在 `data/devices.json`：

```json
{
  "devices": {
    "emulator-5554": {
      "alias": "主号-美食",
      "default_topic": "家常菜食谱",
      "min_interval_minutes": 30,
      "daily_post_limit": 5
    }
  }
}
```

---

## 7. 安全与风险

| 风险 | 等级 | 缓解措施 |
|------|------|--------|
| 小红书 UI 变更导致发布失败 | 高 | `xhs_ui_selectors.yaml` 版本配置，失败截图便于排查 |
| ADB 未授权 | 中 | 首次连接需在手机确认授权，文档说明 |
| 账号发帖频率被限制 | 中 | 可配置发帖间隔和每日上限，默认保守值 |
| 任务积压导致重复发布 | 中 | 任务状态持久化，重启恢复时跳过已完成任务 |
| 图片文件占满手机存储 | 低 | 发布成功后自动删除 `/sdcard/DCIM/XhsAuto/` 临时目录 |

---

## 8. 技术选型摘要

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Android 自动化 | uiautomator2 | Python 原生、无需额外服务进程、成熟的小红书自动化案例 |
| 任务调度 | APScheduler | 项目已有 FastAPI，APScheduler 可内嵌，无需独立 Celery |
| 队列持久化 | JSON 文件 | 任务量小（<100），无需 Redis；重启可恢复 |
| 图片预览 | 静态 HTML | 简单可靠，浏览器直接打开，无额外依赖 |
