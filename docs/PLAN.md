# PLAN — 图文帖子 + 小红书自动发布

**版本**: 1.0  
**日期**: 2026-05-03  
**参考**: [PRD.md](PRD.md) · [TECH-DESIGN.md](TECH-DESIGN.md)

---

## 阶段划分

```
Phase 1：图文帖子流水线（后端 + API）      ~3-4天
Phase 2：图文帖子 Web UI                  ~1-2天
Phase 3：ADB 设备管理（后端 + API）        ~2-3天
Phase 4：小红书 UI 自动化（发布器）         ~3-4天
Phase 5：发布队列调度                      ~1-2天
Phase 6：发布管理 Web UI                  ~2-3天
Phase 7：集成测试 + 文档                   ~1天
```

---

## Phase 1 — 图文帖子流水线（后端核心）

### Task 1.1 — Post 数据模型

**目标**: 创建 `pixelle_video/models/post.py`  
**依赖**: 无  
**并行**: 可与 Task 1.2 并行  
**验收**:
- `PostFrame`、`PostContent`、`PostGenerationResult` dataclass 可正确导入
- 字段类型和默认值符合 TECH-DESIGN 第 3.1 节

---

### Task 1.2 — 帖子文案提示词

**目标**: 创建 `pixelle_video/prompts/post_generation.py`  
**内容**: 
- `POST_GENERATION_SYSTEM_PROMPT`
- `build_post_prompt(topic, image_count, post_tone, hashtag_count) -> str`
- 要求 LLM 返回规定 JSON 结构
**并行**: 可与 Task 1.1 并行  
**验收**: 传入主题，prompt 生成正确；JSON schema 符合 TECH-DESIGN 第 3.3 节

---

### Task 1.3 — 图文帖子流水线

**目标**: 创建 `pixelle_video/pipelines/image_text_post.py`，实现 `ImageTextPostPipeline`  
**依赖**: Task 1.1, 1.2  
**流程**:
1. `generate_post_content` → 调用 LLM，解析 JSON，返回 `PostContent`
2. `generate_images` → 并行调用现有图片生成服务（复用 `standard.py` 中的生成逻辑）
3. `save_post_json` → 写 `post.json`
4. `render_preview` → 写 `post_preview.html`（内嵌简单轮播 JS）

**验收**:
- 调用流水线后，`output/{task_id}/images/` 下有 N 张图
- `post.json` 包含 `title`、`body`、`hashtags`、`created_at`
- `post_preview.html` 在浏览器打开可正常展示

---

### Task 1.4 — Post API 路由

**目标**: 创建 `api/routers/post.py`，注册到 `api/app.py`  
**端点**:
- `POST /post/generate`（异步任务，返回 task_id）
- `GET /post/{task_id}`（查询状态）
- `GET /post/{task_id}/preview`（返回 HTML）

**依赖**: Task 1.3  
**验收**: curl 调用三个接口均返回正确响应

---

## Phase 2 — 图文帖子 Web UI

### Task 2.1 — 图文帖子页面

**目标**: 创建 `web/pages/3_📝_Post.py`  
**UI 元素**:
- 主题输入框
- 图片数量滑块（3-9）
- 文案风格下拉框（干货/种草/故事/清单）
- 图片风格输入框（可选）
- 「生成帖子」按钮
- 进度条（复用现有 progress 组件）
- 结果区：展示图片网格 + 标题正文 + 话题标签
- 复制文案按钮

**依赖**: Task 1.4  
**验收**: 页面能完整走通一次图文帖子生成流程

---

## Phase 3 — ADB 设备管理

### Task 3.1 — 安装依赖

**目标**: 在 `requirements.txt` / `pyproject.toml` 添加：
- `uiautomator2>=3.0`
- `apscheduler>=3.10`

**验收**: `pip install` 无报错，`import uiautomator2` 成功

---

### Task 3.2 — ADB 管理器

**目标**: 创建 `pixelle_video/publish/adb_manager.py`  
**实现**:
- `list_devices()` — 调用 `adb devices` 解析输出
- `connect_wifi(host, port)` — 调用 `adb connect`
- `push_images(serial, images, dest_dir)` — adb push + 媒体扫描
- `take_screenshot(serial)` — `adb exec-out screencap -p`

**验收**:
- 单元测试（mock subprocess）验证 adb 命令格式正确
- 接真机测试 `list_devices()` 返回正确序列号

---

### Task 3.3 — 设备配置持久化

**目标**: 创建 `pixelle_video/publish/device_config.py`  
**内容**:
- `DeviceConfig` dataclass
- `DeviceConfigStore`：读写 `data/devices.json`

