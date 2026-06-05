# HDMI 视觉闭环 实现计划 (HDMI Vision Closed-Loop)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 content_factory 补齐 HDMI 采集卡 + OpenCV 模板匹配的视觉闭环，让 CH9329 执行器从「盲操」升级为「看见界面再动作」，并支持多机各绑定独立采集卡索引。

**Architecture:** 新增 `content_factory/domain/automation/vision/` 包（capture / matcher / templates / screen_vision 四个聚焦单元）。执行器注入一个 `ScreenVision` 门面，新增 `wait_for_element` / `verify_screen` / `click_on_match` 三种步骤。所有 cv2/numpy 调用懒加载；simulate 或视觉不可用时三种步骤「降级为通过」。`DeviceProfile` 增 `camera_index`，由 publish_worker 构造对应 `ScreenVision` 注入执行器。

**Tech Stack:** Python 3, FastAPI, SQLAlchemy(SQLite), pytest；可选依赖 opencv-python + numpy（懒加载）。

**约定：所有命令在仓库根目录 `f:/codex project/小红书/pixelle_video` 下执行，统一用 venv 解释器 `.venv/Scripts/python.exe`。**

---

## 文件结构

新增/修改：

- 新建 `content_factory/domain/automation/vision/__init__.py`
- 新建 `content_factory/domain/automation/vision/templates.py` — 模板引用→路径解析
- 新建 `content_factory/domain/automation/vision/matcher.py` — `TemplateMatcher` + `MatchResult`
- 新建 `content_factory/domain/automation/vision/capture.py` — `HDMICapture`（懒加载 cv2）
- 新建 `content_factory/domain/automation/vision/screen_vision.py` — `ScreenVision` + `VisionOutcome` 门面
- 修改 `content_factory/domain/automation/ch9329/executor.py` — 注入 vision + 三种步骤
- 修改 `content_factory/domain/devices/models.py` — `DeviceProfile.camera_index`
- 修改 `content_factory/domain/devices/service.py` — `DeviceProfileInput.camera_index` + 写入
- 修改 `content_factory/app/api/schemas.py` — 请求/响应增 `camera_index`
- 修改 `content_factory/app/api/routes_devices.py` — 透传 `camera_index`
- 修改 `content_factory/workers/publish_worker.py` — 按 `camera_index` 构造 `ScreenVision` 注入
- 修改 `content_factory/domain/automation/flows/xhs_upload.yaml` — 穿插参考视觉步骤
- 新建 `content_factory/domain/automation/templates/xhs/.gitkeep`
- 新建 `content_factory/domain/automation/templates/README.md` — 模板采集说明
- 新建 `content_factory/requirements-optional.txt` — opencv-python + numpy
- 新建测试 `content_factory/tests/__init__.py`、`content_factory/tests/conftest.py`
- 新建测试 `content_factory/tests/test_vision_templates.py`
- 新建测试 `content_factory/tests/test_vision_screen.py`
- 新建测试 `content_factory/tests/test_executor_vision.py`
- 新建测试 `content_factory/tests/test_devices_camera_index.py`
- 新建测试 `content_factory/tests/test_publish_worker_vision.py`

---

## Task 0: 测试环境与目录骨架

**Files:**
- Create: `content_factory/tests/__init__.py`
- Create: `content_factory/tests/conftest.py`
- Create: `content_factory/requirements-optional.txt`

- [ ] **Step 1: 确认/安装 pytest 到 venv**

Run:
```bash
.venv/Scripts/python.exe -m pytest --version || .venv/Scripts/python.exe -m pip install pytest
```
Expected: 打印 pytest 版本（若未安装则先安装再打印）。

- [ ] **Step 2: 建测试包入口**

Create `content_factory/tests/__init__.py`（空文件）：
```python
```

- [ ] **Step 3: 建 conftest（临时 SQLite 会话 fixture）**

Create `content_factory/tests/conftest.py`:
```python
from __future__ import annotations

import pytest

from content_factory.core import database


@pytest.fixture
def db_session(tmp_path):
    """Fresh file-backed SQLite session with the full schema migrated."""
    url = f"sqlite:///{(tmp_path / 'cf_test.sqlite').as_posix()}"
    database.init_database(url)
    database.create_all_tables()
    database.migrate_missing_columns()
    assert database._SessionLocal is not None  # initialized by init_database
    session = database._SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
```

- [ ] **Step 4: 建可选依赖清单**

Create `content_factory/requirements-optional.txt`:
```text
# Optional: only required for the real HDMI vision closed-loop (simulate=False).
# All cv2/numpy usage is lazy-imported; the pipeline runs without these.
opencv-python>=4.8
numpy>=1.24
```

