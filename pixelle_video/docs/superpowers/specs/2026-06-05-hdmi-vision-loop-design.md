# HDMI 视觉闭环设计 (HDMI Vision Closed-Loop)

- 日期: 2026-06-05
- 状态: 已确认设计，待实现
- 关联文档: [docs/PHYSICAL_AUTOMATION_GUIDE.md](../../PHYSICAL_AUTOMATION_GUIDE.md)

## 背景与目标

`PHYSICAL_AUTOMATION_GUIDE.md` 方案分为两半：

1. **物理控制层**（CH9329 键鼠 + 局域网剪贴板中文输入）—— 已在
   `content_factory/domain/automation/ch9329/controller.py` 完整落地。
2. **HDMI 视觉闭环**（多路采集卡捕获 + OpenCV 模板匹配 + 看见界面加载成功才点下一步）
   —— 当前**几乎为 0**：全 `content_factory` 内无 `cv2`/`VideoCapture`/`matchTemplate`，
   `DeviceProfile` 无 `camera_index`，执行器无任何视觉验证步骤，
   `preview/checkpoint/select_media/set_cover` 均为空记录（no-op）。

本设计补齐第 2 半，让执行器从"纯盲操"升级为"看见界面再动作"的闭环，并为多路 HDMI
（每台手机绑定独立采集卡索引）打基础。

### 范围

完整闭环，一次交付：

- 采集卡捕获模块
- 模板匹配模块
- `DeviceProfile` 增加 `camera_index` 字段（多机绑定）
- 执行器新增三种视觉步骤类型
- 接入 `publish_worker`

## 关键决策（已确认）

| 决策点 | 选择 |
|---|---|
| 范围 | 完整闭环 |
| 无硬件/无 cv2/simulate 时降级 | **降级为通过**：视觉步骤记为 `succeeded` 且 `simulated=True`，不阻断流程（与现有 `tap`/`input_text` 一致） |
| 模板组织 | **按平台分目录**：`templates/<platform>/<name>.png`，步骤用 `template: xhs/album_tab` 引用 |
| 视觉步骤类型 | **全部三种**：`wait_for_element` + `verify_screen` + `click_on_match` |

## 架构

新增包 `content_factory/domain/automation/vision/`，四个聚焦单元：

### `capture.py` — `HDMICapture`

- 包裹 `cv2.VideoCapture(camera_index)`，**懒加载** cv2（模块顶层 `try import cv2`）。
- 构造时设 `CAP_PROP_FRAME_WIDTH=1280`、`CAP_PROP_FRAME_HEIGHT=720`（低分辨率降 CPU）。
- 属性 `available: bool` —— cv2 缺失或采集卡打不开时为 `False`。
- `read_frame() -> frame | None` —— 读不到返回 `None`，不抛异常。
- `release()` —— 释放资源。
- 设计约束：**任何底层失败都不抛**，只反映在 `available`/返回 `None` 上（贴合现有降级风格）。

### `matcher.py` — `TemplateMatcher`

- `match(frame, template_path, threshold=0.8) -> MatchResult`。
- `MatchResult` 字段：`matched: bool`、`confidence: float`、`center_x: int`、`center_y: int`、
  `frame_w: int`、`frame_h: int`。
- 实现：灰度化 + `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` + `minMaxLoc`，
  `max_val >= threshold` 即命中，中心 = `max_loc + (w//2, h//2)`。
- 懒加载 cv2/numpy；模板文件读不到时返回 `matched=False`。

### `templates.py`

- 解析步骤里的 `template: "<platform>/<name>"`（或 `"<platform>/<name>.png"`）
  → 绝对路径 `content_factory/domain/automation/templates/<platform>/<name>.png`。
- 模板根目录常量集中在此（便于测试覆盖/未来配置化）。
- 文件不存在返回 `None`（由调用方按降级语义处理）。

### `screen_vision.py` — `ScreenVision`

组合 capture + matcher 的门面，是执行器唯一依赖的视觉入口。

- 构造参数：`camera_index: int | None`、`platform: str`、`simulate: bool`。
- `available: bool` —— `not simulate and capture.available`。
- `wait_for(template, timeout=10.0, interval=0.5, threshold=0.8) -> VisionOutcome`
  —— 轮询读帧+匹配，命中即返回，超时返回未命中。
- `verify(template, threshold=0.8) -> VisionOutcome` —— 单次读帧+匹配。
- `VisionOutcome` 字段：`matched`、`confidence`、`x_ratio`、`y_ratio`、`simulated`。
  - **坐标换算**：HDMI 输出代表整块手机屏幕，故
    `x_ratio = center_x / frame_w`、`y_ratio = center_y / frame_h`，
    直接喂给 `CH9329Controller.click(x_ratio, y_ratio)`。
- `release()` 透传到 capture。
- **降级**：`available=False` 时 `wait_for`/`verify` 立即返回
  `VisionOutcome(matched=True, simulated=True, confidence=0.0, x_ratio=0, y_ratio=0)`。

## 执行器集成

`content_factory/domain/automation/ch9329/executor.py` 的 `CH9329Executor`：

- 构造新增可选参数 `vision: ScreenVision | None = None`。
- `_run_step` 新增三个分支：

