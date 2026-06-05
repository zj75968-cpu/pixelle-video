# CH9329 调试与坐标获取指南

本指南介绍如何使用 `pixelle_video` 模块中集成的 CH9329 调试和坐标获取功能。

## 目录

1. [快速开始](#快速开始)
2. [可视化工作台](#可视化工作台)
3. [交互式调试控制台](#交互式调试控制台)
4. [快速坐标拾取](#快速坐标拾取)
5. [编程式使用](#编程式使用)
6. [CH9329 增强方法](#ch9329-增强方法)

---

## 快速开始

### 1. 启动可视化工作台（推荐）

最完整的图形化调试工具，支持实时投屏、坐标拾取、手势测试等：

```python
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench

workbench = CalibrationWorkbench()

# 启动可视化GUI（异步，不阻塞）
workbench.launch_interactive_gui(
    phone_id="vivo_v2199a_001",
    profile_name="default"
)
```

或者直接运行脚本：

```bash
python scripts/ch9329_visual_debug.py --phone_id vivo_v2199a_001 --profile default
```

**功能特性：**
- ✅ 实时屏幕投屏（1.5秒/帧）
- ✅ 鼠标悬停显示坐标
- ✅ 点击图片直接物理点击手机
- ✅ 拖拽绘制滑动轨迹
- ✅ 键盘输入测试
- ✅ 语义点保存和管理
- ✅ 双击测试已保存的坐标点

---

## 可视化工作台

### 启动方式

```python
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench

workbench = CalibrationWorkbench()
workbench.launch_interactive_gui("vivo_v2199a_001")
```

### 界面说明

#### 左侧：屏幕投屏区
- **实时投屏**：勾选"实时同步投屏"自动刷新
- **手动刷新**：点击"立即刷新手机屏幕"
- **坐标显示**：鼠标悬停显示像素和比例坐标
- **点击测试**：直接点击图片，物理点击手机对应位置
- **滑动测试**：按住鼠标拖拽，松开后执行滑动手势

#### 右侧：控制面板

**硬件连接标签页：**
- 选择 CH9329 串口
- 选择 ADB 设备
- 配置屏幕分辨率
- 建立物理连接

**坐标校准标签页：**
- 输入语义点名称（如 `xhs.home.publish_button`）
- 点击图片选择坐标
- 保存语义点
- 查看和管理已保存的点
- 双击列表项测试点击

**键鼠调试标签页：**
- 文本输入测试
- 快捷键测试（Home、Back、Enter等）
- 连续退格
- 滑动手势说明

---

## 交互式调试控制台

命令行版本的调试工具，适合快速测试和脚本化操作。

### 启动方式

```python
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench

workbench = CalibrationWorkbench()

# 启动校准会话
session = workbench.start_calibration("vivo_v2199a_001")

# 进入交互式控制台
workbench.interactive_debug_console("vivo_v2199a_001")
```

### 可用命令

#### 坐标操作
```bash
# 点击（支持像素或比例坐标）
click 540 1200          # 像素坐标
click 0.5 0.5           # 比例坐标（屏幕中心）
c 540 1200              # 简写

# 滑动
swipe 540 1800 540 600  # 从底部向上滑动
s 0.5 0.8 0.5 0.3       # 比例坐标滑动
```

#### 键盘操作
```bash
type hello              # 输入文本
t hello                 # 简写
enter                   # 回车键
back                    # 返回键
backspace               # 退格键
backspace 5             # 连续退格5次
home                    # 返回桌面（上滑手势）
```

#### 工具命令
```bash
screenshot              # 截图
ss                      # 简写
pick                    # 快速拾取坐标（弹出图形界面）
list                    # 列出已保存的坐标点
test xhs.home.button    # 测试指定坐标点
help                    # 显示帮助
exit                    # 退出
```

### 使用示例

```bash
[CH9329]> screenshot
✓ 截图已保存: F:\codex project\小红书\runtime\calibration_screenshots\...

[CH9329]> pick
# 弹出图形界面，点击选择坐标
✓ 坐标: (540, 1200) | 比例: (0.5000, 0.5000)

[CH9329]> click 540 1200
🎯 点击像素: (540, 1200) -> 比例: (0.5000, 0.5000)
✓ 点击成功

[CH9329]> list
已保存的坐标点 (共 3 个):
--------------------------------------------------------------------------------
名称                           坐标            比例                 描述
--------------------------------------------------------------------------------
xhs.home.publish_button        (540, 1200)     (0.5000, 0.5000)     发布按钮
xhs.edit.title_input           (540, 600)      (0.5000, 0.2500)     标题输入框
xhs.edit.confirm_button        (960, 2100)     (0.8889, 0.8750)     确认按钮

[CH9329]> test xhs.home.publish_button
🎯 测试点 'xhs.home.publish_button' at ratio (0.5000, 0.5000)
✓ 点击成功
```

---

## 快速坐标拾取

在已有截图上快速拾取坐标，无需启动完整的工作台。

### 使用方式

```python
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench

workbench = CalibrationWorkbench()

# 启动校准会话
session = workbench.start_calibration("vivo_v2199a_001")

# 截图
workbench.capture_screen("vivo_v2199a_001")

# 快速拾取坐标（弹出图形界面）
coords = workbench.quick_pick_coordinates("vivo_v2199a_001", auto_screenshot=False)

if coords:
    x, y, x_ratio, y_ratio = coords
    print(f"像素坐标: ({x}, {y})")
    print(f"比例坐标: ({x_ratio:.4f}, {y_ratio:.4f})")
    
    # 保存为语义点
    workbench.save_point(
        phone_id="vivo_v2199a_001",
        name="xhs.my_button",
        x=x,
        y=y,
        description="我的按钮"
    )
```

---

## 编程式使用

### 完整的校准流程

```python
from pixelle_video.device_farm.calibration.workbench import CalibrationWorkbench

# 初始化工作台
workbench = CalibrationWorkbench()

# 启动校准会话
session = workbench.start_calibration(
    phone_id="vivo_v2199a_001",
    profile_name="xiaohongshu"
)

# 1. 截图
img_data, img_path = workbench.capture_screen("vivo_v2199a_001")
print(f"截图已保存: {img_path}")

# 2. 保存坐标点
point = workbench.save_point(
    phone_id="vivo_v2199a_001",
    name="xhs.home.publish_button",
    x=540,
    y=1200,
    description="首页发布按钮"
)
print(f"坐标点已保存: {point.name}")

# 3. 测试坐标点
result = workbench.test_point(
    phone_id="vivo_v2199a_001",
    name="xhs.home.publish_button",
    capture_after=True
)

if result['success']:
    print("✓ 点击成功")
    print(f"前置截图: {result['before_screenshot']}")
    print(f"后置截图: {result['after_screenshot']}")

# 4. 比较截图（检测变化）
comparison = workbench.compare_screenshots("vivo_v2199a_001")
print(f"屏幕变化: {comparison['change_percentage']:.2f}%")

# 5. 列出所有坐标点
points = workbench.list_points("vivo_v2199a_001")
for point in points:
    print(f"- {point['name']}: ({point['x']}, {point['y']})")

# 6. 获取配置文件
profile = workbench.get_profile("vivo_v2199a_001")
print(f"配置文件: {profile.profile_name}")
print(f"坐标点数量: {len(profile.points)}")

# 7. 停止会话（自动保存）
workbench.stop_calibration("vivo_v2199a_001", save_profile=True)
```

### 直接使用 CH9329 控制器

```python
from pixelle_video.utils.ch9329 import CH9329Controller

# 初始化控制器
controller = CH9329Controller(port="COM3")
controller.screen_width = 1080
controller.screen_height = 2400

# 连接
if controller.connect():
    print("✓ CH9329 已连接")
    
    # 测试连接
    if controller.test_connection():
        print("✓ 连接测试通过")
    
    # 点击屏幕中心
    controller.tap_center()
    
    # 向上滑动
    controller.swipe_up(distance=0.3, duration=0.5)
    
    # 输入文本
    controller.write_text("Hello World")
    
    # 返回桌面
    controller.swipe_up_to_home()
    
    # 断开连接
    controller.disconnect()
```

---

## CH9329 增强方法

新增的便捷方法，简化常见操作。

### 像素坐标操作

```python
# 使用像素坐标点击（自动转换为比例）
controller.click_pixel(540, 1200)

# 使用像素坐标滑动
controller.swipe_pixel(540, 1800, 540, 600, duration=0.8)
```

### 快捷手势

```python
# 点击屏幕中心
controller.tap_center()

# 向上滑动（默认30%距离）
controller.swipe_up(distance=0.3, duration=0.5)

# 向下滑动
controller.swipe_down(distance=0.3, duration=0.5)

# 向左滑动
controller.swipe_left(distance=0.3, duration=0.5)

# 向右滑动
controller.swipe_right(distance=0.3, duration=0.5)

# 双击
controller.double_click(0.5, 0.5, interval=0.1)
```

### 坐标信息查询

```python
# 获取坐标详细信息
info = controller.get_coordinate_info(540, 1200)
print(info)
# 输出:
# {
#     'pixel': {'x': 540, 'y': 1200},
#     'ratio': {'x': 0.5, 'y': 0.5},
#     'screen': {'width': 1080, 'height': 2400}
# }
```

### 连接测试

```python
# 测试 CH9329 连接是否正常
if controller.test_connection():
    print("✓ CH9329 工作正常")
else:
    print("❌ CH9329 连接异常")
```

---

## 最佳实践

### 1. 坐标命名规范

使用层级化的语义命名：

```
<app>.<page>.<element>

示例：
xhs.home.publish_button          # 小红书首页发布按钮
xhs.edit.title_input             # 编辑页标题输入框
xhs.edit.image_selector          # 编辑页图片选择器
xhs.publish.confirm_button       # 发布页确认按钮
```

### 2. 坐标采集流程

1. **启动可视化工作台**：`workbench.launch_interactive_gui()`
2. **连接硬件**：选择串口和ADB设备
3. **实时投屏**：勾选"实时同步投屏"
4. **操作手机**：手动导航到目标页面
5. **点击标注**：在投屏画面上点击目标位置
6. **输入名称**：使用规范的语义命名
7. **测试验证**：双击列表项测试点击效果
8. **保存配置**：点击"强制保存配置文件"

### 3. 调试技巧

**使用交互式控制台快速测试：**

```python
# 启动控制台
workbench.interactive_debug_console("vivo_v2199a_001")

# 在控制台中：
[CH9329]> screenshot      # 截图
[CH9329]> pick            # 拾取坐标
[CH9329]> click 540 1200  # 测试点击
[CH9329]> list            # 查看已保存的点
```

**使用快速拾取器批量采集：**

```python
# 循环采集多个坐标
for i in range(5):
    coords = workbench.quick_pick_coordinates("vivo_v2199a_001")
    if coords:
        name = input("输入坐标点名称: ")
        workbench.save_point("vivo_v2199a_001", name, coords[0], coords[1])
```

### 4. 配置文件管理

配置文件保存在：`config/calibration_profiles/{phone_id}_{profile_name}.yaml`

```yaml
profile_id: vivo_v2199a_001_xiaohongshu
phone_id: vivo_v2199a_001
screen:
  width: 1080
  height: 2400
  safe_top: 100
  safe_bottom: 120
  navigation_mode: gesture
points:
  - name: xhs.home.publish_button
    type: absolute
    x: 540
    y: 1200
    x_ratio: 0.5
    y_ratio: 0.5
    description: 首页发布按钮
```

---

## 故障排查

### CH9329 连接失败

```python
# 1. 检查串口是否正确
from pixelle_video.device_farm.hardware.ch9329_controller import scan_com_ports
ports = scan_com_ports()
print("可用串口:", ports)

# 2. 测试连接
controller = CH9329Controller(port="COM3")
if controller.connect():
    if controller.test_connection():
        print("✓ 连接正常")
    else:
        print("❌ 连接异常，请检查硬件")
```

### ADB 设备未找到

```python
# 检查 ADB 设备
from pixelle_video.device_farm.hardware.adb_observer import scan_adb_devices
devices = scan_adb_devices()
for dev in devices:
    print(f"设备: {dev.serial}, 状态: {dev.status}")
```

### 坐标点击不准确

1. **检查屏幕分辨率配置**：确保 `screen_width` 和 `screen_height` 正确
2. **重新校准**：使用可视化工作台重新采集坐标
3. **测试校准**：`controller.calibrate_mouse()` 确保鼠标归零正常

---

## 总结

现在你有三种方式来调试 CH9329 和获取坐标：

1. **可视化工作台**（最推荐）：完整的图形化工具，实时投屏+坐标拾取
2. **交互式控制台**：命令行快速测试，适合脚本化操作
3. **编程式API**：完全的代码控制，适合自动化流程

选择最适合你当前任务的方式即可！