- [ ] **Step 5: 验证 conftest 可被收集**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests -q
```
Expected: `no tests ran`（或 collected 0 items），无 import 错误。

- [ ] **Step 6: Commit**

```bash
git add content_factory/tests/__init__.py content_factory/tests/conftest.py content_factory/requirements-optional.txt
git commit -m "test: scaffold content_factory vision test harness"
```

---

## Task 1: 模板路径解析 (templates.py)

**Files:**
- Create: `content_factory/domain/automation/vision/__init__.py`
- Create: `content_factory/domain/automation/vision/templates.py`
- Test: `content_factory/tests/test_vision_templates.py`

- [ ] **Step 1: 写失败测试**

Create `content_factory/tests/test_vision_templates.py`:
```python
from __future__ import annotations

from content_factory.domain.automation.vision.templates import resolve_template


def test_resolve_returns_none_for_empty():
    assert resolve_template(None) is None
    assert resolve_template("") is None


def test_resolve_existing_template(tmp_path):
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    target = root / "xhs" / "album_tab.png"
    target.write_bytes(b"x")
    # both "xhs/album_tab" and "xhs/album_tab.png" resolve to the same file
    assert resolve_template("xhs/album_tab", root=root) == target
    assert resolve_template("xhs/album_tab.png", root=root) == target


def test_resolve_missing_returns_none(tmp_path):
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    assert resolve_template("xhs/nope", root=root) is None
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_templates.py -v
```
Expected: FAIL（ModuleNotFoundError: ...vision.templates）。

- [ ] **Step 3: 建包入口**

Create `content_factory/domain/automation/vision/__init__.py`（空文件）：
```python
```

- [ ] **Step 4: 实现 templates.py**

Create `content_factory/domain/automation/vision/templates.py`:
```python
from __future__ import annotations

from pathlib import Path

# templates live at content_factory/domain/automation/templates/<platform>/<name>.png
TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


def resolve_template(ref: str | None, root: Path | None = None) -> Path | None:
    """Resolve a "<platform>/<name>" template reference to an existing file path.

    Returns None when ref is empty or the file does not exist, so callers can
    apply the degrade-to-pass / template_missing semantics uniformly.
    """
    if not ref:
        return None
    base = root or TEMPLATES_ROOT
    name = ref if ref.endswith(".png") else f"{ref}.png"
    path = base / name
    return path if path.exists() else None
```

- [ ] **Step 5: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_templates.py -v
```
Expected: PASS（3 个用例）。

- [ ] **Step 6: Commit**

```bash
git add content_factory/domain/automation/vision/__init__.py content_factory/domain/automation/vision/templates.py content_factory/tests/test_vision_templates.py
git commit -m "feat: add vision template path resolver"
```

---

## Task 2: 模板匹配器 (matcher.py)

**Files:**
- Create: `content_factory/domain/automation/vision/matcher.py`
- Test: 复用 `content_factory/tests/test_vision_screen.py`（Task 3 建）；本任务只加 cv2-gated 冒烟测试

**说明：** cv2/numpy 在当前 venv 未安装，真匹配测试用 `pytest.importorskip` 自动跳过。`MatchResult` 与匹配逻辑无需 cv2 即可定义（cv2 在方法内懒加载）。

- [ ] **Step 1: 写 cv2-gated 测试**

Create `content_factory/tests/test_vision_matcher.py`:
```python
from __future__ import annotations

from content_factory.domain.automation.vision.matcher import MatchResult, TemplateMatcher


def test_match_result_dataclass_fields():
    r = MatchResult(matched=True, confidence=0.9, center_x=10, center_y=20, frame_w=100, frame_h=200)
    assert r.matched and r.center_x == 10 and r.frame_h == 200


def test_match_finds_template_when_cv2_available(tmp_path):
    cv2 = __import__("pytest").importorskip("cv2")
    np = __import__("pytest").importorskip("numpy")
    # white frame with a black 20x20 square at (40,60)
    frame = np.full((200, 100, 3), 255, dtype=np.uint8)
    frame[60:80, 40:60] = 0
    tpl_path = tmp_path / "sq.png"
    cv2.imwrite(str(tpl_path), frame[60:80, 40:60])
    r = TemplateMatcher().match(frame, tpl_path, threshold=0.8)
    assert r.matched is True
    assert 40 <= r.center_x <= 60
    assert 60 <= r.center_y <= 80
    assert r.frame_w == 100 and r.frame_h == 200
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_matcher.py -v
```
Expected: FAIL（ModuleNotFoundError: ...vision.matcher）。

- [ ] **Step 3: 实现 matcher.py**

