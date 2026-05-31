# CH9329 Publish Copy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the publish management page present CH9329 serial COM control as the primary local publishing path and remove misleading ADB/USB/WiFi setup copy from the main flow.

**Architecture:** Keep the existing single Streamlit page `web/views/4_Publish.py` and make focused copy/UI changes in the device-management and publish-settings sections. Use Streamlit `AppTest` coverage in `tests/test_app_baseline.py` to lock visible text expectations, then verify through a running browser session.

**Tech Stack:** Python, Streamlit, Streamlit testing API, pytest, Playwright for runtime verification.

---

## File Structure

- Modify `web/views/4_Publish.py`
  - `_render_device_cards`: CH9329 empty state.
  - `_render_auto_refresh_device_list`: CH9329 auto-refresh copy and no-device copy.
  - `render_devices_tab`: remove legacy WiFi/pairing tabs from the main UI and keep one CH9329 serial form.
  - `render_publish_settings`: keep CH9329 serial settings and remove ADB Server settings.
  - `render_client_agent_tab`: replace USB/ADB-specific client-agent copy with provider-neutral device copy.
- Modify `tests/test_app_baseline.py`
  - Extend the Streamlit page regression to assert CH9329 copy is visible and legacy ADB/USB/WiFi setup copy is absent.

---

### Task 1: Lock publish page copy expectations

**Files:**
- Modify: `tests/test_app_baseline.py`
- Test: `tests/test_app_baseline.py`

- [ ] **Step 1: Replace the publish page copy regression with stricter expectations**

In `tests/test_app_baseline.py`, update `test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb` to this exact body:

```python
def test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("web/views/4_Publish.py")
    at.run(timeout=20)

    rendered = "\n".join(
        str(element.value)
        for collection in (at.error, at.info, at.warning, at.markdown, at.caption, at.text)
        for element in collection
    )

    assert "ADB 环境问题" not in rendered
    assert "ADB environment" not in rendered
    assert "ADB Server 设置" not in rendered
    assert "USB 调试" not in rendered
    assert "adb devices" not in rendered
    assert "无线配对" not in rendered
    assert "ADB 端口" not in rendered
    assert "CH9329" in rendered
    assert "COM" in rendered
    assert "CH9329 串口设置" in rendered
    assert any(element.label == "波特率" for element in at.number_input)
```

- [ ] **Step 2: Run the test and verify it fails before UI cleanup**

Run:

```bash
python -m pytest tests/test_app_baseline.py::test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb -q
```

Expected: FAIL mentioning one of the legacy strings, such as `USB 调试`, `adb devices`, `无线配对`, or `ADB 端口`.

- [ ] **Step 3: Commit the failing test only if implementing with separate commits is required**

Normally do not commit red tests alone on `main`. If using a temporary worktree branch, commit with:

```bash
git add tests/test_app_baseline.py
git commit -m "test: lock CH9329 publish page copy expectations"
```

---

### Task 2: Remove legacy ADB setup from device management

**Files:**
- Modify: `web/views/4_Publish.py`
- Test: `tests/test_app_baseline.py`

- [ ] **Step 1: Update `_render_device_cards` empty state**

In `web/views/4_Publish.py`, change the empty state in `_render_device_cards` to:

```python
    if not devices:
        st.info("暂无设备。请在下方注册 CH9329 串口 COM 设备，或切换到客户端代理模式。")
        return
```

- [ ] **Step 2: Update auto-refresh caption and no-device copy**

In `_render_auto_refresh_device_list`, change the caption to:

```python
    st.caption("设备状态每 8 秒自动刷新；CH9329 串口设备会根据配置中的 COM 口自动注册。")
```

Replace the non-VPS no-device `st.info(...)` block with:

```python
            st.info(
                "💡 **暂无 CH9329 串口设备。**\n\n"
                "请检查：\n"
                "1. CH9329 控制器已连接到本机。\n"
                "2. Windows 设备管理器中能看到串口号，例如 `COM3` / `COM5`。\n"
                "3. 在下方「CH9329 串口」表单中填写并注册对应 COM 口。"
            )
```

Replace the VPS warning body with this provider-neutral text:

```python
            st.warning(
                "⚠️ **您当前使用的是公网/VPS 网页后台**\n\n"
                "CH9329 串口设备必须连接在实际执行发布的电脑上；公网网页本身无法直接访问你本地电脑的串口。\n\n"
                "**推荐方式：**\n"
                "- 在连接 CH9329 的本地电脑运行本项目或客户端代理。\n"
                "- 主控网页负责任务编排，本地执行端负责控制其连接的发布设备。"
            )
```

- [ ] **Step 3: Remove legacy WiFi and Android pairing tabs from add-device UI**

In `render_devices_tab`, replace the tab block beginning with:

```python
    tab_serial, tab_wifi, tab_pair = st.tabs(["CH9329 串口", "鸿蒙 / 手动 WiFi", "Android 11+ 无线配对"])
```