**验收**: 保存后重启服务，配置数据不丢失

---

### Task 3.4 — 发布管理 API（设备部分）

**目标**: 创建 `api/routers/publish.py`（设备管理端点）  
**端点**:
- `GET /publish/devices`
- `POST /publish/devices/connect`
- `GET /publish/devices/{serial}/config`
- `PUT /publish/devices/{serial}/config`

**依赖**: Task 3.2, 3.3  
**验收**: 接真机，curl 调用设备列表接口返回正确数据

---

## Phase 4 — 小红书 UI 自动化

### Task 4.1 — UI 选择器配置文件

**目标**: 创建 `pixelle_video/publish/xhs_ui_selectors.yaml`  
**内容**: 小红书各版本的 UI 元素 resourceId / description / text  
**格式**:
```yaml
default:
  home_create_btn:
    description: "+"
  post_type_image_text:
    text: "图文"
  title_input:
    resourceId: "com.xingin.xhs:id/..."
  ...
```

**验收**: yaml 文件可被 Python 正常加载

---

### Task 4.2 — 小红书发布器（核心）

**目标**: 创建 `pixelle_video/publish/xhs_publisher.py`  
**实现** `XhsPublisher.publish(serial, post_dir, post_json)`:
1. u2 连接设备
2. 启动小红书
3. 按 TECH-DESIGN 第 4.3 节流程操作 UI
4. 完成后截图、删除临时图片

**依赖**: Task 3.2, 4.1  
**验收**:
- 接真机，手动执行发布一篇帖子，全流程无需人工干预
- 截图文件正确保存

---

## Phase 5 — 发布队列调度

### Task 5.1 — 调度器

**目标**: 创建 `pixelle_video/publish/scheduler.py`  
**实现**:
- `PublishTask` dataclass（参见 TECH-DESIGN 第 4.4 节）
- `PublishScheduler`：APScheduler + JSON 持久化队列
- 支持 `enqueue`、`cancel`、`list_tasks`
- 失败自动重试 3 次

**依赖**: Task 4.2  
**验收**:
- 加入队列的任务在计划时间自动执行
- 服务重启后，`pending` 任务恢复执行，`done/failed` 任务状态保留

---

### Task 5.2 — 发布管理 API（任务部分）

**目标**: 在 `api/routers/publish.py` 添加任务端点  
**端点**:
- `POST /publish/tasks`
- `GET /publish/tasks`
- `DELETE /publish/tasks/{task_id}`
- `GET /publish/tasks/{task_id}/screenshot`

**依赖**: Task 5.1  
**验收**: curl 创建任务后，队列中能看到该任务

---

## Phase 6 — 发布管理 Web UI

### Task 6.1 — 发布管理页面

**目标**: 创建 `web/pages/4_📱_Publish.py`  
**UI 区域**:
1. **设备列表** — 卡片展示：序列号、备注名、状态、配置按钮
2. **WiFi 连接** — 输入 IP:Port，点击连接
3. **发布任务创建** — 选帖子（已生成的）、选设备、选发布时间
4. **任务队列** — 表格展示：状态、计划时间、设备、帖子标题、操作
5. **发布截图** — 点击任务查看截图

**依赖**: Task 5.2  
**验收**: UI 能完整走通「添加设备 → 选择帖子 → 定时发布 → 查看结果」流程

---

## Phase 7 — 集成测试 + 文档

### Task 7.1 — 端到端集成测试

**目标**: 用两台手机执行完整流程：  
主题输入 → 图文帖子生成 → 分配到不同设备 → 定时发布 → 截图确认

**验收**: 两台手机均成功发布，无错误日志

---

### Task 7.2 — 文档更新

**目标**:
- 更新 `README.md` 添加图文帖子和自动发布功能说明
- 在 `docs/` 添加 ADB 准备指南（开启开发者模式、授权 ADB）
- 在 `docs/` 添加自动发布使用指南

**验收**: 文档步骤可被新用户独立跟随执行

---

## 任务依赖图

```
1.1 ─┐
1.2 ─┤─→ 1.3 → 1.4 → 2.1
     │
3.1 ─┤
3.2 ─┤─→ 3.4
3.3 ─┘
          ↓
     3.2 + 4.1 → 4.2 → 5.1 → 5.2 → 6.1 → 7.1 → 7.2
```

---

## 当前非目标（提醒）

- iOS 设备
- 视频帖子自动发布
- 账号注册/登录自动化
- 多平台（抖音、微博）
- 数据回收（点赞/评论统计）