Create `content_factory/domain/automation/vision/matcher.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MatchResult:
    matched: bool
    confidence: float
    center_x: int
    center_y: int
    frame_w: int
    frame_h: int


class TemplateMatcher:
    """Locate a template image inside a captured frame via OpenCV.

    cv2/numpy are imported lazily so importing this module never requires them.
    """

    def match(self, frame: Any, template_path: Path, threshold: float = 0.8) -> MatchResult:
        import cv2  # lazy: only needed for real vision

        h_frame, w_frame = frame.shape[:2]
        template = cv2.imread(str(template_path), 0)
        if template is None:
            return MatchResult(False, 0.0, 0, 0, w_frame, h_frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        th, tw = template.shape[:2]
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            return MatchResult(
                True, float(max_val), max_loc[0] + tw // 2, max_loc[1] + th // 2, w_frame, h_frame
            )
        return MatchResult(False, float(max_val), 0, 0, w_frame, h_frame)
```

- [ ] **Step 4: 运行确认通过（或跳过）**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_matcher.py -v
```
Expected: 第 1 个用例 PASS；第 2 个 PASS 或 SKIPPED（cv2 未装时 skip）。整体非 FAIL。

- [ ] **Step 5: Commit**

```bash
git add content_factory/domain/automation/vision/matcher.py content_factory/tests/test_vision_matcher.py
git commit -m "feat: add OpenCV template matcher"
```

---

## Task 3: 采集卡 (capture.py) 与视觉门面 (screen_vision.py)

**Files:**
- Create: `content_factory/domain/automation/vision/capture.py`
- Create: `content_factory/domain/automation/vision/screen_vision.py`
- Test: `content_factory/tests/test_vision_screen.py`

- [ ] **Step 1: 写失败测试（注入 fake capture/matcher，不依赖 cv2）**

Create `content_factory/tests/test_vision_screen.py`:
```python
from __future__ import annotations

from content_factory.domain.automation.vision.matcher import MatchResult
from content_factory.domain.automation.vision.screen_vision import ScreenVision, VisionOutcome


class _FakeCapture:
    def __init__(self, frames):
        self._frames = list(frames)
        self.available = True
        self.released = False

    def read_frame(self):
        return self._frames.pop(0) if self._frames else None

    def release(self):
        self.released = True


class _FakeMatcher:
    def __init__(self, result):
        self._result = result

    def match(self, frame, template_path, threshold=0.8):
        return self._result


def _vision(result, frames=("frame",), simulate=False):
    return ScreenVision(
        camera_index=0,
        platform="xhs",
        simulate=simulate,
        capture=_FakeCapture(frames),
        matcher=_FakeMatcher(result),
    )


def test_unavailable_when_simulate():
    v = ScreenVision(camera_index=0, platform="xhs", simulate=True)
    assert v.available is False
    out = v.verify("xhs/album_tab")
    assert out.matched is True and out.simulated is True


def test_verify_match_maps_ratio(tmp_path, monkeypatch):
    # template must resolve to an existing file
    root = tmp_path / "templates"
    (root / "xhs").mkdir(parents=True)
    (root / "xhs" / "album_tab.png").write_bytes(b"x")
    monkeypatch.setattr(
        "content_factory.domain.automation.vision.screen_vision.resolve_template",
        lambda ref, root=None: (root and None) or (tmp_path / "templates" / "xhs" / "album_tab.png"),
    )
    result = MatchResult(True, 0.95, center_x=50, center_y=100, frame_w=100, frame_h=200)
    v = _vision(result)
    out = v.verify("xhs/album_tab")
    assert out.matched is True
    assert out.x_ratio == 0.5 and out.y_ratio == 0.5
    assert out.simulated is False


def test_template_missing_reports_reason():
    v = _vision(MatchResult(False, 0.0, 0, 0, 100, 200))
    out = v.verify("xhs/does_not_exist")
    assert out.matched is False and out.reason == "template_missing"