through the end of the `with tab_pair:` block with a single CH9329 block:

```python
    st.markdown("##### CH9329 串口")
    st.info(
        "CH9329 硬件控制模式通过串口 COM 控制物理发帖机，不依赖 ADB。\n"
        "请填写 `COM3` / `COM5` 等 Windows 串口号；推荐先在配置文件中设置 `xhs_publish.hardware.com_port`。"
    )
    with st.form("add_serial_device"):
        serial = st.text_input("串口 COM", placeholder="如：COM3")
        name = st.text_input("设备名称", placeholder="如：CH9329 主号机")
        theme = st.text_input("内容主题", placeholder="如：旅行摄影")
        if st.form_submit_button("注册 CH9329 串口设备"):
            if serial.strip():
                dm.add_device(serial=serial.strip(), name=name.strip(), theme=theme.strip())
                st.success(f"已注册 CH9329 串口设备 {serial}")
                st.rerun()
```

Do not leave visible labels containing `鸿蒙 / 手动 WiFi`, `Android 11+ 无线配对`, `ADB 端口`, `adb pair`, `mDNS`, or `adb devices` in the default page.

- [ ] **Step 4: Run the focused copy regression**

Run:

```bash
python -m pytest tests/test_app_baseline.py::test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb -q
```

Expected: If Task 3 is not done yet, the test may still fail on client-agent copy. It must no longer fail on the add-device tabs.

---

### Task 3: Clean client-agent visible copy

**Files:**
- Modify: `web/views/4_Publish.py`
- Test: `tests/test_app_baseline.py`

- [ ] **Step 1: Update hanging-node extension helper text**

In `render_devices_tab`, replace the `st.info(...)` body under `st.subheader("🖥️ 挂机节点扩展助手")` with:

```python
        "💡 **分布式多电脑矩阵挂机**：\n"
        "如果你想让其他电脑参与发布，只需在执行端电脑上运行本助手。\n\n"
        "1. 点击下方按钮，下载挂机小助手程序到执行端电脑；\n"
        "2. 执行端电脑连接本地发布设备并运行助手；\n"
        "3. 助手会连接当前网页后台，自动领取并执行发布任务。"
```

- [ ] **Step 2: Update generated Windows batch copy**

In `render_client_agent_tab`, change the batch content strings:

```bat
echo Starting agent. Ensure your local publishing device is connected.
```

and remove any visible `USB debugging` wording from `bat_content`.

- [ ] **Step 3: Update generated shell script copy**

In `sh_content`, change the startup echo to:

```bash
echo "正在启动客户端代理，请确保本机发布设备已连接并可用！"
```

- [ ] **Step 4: Update user-facing client-agent steps**

Replace the `st.markdown` steps under `st.markdown("#### 🚀 使用步骤（零配置，一步到位）：")` with:

```python
    st.markdown(
        "1. **准备执行端电脑与发布设备**：\n"
        "   - 将 CH9329 控制器或其他本地发布设备连接到执行端电脑。\n"
        "   - 确保执行端电脑安装 Python 环境 (3.9+)。\n"
        "2. **一键运行代理**：\n"
        "   - **Windows**：双击下载的 `start_agent.bat` 脚本即可。脚本会自动下载代理包、解压、安装依赖并运行。\n"
        "   - **macOS / Linux**：打开终端，运行 `chmod +x start_agent.sh` 赋予权限，然后运行 `./start_agent.sh` 即可。\n"
        "3. **自动同步**：运行后，代理会在终端显示连接状态，并自动从当前服务器领取发布、评论或删除任务。"
    )
```

- [ ] **Step 5: Update online-agent empty serial text**

Replace:

```python
st.markdown("⚠️ *未检测到已连接手机，请确保已运行 adb devices 并授权*")
```

with:

```python
st.markdown("⚠️ *未检测到执行端发布设备，请确认本地设备已连接并被代理识别*")
```

- [ ] **Step 6: Run the focused copy regression**

Run:

```bash
python -m pytest tests/test_app_baseline.py::test_publish_page_describes_ch9329_serial_mode_instead_of_blocking_on_adb -q
```

Expected: PASS.

---

### Task 4: Run regression checks

**Files:**
- Test: `tests/test_app_baseline.py`
- Test: `tests/test_lifecycle.py`

- [ ] **Step 1: Run app baseline tests**

Run:

```bash
python -m pytest tests/test_app_baseline.py
```

Expected: all tests pass.

- [ ] **Step 2: Run lifecycle tests**

Run:

```bash
python -m pytest tests/test_lifecycle.py
```

Expected: all tests pass with no `was never awaited` warning.

- [ ] **Step 3: Run Streamlit page smoke test**

Run:

```bash
PYTHONIOENCODING=utf-8 python - <<'PY'
from streamlit.testing.v1 import AppTest
for page in ['web/views/4_Publish.py', 'web/views/10_Monitor.py']:
    print(f'=== {page} ===')
    at = AppTest.from_file(page)
    at.run(timeout=20)
    print('exception_count', len(at.exception))
    print('error_count', len(at.error))
    print('warning_count', len(at.warning))
PY
```

Expected:

```text
=== web/views/4_Publish.py ===
exception_count 0
error_count 0
=== web/views/10_Monitor.py ===
exception_count 0
error_count 0
```

---

### Task 5: Runtime browser verification

**Files:**
- Runtime evidence: `runtime/verification/*.png`

- [ ] **Step 1: Start a fresh Streamlit instance**

Run on a fresh unused port, for example:

```bash
NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost" python -m streamlit run web/app.py --server.port 8767 --server.headless true --server.address 127.0.0.1
```

Expected output includes:

```text
URL: http://127.0.0.1:8767
```

- [ ] **Step 2: Drive login, publish page, monitor page, and reload**

Run this Playwright script after updating the port if needed:

```bash
PYTHONIOENCODING=utf-8 python - <<'PY'
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out = Path('runtime/verification')
    out.mkdir(parents=True, exist_ok=True)
    username = 'claude_verify_ch9329_copy'
    password = 'verify123456'
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1400})
        await page.goto('http://127.0.0.1:8767', wait_until='networkidle', timeout=30000)
        body = await page.locator('body').inner_text()
        if '登录平台' in body:
            await page.get_by_text('📝 注册新账号', exact=True).click(timeout=5000)
            await page.get_by_label('设定用户名', exact=True).fill(username)
            await page.get_by_label('设定密码', exact=True).fill(password)
            await page.get_by_label('确认密码', exact=True).fill(password)
            await page.get_by_role('button', name='创建新账号', exact=True).click()
            await page.wait_for_timeout(2500)
            await page.get_by_text('🔑 登录账户', exact=True).click(timeout=5000)
            await page.get_by_label('用户名', exact=True).fill(username)
            await page.get_by_label('密码', exact=True).fill(password)
            await page.get_by_role('button', name='登录平台', exact=True).click()
            await page.wait_for_timeout(3500)
        await page.screenshot(path=str(out / 'ch9329_after_login.png'), full_page=True)
        for name, shot in [('发布管理', 'ch9329_publish.png'), ('监控大屏', 'ch9329_monitor.png')]:
            await page.get_by_text(name, exact=True).first.click(timeout=15000)
            await page.wait_for_timeout(5000)
            text = await page.locator('body').inner_text(timeout=10000)
            await page.screenshot(path=str(out / shot), full_page=True)
            print(name, {
                'has_adb_env_error': 'ADB 环境问题' in text,
                'has_adb_server_settings': 'ADB Server 设置' in text,
                'has_usb_debugging': 'USB 调试' in text,
                'has_adb_devices': 'adb devices' in text,
                'has_wireless_pairing': '无线配对' in text,
                'has_ch9329': 'CH9329' in text,
                'has_com': 'COM' in text,
                'has_monitor_title': '集中群控大屏' in text,
            })
        await page.reload(wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2500)
        text = await page.locator('body').inner_text(timeout=10000)
        await page.screenshot(path=str(out / 'ch9329_after_reload.png'), full_page=True)
        print('reload_has_error', 'Traceback' in text or 'Exception' in text)
        await browser.close()

asyncio.run(main())
PY
```

Expected observations:

```text
发布管理 {'has_adb_env_error': False, 'has_adb_server_settings': False, 'has_usb_debugging': False, 'has_adb_devices': False, 'has_wireless_pairing': False, 'has_ch9329': True, 'has_com': True, ...}
监控大屏 {... 'has_monitor_title': True, ...}
reload_has_error False
```

---

### Task 6: Commit and push

**Files:**
- Modify: `web/views/4_Publish.py`
- Modify: `tests/test_app_baseline.py`
- Include already modified: `pixelle_video/services/device_manager.py`, `pixelle_video/services/publish_scheduler.py`, `tests/test_lifecycle.py`

- [ ] **Step 1: Review git status**

Run:

```bash
git status --short
```

Expected: tracked changes include the intended files. Do not add local runtime artifacts such as `.claude/`, `.codegraph/`, `config/devices.yaml`, `runtime/`, or tarballs.

- [ ] **Step 2: Stage intended tracked files**

Run:

```bash
git add web/views/4_Publish.py tests/test_app_baseline.py pixelle_video/services/device_manager.py pixelle_video/services/publish_scheduler.py tests/test_lifecycle.py
```

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "fix: align publish management with CH9329 mode" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Push main**

Run:

```bash
git push origin main
```

Expected: push updates `main` on origin.

---

## Self-Review

- Spec coverage: device list copy, add-device flow, publish settings, client-agent wording, tests, runtime verification, and push are covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: uses existing `config_manager.update`, `xhs_publish.hardware.com_port`, `baudrate`, and `unlock_pin` from `HardwareConfig`.