| 步骤 type | 参数 | 行为 | 失败语义 |
|---|---|---|---|
| `wait_for_element` | `template`, `timeout`(默认10), `threshold`(默认0.8) | `vision.wait_for(...)` 轮询 | 真实模式且 `vision.available` 时超时未命中 → `status=failed` |
| `verify_screen` | `template`, `threshold` | `vision.verify(...)` 单次 | 未命中 → `failed` |
| `click_on_match` | `template`, `threshold` | 命中后用 `outcome.x_ratio/y_ratio` 调 `controller.click()` | 未命中 → `failed` |

- **降级为通过**：当 `self.simulate is True` 或 `vision is None` 或 `not vision.available`
  时，三种步骤均返回 `succeeded`、`detail.simulated=True`、不阻断。
- 失败 → 复用现有 `stop_on_failure` 机制：`publish_worker` 把 job 置 `paused`、
  记 `resume_from_step`、写 `ErrorRecord`，等人工检查后从该步续跑（无新增暂停机制）。
- 现有 `preview/select_media/set_cover/checkpoint/open_app` 保持 no-op，
  靠在 flow 中**穿插**视觉步骤来补盲点安全网。

## 设备表：`camera_index`

- `content_factory/domain/devices/models.py`：`DeviceProfile` 增
  `camera_index = Column(Integer, nullable=True)`。
- `content_factory/domain/devices/service.py`：`DeviceProfileInput` 增 `camera_index: int | None = None`，
  `register_device` 写入。
- `content_factory/app/api/routes_devices.py` + `schemas.py`：注册设备的请求体增 `camera_index`（可选）。
- **DB 迁移**：现有 SQLite 库不会因模型加列而自动加列。在 `content_factory/core/database.py`
  的建表初始化后，加一段**幂等迁移**：检查 `PRAGMA table_info(device_profiles)`，
  若无 `camera_index` 列则 `ALTER TABLE device_profiles ADD COLUMN camera_index INTEGER`。

## publish_worker 接线

`content_factory/workers/publish_worker.py` 的 `_resolve_executor`：

- 读 `device.camera_index`；构造 `ScreenVision(camera_index=..., platform=device.platform, simulate=self.simulate)`。
- 注入 `CH9329Executor(controller=..., vision=..., simulate=..., phone_ip=...)`。
- 无设备 / 无 `camera_index` → `vision=None`（执行器自动降级为通过）。
- `simulate` 标志透传，使 dry-run 下视觉步骤同样降级通过、保持确定性。

## 模板目录与参考流程

- 新建 `content_factory/domain/automation/templates/xhs/`，含 `.gitkeep` 与
  `README.md`（说明如何从采集卡画面裁剪模板小图、命名规范、阈值建议）。
- 给 `flows/xhs_upload.yaml` 与 `publish_worker.DEFAULT_FLOW_STEPS` 加 2~3 个参考视觉步骤，例如：
  - `open_app` 后：`wait_for_element: xhs/home_publish_btn`
  - 进入发布页后：`verify_screen: xhs/album_tab`
  - 保存草稿前：`verify_screen: xhs/publish_ready`
- 这些步骤在无模板/无 cv2/simulate 下全部降级通过，不影响现有 dry-run。

## 错误处理

- 视觉模块内部一律不向上抛硬件/依赖异常 —— 通过 `available=False` 与降级通过吸收。
- 视觉步骤"未命中"是**业务级失败**（非异常），走现有 `StepResult(status="failed")` →
  job 挂起 → 人工检查 → 续跑路径。
- 模板文件缺失：记为未命中并在 `detail` 里标注 `template_missing`，便于排查。

## 测试

- **执行器级（不依赖 cv2，注入 `FakeVision`）**：
  - `wait_for_element` 命中 → `succeeded`。
  - `wait_for_element` 超时未命中（`available=True`，真实模式）→ `failed`，job 经 `publish_worker` 置 `paused` 且 `resume_from_step` 正确。
  - `vision=None` 或 `available=False` → 降级 `succeeded`、`simulated=True`。
  - `click_on_match` 命中 → 以正确 `x_ratio/y_ratio` 调用 `controller.click`（用 stub controller 断言入参）。
- **`templates.py`**：`"xhs/album_tab"` / 带 `.png` / 不存在 三种路径解析单测。
- **`TemplateMatcher` / `HDMICapture`**：真匹配单测，在 cv2 不可用时 `pytest.importorskip` 自动跳过。
- **DB 迁移**：对旧结构（无 `camera_index`）的库执行初始化后，列存在且可写。

## 依赖

- `opencv-python` + `numpy` 作为**可选**依赖加入 requirements（注明 optional / 仅真实视觉模式需要）。
- 全部 cv2/numpy 调用懒加载，确保无 cv2 环境下导入与 dry-run 不受影响。

## 非目标 (YAGNI)

- 不做模板的按设备/分辨率覆盖（先一套按平台复用）。
- 不做实时多路画面预览 UI。
- 不重写 `select_media`/`set_cover` 为真实视觉文件选择（仍 no-op，靠穿插视觉步骤兜底）。
- 不引入新的暂停/续跑机制（复用现有 `stop_on_failure` + `resume_from_step`）。