def test_wait_for_times_out(monkeypatch, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    monkeypatch.setattr(
        "content_factory.domain.automation.vision.screen_vision.resolve_template",
        lambda ref, root=None: p,
    )
    v = _vision(MatchResult(False, 0.1, 0, 0, 100, 200), frames=("f1",))
    out = v.wait_for("xhs/x", timeout=0.0, interval=0.0)
    assert out.matched is False and out.reason in ("timeout", "no_frame")
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_screen.py -v
```
Expected: FAIL（ModuleNotFoundError: ...vision.screen_vision）。

- [ ] **Step 3: 实现 capture.py**

Create `content_factory/domain/automation/vision/capture.py`:
```python
from __future__ import annotations

from typing import Any

try:  # pragma: no cover - import guard
    import cv2  # type: ignore
except Exception:  # pragma: no cover - cv2 not installed
    cv2 = None  # type: ignore


class HDMICapture:
    """Read frames from a UVC HDMI capture card via OpenCV.

    Never raises on hardware/dependency problems; failures surface as
    ``available=False`` / ``read_frame()`` returning None.
    """

    def __init__(self, camera_index: int, width: int = 1280, height: int = 720):
        self.camera_index = camera_index
        self._cap: Any = None
        self.available = False
        if cv2 is None:
            return
        try:
            cap = cv2.VideoCapture(camera_index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if cap.isOpened():
                self._cap = cap
                self.available = True
            else:
                cap.release()
        except Exception:
            self._cap = None
            self.available = False

    def read_frame(self) -> Any:
        if not self.available or self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
            return frame if ok else None
        except Exception:
            return None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self.available = False
```

- [ ] **Step 4: 实现 screen_vision.py**

Create `content_factory/domain/automation/vision/screen_vision.py`:
```python
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from content_factory.domain.automation.vision.capture import HDMICapture
from content_factory.domain.automation.vision.matcher import TemplateMatcher
from content_factory.domain.automation.vision.templates import resolve_template


@dataclass
class VisionOutcome:
    matched: bool
    confidence: float = 0.0
    x_ratio: float = 0.0
    y_ratio: float = 0.0
    simulated: bool = False
    reason: str | None = None


class ScreenVision:
    """Facade combining a capture source and a template matcher.

    When ``simulate`` is True or no capture device is available, ``verify`` and
    ``wait_for`` short-circuit to a matched/simulated outcome (degrade-to-pass).
    """

    def __init__(
        self,
        camera_index: int | None,
        platform: str = "xhs",
        simulate: bool = True,
        capture: Any = None,
        matcher: Any = None,
    ):
        self.platform = platform
        self.simulate = simulate
        self._matcher = matcher or TemplateMatcher()
        if capture is not None:
            self._capture = capture
        elif simulate or camera_index is None:
            self._capture = None
        else:
            self._capture = HDMICapture(camera_index)

    @property
    def available(self) -> bool:
        return bool(
            not self.simulate
            and self._capture is not None
            and getattr(self._capture, "available", False)
        )

    def _check_once(self, template_ref: str | None, threshold: float) -> VisionOutcome:
        path = resolve_template(template_ref)
        if path is None:
            return VisionOutcome(matched=False, reason="template_missing")
        frame = self._capture.read_frame()
        if frame is None:
            return VisionOutcome(matched=False, reason="no_frame")
        r = self._matcher.match(frame, path, threshold)
        x_ratio = (r.center_x / r.frame_w) if r.frame_w else 0.0
        y_ratio = (r.center_y / r.frame_h) if r.frame_h else 0.0
        return VisionOutcome(
            matched=r.matched, confidence=r.confidence, x_ratio=x_ratio, y_ratio=y_ratio
        )

    def verify(self, template_ref: str | None, threshold: float = 0.8) -> VisionOutcome:
        if not self.available:
            return VisionOutcome(matched=True, simulated=True)
        return self._check_once(template_ref, threshold)

    def wait_for(
        self,
        template_ref: str | None,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = 0.8,
    ) -> VisionOutcome:
        if not self.available:
            return VisionOutcome(matched=True, simulated=True)
        deadline = time.monotonic() + timeout
        last = VisionOutcome(matched=False, reason="timeout")
        while True:
            last = self._check_once(template_ref, threshold)
            if last.matched:
                return last
            if time.monotonic() >= deadline:
                if last.reason is None:
                    last.reason = "timeout"
                return last
            time.sleep(interval)

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
```

- [ ] **Step 5: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_vision_screen.py -v
```
Expected: PASS（4 个用例）。

- [ ] **Step 6: Commit**

```bash
git add content_factory/domain/automation/vision/capture.py content_factory/domain/automation/vision/screen_vision.py content_factory/tests/test_vision_screen.py
git commit -m "feat: add HDMI capture and ScreenVision facade"
```

---

## Task 4: 执行器视觉步骤 (executor.py)

**Files:**
- Modify: `content_factory/domain/automation/ch9329/executor.py`
- Test: `content_factory/tests/test_executor_vision.py`

- [ ] **Step 1: 写失败测试（FakeVision + stub controller，不依赖硬件）**

Create `content_factory/tests/test_executor_vision.py`:
```python
from __future__ import annotations

from content_factory.domain.automation.ch9329.executor import CH9329Executor
from content_factory.domain.automation.vision.screen_vision import VisionOutcome


class _StubController:
    def __init__(self):
        self.clicks = []
        self.screen_width = 1080
        self.screen_height = 2400

    def connect(self):
        return True

    def disconnect(self):
        return None

    def click(self, x_ratio, y_ratio):
        self.clicks.append((x_ratio, y_ratio))
        return True


class _FakeVision:
    def __init__(self, outcome, available=True):
        self._outcome = outcome
        self.available = available
        self.released = False

    def wait_for(self, template_ref, timeout=10.0, interval=0.5, threshold=0.8):
        return self._outcome

    def verify(self, template_ref, threshold=0.8):
        return self._outcome

    def release(self):
        self.released = True


def _executor(vision, simulate=False):
    return CH9329Executor(controller=_StubController(), simulate=simulate, vision=vision)


def test_wait_for_element_match_succeeds():
    ex = _executor(_FakeVision(VisionOutcome(matched=True, confidence=0.9)))
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["matched"] is True


def test_wait_for_element_timeout_fails():
    ex = _executor(_FakeVision(VisionOutcome(matched=False, reason="timeout")))
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "failed"


def test_vision_unavailable_degrades_to_pass():
    ex = _executor(_FakeVision(VisionOutcome(matched=False), available=False))
    res = ex.execute_flow([{"type": "verify_screen", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["simulated"] is True


def test_simulate_degrades_to_pass_without_vision():
    ex = CH9329Executor(controller=_StubController(), simulate=True, vision=None)
    res = ex.execute_flow([{"type": "wait_for_element", "template": "xhs/x"}], {})
    assert res[0].status == "succeeded"
    assert res[0].detail["simulated"] is True


def test_click_on_match_clicks_center_ratio():
    ctrl = _StubController()
    vision = _FakeVision(VisionOutcome(matched=True, confidence=0.9, x_ratio=0.5, y_ratio=0.25))
    ex = CH9329Executor(controller=ctrl, simulate=False, vision=vision)
    res = ex.execute_flow([{"type": "click_on_match", "template": "xhs/btn"}], {})
    assert res[0].status == "succeeded"
    assert ctrl.clicks == [(0.5, 0.25)]
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_executor_vision.py -v
```
Expected: FAIL（CH9329Executor 不接受 `vision` 关键字 / 步骤未支持）。

- [ ] **Step 3: 给执行器加 vision 参数**

In `content_factory/domain/automation/ch9329/executor.py`, replace the `__init__` (当前 27-36 行) with:
```python
    def __init__(
        self,
        controller: CH9329Controller | None = None,
        simulate: bool = True,
        phone_ip: str | None = None,
        vision: "ScreenVision | None" = None,
    ):
        self.simulate = simulate
        self.controller = controller or CH9329Controller(
            simulate=simulate, phone_ip=phone_ip
        )
        self.vision = vision
```

And add the import near the top (after the existing controller import):
```python
from content_factory.domain.automation.vision.screen_vision import ScreenVision  # noqa: F401
```

- [ ] **Step 4: 在 finally 释放 vision**

In `execute_flow`, replace the `finally` block (当前 69-70 行) with:
```python
        finally:
            self.controller.disconnect()
            if self.vision is not None:
                self.vision.release()
```

- [ ] **Step 5: 在 _run_step 增加三种视觉分支**

In `_run_step`, after the `input_text` branch and before the `wait` branch (当前第 90 行 `elif action_type == "wait":` 之前) insert:
```python
            elif action_type in ("wait_for_element", "verify_screen", "click_on_match"):
                detail = self._run_vision_step(action_type, step)
```

- [ ] **Step 6: 实现 _run_vision_step 辅助方法**

In the same file, add this method to `CH9329Executor` (放在 `_run_step` 之后、`_resolve_source` 之前):
```python
    def _run_vision_step(self, action_type: str, step: dict[str, Any]) -> dict[str, Any]:
        template = step.get("template")
        threshold = float(step.get("threshold", 0.8))
        if self.simulate or self.vision is None or not self.vision.available:
            return {"action": action_type, "template": template, "simulated": True}

        if action_type == "wait_for_element":
            timeout = float(step.get("timeout", 10.0))
            outcome = self.vision.wait_for(template, timeout=timeout, threshold=threshold)
        else:  # verify_screen / click_on_match
            outcome = self.vision.verify(template, threshold=threshold)

        detail: dict[str, Any] = {
            "action": action_type,
            "template": template,
            "simulated": False,
            "matched": outcome.matched,
            "confidence": outcome.confidence,
            "reason": outcome.reason,
        }
        if not outcome.matched:
            detail["ok"] = False
            return detail
        if action_type == "click_on_match":
            detail["x_ratio"] = outcome.x_ratio
            detail["y_ratio"] = outcome.y_ratio
            detail["ok"] = self.controller.click(outcome.x_ratio, outcome.y_ratio)
        return detail
```

- [ ] **Step 7: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_executor_vision.py -v
```
Expected: PASS（5 个用例）。

- [ ] **Step 8: Commit**

```bash
git add content_factory/domain/automation/ch9329/executor.py content_factory/tests/test_executor_vision.py
git commit -m "feat: add vision steps to CH9329 executor"
```

---

## Task 5: 设备表 camera_index (model/service/schema/route)

**Files:**
- Modify: `content_factory/domain/devices/models.py:23` 附近
- Modify: `content_factory/domain/devices/service.py`（`DeviceProfileInput` 与 `register_device`）
- Modify: `content_factory/app/api/schemas.py`（`DeviceRegisterRequest`、`DeviceProfileResponse`）
- Modify: `content_factory/app/api/routes_devices.py`（`device_to_response`、`register_device`）
- Test: `content_factory/tests/test_devices_camera_index.py`

**说明：** DB 迁移由现有 `migrate_missing_columns()`（启动时 [main.py:57](../../../content_factory/app/main.py) 调用，conftest 中也调用）自动加列，无需手写 ALTER TABLE。

- [ ] **Step 1: 写失败测试**

Create `content_factory/tests/test_devices_camera_index.py`:
```python
from __future__ import annotations

from content_factory.domain.devices.service import DeviceProfileInput, DeviceService


def test_register_device_persists_camera_index(db_session):
    service = DeviceService(db_session)
    device = service.register_device(
        DeviceProfileInput(name="phone-01", platform="xhs", ch9329_port="COM3", camera_index=2)
    )
    db_session.flush()
    fetched = service.get_device(device.id)
    assert fetched is not None
    assert fetched.camera_index == 2


def test_camera_index_defaults_none(db_session):
    service = DeviceService(db_session)
    device = service.register_device(DeviceProfileInput(name="phone-02"))
    assert device.camera_index is None
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_devices_camera_index.py -v
```
Expected: FAIL（`DeviceProfileInput` 无 `camera_index` / 列不存在）。

- [ ] **Step 3: 模型加列**

In `content_factory/domain/devices/models.py`, after the `phone_ip` column (当前第 20 行 `phone_ip = Column(String(64), nullable=True)`) add:
```python
    camera_index = Column(Integer, nullable=True)
```
（`Integer` 已在文件顶部导入，无需新增 import。）

- [ ] **Step 4: service 入参加字段**

In `content_factory/domain/devices/service.py`, 在 `DeviceProfileInput`（当前 13-24 行）的 `phone_ip` 之后加：
```python
    camera_index: int | None = None
```
并在 `register_device` 构造 `DeviceProfile(...)`（当前 44-54 行）里加：
```python
            camera_index=payload.camera_index,
```

- [ ] **Step 5: schemas 加字段**

In `content_factory/app/api/schemas.py`：
- `DeviceRegisterRequest` 的 `ch9329_port: str | None = None` 之后加：
```python
    phone_ip: str | None = None
    camera_index: int | None = None
```
- `DeviceProfileResponse` 的 `ch9329_port: str | None` 之后加：
```python
    camera_index: int | None
```

- [ ] **Step 6: route 透传字段**

In `content_factory/app/api/routes_devices.py`：
- `device_to_response`（当前 24-38 行）的 `ch9329_port=device.ch9329_port,` 之后加：
```python
        camera_index=device.camera_index,
```
- `register_device` 里构造 `DeviceProfileInput(...)`（当前 61-70 行）的 `ch9329_port=payload.ch9329_port,` 之后加：
```python
            phone_ip=payload.phone_ip,
            camera_index=payload.camera_index,
```

- [ ] **Step 7: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_devices_camera_index.py -v
```
Expected: PASS（2 个用例）。

- [ ] **Step 8: Commit**

```bash
git add content_factory/domain/devices/models.py content_factory/domain/devices/service.py content_factory/app/api/schemas.py content_factory/app/api/routes_devices.py content_factory/tests/test_devices_camera_index.py
git commit -m "feat: add camera_index to device profile and API"
```

---

## Task 6: publish_worker 接线视觉

**Files:**
- Modify: `content_factory/workers/publish_worker.py`（`_resolve_executor`，当前 143-163 行）
- Test: `content_factory/tests/test_publish_worker_vision.py`

- [ ] **Step 1: 写失败测试**

Create `content_factory/tests/test_publish_worker_vision.py`:
```python
from __future__ import annotations

from content_factory.domain.devices.service import DeviceProfileInput, DeviceService
from content_factory.workers.publish_worker import PublishWorker


def test_executor_gets_vision_when_camera_index_set(db_session):
    service = DeviceService(db_session)
    device = service.register_device(
        DeviceProfileInput(name="p1", platform="xhs", ch9329_port="COM3", camera_index=0)
    )
    db_session.flush()
    worker = PublishWorker(db_session, simulate=True)
    executor = worker._resolve_executor(device.id)
    assert executor.vision is not None
    # simulate=True -> vision present but not available (degrade-to-pass)
    assert executor.vision.available is False


def test_executor_no_vision_without_camera_index(db_session):
    service = DeviceService(db_session)
    device = service.register_device(DeviceProfileInput(name="p2", platform="xhs", ch9329_port="COM3"))
    db_session.flush()
    worker = PublishWorker(db_session, simulate=True)
    executor = worker._resolve_executor(device.id)
    assert executor.vision is None
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_publish_worker_vision.py -v
```
Expected: FAIL（executor.vision 始终为 None）。

- [ ] **Step 3: 修改 _resolve_executor 构造并注入 vision**

In `content_factory/workers/publish_worker.py`, replace the body of `_resolve_executor`（当前 143-163 行）with:
```python
    def _resolve_executor(self, device_id: str | None) -> CH9329Executor:
        if self.executor is not None:
            return self.executor

        from content_factory.domain.automation.vision.screen_vision import ScreenVision

        controller_kwargs: dict = {"simulate": self.simulate}
        vision: ScreenVision | None = None
        if device_id:
            device = self.device_service.get_device(device_id)
            if device is not None:
                controller_kwargs["port"] = device.ch9329_port
                controller_kwargs["phone_ip"] = getattr(device, "phone_ip", None)
                if device.screen_width:
                    controller_kwargs["screen_width"] = device.screen_width
                if device.screen_height:
                    controller_kwargs["screen_height"] = device.screen_height
                if device.camera_index is not None:
                    vision = ScreenVision(
                        camera_index=device.camera_index,
                        platform=device.platform,
                        simulate=self.simulate,
                    )

        controller = CH9329Controller(**controller_kwargs)
        return CH9329Executor(
            controller=controller,
            simulate=controller.simulate,
            phone_ip=controller.phone_ip,
            vision=vision,
        )
```

- [ ] **Step 4: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_publish_worker_vision.py -v
```
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add content_factory/workers/publish_worker.py content_factory/tests/test_publish_worker_vision.py
git commit -m "feat: wire ScreenVision into publish worker"
```

---

## Task 7: 模板目录、说明与参考流程

**Files:**
- Create: `content_factory/domain/automation/templates/xhs/.gitkeep`
- Create: `content_factory/domain/automation/templates/README.md`
- Modify: `content_factory/domain/automation/flows/xhs_upload.yaml`
- Modify: `content_factory/workers/publish_worker.py`（`DEFAULT_FLOW_STEPS`，当前 21-33 行）
- Test: 追加到 `content_factory/tests/test_executor_vision.py`

- [ ] **Step 1: 写失败测试（DEFAULT 流程含视觉步骤、simulate 下全 succeeded）**

Append to `content_factory/tests/test_executor_vision.py`:
```python
def test_default_flow_with_vision_steps_passes_in_simulate():
    from content_factory.workers.publish_worker import DEFAULT_FLOW_STEPS

    types = [s["type"] for s in DEFAULT_FLOW_STEPS]
    assert "wait_for_element" in types  # reference vision step present

    ex = CH9329Executor(controller=_StubController(), simulate=True, vision=None)
    res = ex.execute_flow(DEFAULT_FLOW_STEPS, {})
    assert all(r.status in ("succeeded", "skipped") for r in res)
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_executor_vision.py::test_default_flow_with_vision_steps_passes_in_simulate -v
```
Expected: FAIL（DEFAULT_FLOW_STEPS 无 `wait_for_element`）。

- [ ] **Step 3: 建模板目录占位**

Create `content_factory/domain/automation/templates/xhs/.gitkeep`（空文件）：
```text
```

- [ ] **Step 4: 建模板说明**

Create `content_factory/domain/automation/templates/README.md`:
```markdown
# 视觉模板 (Vision Templates)

执行器的视觉步骤（`wait_for_element` / `verify_screen` / `click_on_match`）在此查找模板小图。

## 目录约定

```
templates/<platform>/<name>.png
```

步骤里用 `template: "<platform>/<name>"`（可省略 `.png`）引用，例如 `xhs/album_tab`
解析到 `templates/xhs/album_tab.png`。

## 采集模板

1. 用对应采集卡运行真实视觉模式，截取一帧（1280x720）。
2. 裁剪出目标按钮/图标的最小稳定区域（避免包含会变化的文字/红点）。
3. 灰度匹配，默认阈值 0.8；偏花哨的图标可调到 0.7，纯色按钮可调高到 0.9。
4. 命名贴合用途：`home_publish_btn`、`album_tab`、`publish_ready` 等。

## 降级说明

`simulate=True` 或 cv2/采集卡不可用或模板文件缺失时，视觉步骤一律「降级为通过」，
因此参考流程可以先引用尚未采集的模板而不影响 dry-run。
```

- [ ] **Step 5: 在 DEFAULT_FLOW_STEPS 穿插视觉步骤**

In `content_factory/workers/publish_worker.py`, replace `DEFAULT_FLOW_STEPS`（当前 21-33 行）with:
```python
DEFAULT_FLOW_STEPS = [
    {"type": "checkpoint", "note": "confirm phone is unlocked"},
    {"type": "open_app", "app": "xiaohongshu", "note": "open Xiaohongshu app"},
    {"type": "wait_for_element", "template": "xhs/home_publish_btn", "timeout": 10, "note": "wait for home loaded"},
    {"type": "tap", "x": 540, "y": 2250, "note": "enter publish entry"},
    {"type": "verify_screen", "template": "xhs/album_tab", "note": "confirm media picker"},
    {"type": "select_media", "source": "publish_package.media", "note": "select images/videos"},
    {"type": "input_text", "field": "title", "source": "publish_package.title", "note": "input title"},
    {"type": "input_text", "field": "body", "source": "publish_package.body", "note": "input body"},
    {"type": "input_text", "field": "tags", "source": "publish_package.hashtags", "note": "input tags"},
    {"type": "set_cover", "source": "publish_package.cover", "note": "set cover if needed"},
    {"type": "preview", "note": "check preview"},
    {"type": "verify_screen", "template": "xhs/publish_ready", "note": "confirm ready to save"},
    {"type": "tap", "x": 540, "y": 2300, "note": "save draft"},
    {"type": "checkpoint", "note": "record result"},
]
```

- [ ] **Step 6: 同步更新 xhs_upload.yaml**

In `content_factory/domain/automation/flows/xhs_upload.yaml`, replace the `steps:` 列表（当前 7-46 行）with:
```yaml
steps:
  - type: checkpoint
    note: confirm phone is unlocked
  - type: open_app
    app: xiaohongshu
    note: open Xiaohongshu app
  - type: wait_for_element
    template: xhs/home_publish_btn
    timeout: 10
    note: wait for home loaded
  - type: tap
    x: 540
    y: 2250
    x_ratio: 0.5
    y_ratio: 0.9375
    note: enter publish entry
  - type: verify_screen
    template: xhs/album_tab
    note: confirm media picker
  - type: select_media
    source: publish_package.media
    note: select images/videos
  - type: input_text
    field: title
    source: publish_package.title
    note: input title
  - type: input_text
    field: body
    source: publish_package.body
    note: input body
  - type: input_text
    field: tags
    source: publish_package.hashtags
    note: input tags
  - type: set_cover
    source: publish_package.cover
    note: set cover if needed
  - type: preview
    note: check preview
  - type: verify_screen
    template: xhs/publish_ready
    note: confirm ready to save
  - type: tap
    x: 540
    y: 2300
    x_ratio: 0.5
    y_ratio: 0.958333
    note: save draft
  - type: checkpoint
    note: record result
```

- [ ] **Step 7: 运行确认通过**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests/test_executor_vision.py -v
```
Expected: PASS（含新用例，全部通过）。

- [ ] **Step 8: Commit**

```bash
git add content_factory/domain/automation/templates content_factory/domain/automation/flows/xhs_upload.yaml content_factory/workers/publish_worker.py content_factory/tests/test_executor_vision.py
git commit -m "feat: add vision templates dir and reference flow steps"
```

---

## Task 8: 全量回归

**Files:** 无新增，仅验证。

- [ ] **Step 1: 跑 content_factory 全部新测试**

Run:
```bash
.venv/Scripts/python.exe -m pytest content_factory/tests -v
```
Expected: 全部 PASS（cv2 相关用例 SKIPPED 也算通过），无 FAIL/ERROR。

- [ ] **Step 2: 冒烟导入主应用，确认无 import 回归**

Run:
```bash
.venv/Scripts/python.exe -c "import content_factory.app.main as m; print('app import ok')"
```
Expected: 打印 `app import ok`，无异常。

- [ ] **Step 3: 最终提交（若有未提交的零散改动）**

```bash
git add -A
git commit -m "test: full vision closed-loop regression green" || echo "nothing to commit"
```

---

## Self-Review 结果

- **Spec 覆盖**：架构四单元(capture/matcher/templates/screen_vision)→Task1-3；执行器三步骤+降级→Task4；camera_index 全链路→Task5；publish_worker 接线→Task6；模板目录+参考流程→Task7；可选依赖→Task0；测试→各任务内 + Task8。DB 迁移由现有 `migrate_missing_columns()` 自动完成（较 spec 的手写 ALTER 更优，已在计划说明）。
- **Placeholder 扫描**：无 TBD/TODO，所有代码步骤含完整代码。
- **类型一致性**：`VisionOutcome`(matched/confidence/x_ratio/y_ratio/simulated/reason)、`MatchResult`(matched/confidence/center_x/center_y/frame_w/frame_h)、`ScreenVision.wait_for/verify/available/release`、`CH9329Executor.__init__(vision=)` 与 `_run_vision_step` 在各任务中签名一致。
