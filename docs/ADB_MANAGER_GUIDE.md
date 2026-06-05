# ADB Manager 增强功能指南

## 概述

新的 `ADBManager` 模块为多设备自动化项目提供了强大的设备管理功能，解决了 ADB 连接不稳定的问题。

## 核心功能

### 1. 自动重试机制
- **指数退避重试**：失败后自动重试，延迟时间逐渐增加
- **可配置重试次数**：默认 3 次，可自定义
- **智能错误恢复**：区分临时故障和永久故障

### 2. 设备健康监控
- **实时状态跟踪**：监控设备连接状态（已连接、离线、未授权等）
- **健康指标**：
  - 连续失败次数
  - 总重连次数
  - 最后成功操作时间
  - 设备在线时长
- **健康评估**：自动判断设备是否健康

### 3. 自动重连
- **掉线检测**：自动检测设备断开连接
- **主动重连**：尝试重新建立连接
- **ADB 服务器重启**：必要时自动重启 ADB 服务器

### 4. 后台监控
- **独立监控线程**：不阻塞主程序
- **定期健康检查**：可配置检查间隔
- **事件回调**：设备连接/断开/重连时触发回调

## 快速开始

### 基础使用

```python
from pixelle_video.device_farm.hardware import ADBManager

# 创建管理器
manager = ADBManager(
    retry_attempts=3,      # 重试次数
    retry_delay=1.0,       # 初始重试延迟（秒）
    retry_backoff=2.0,     # 退避倍数
    monitor_interval=30.0, # 监控间隔（秒）
    auto_restart_adb=True  # 自动重启 ADB
)

# 扫描设备（带重试）
devices = manager.scan_devices_with_retry()

for device in devices:
    print(f"Found: {device.serial} - {device.status}")
```

### 使用上下文管理器

```python
from pixelle_video.device_farm.hardware import ADBManager

# 自动启动和停止监控
with ADBManager(monitor_interval=10.0) as manager:
    devices = manager.scan_devices_with_retry()
    
    # 执行操作...
    
# 退出时自动停止监控
```

### 执行操作（带重试）

```python
from pixelle_video.device_farm.hardware import ADBManager, capture_screenshot

manager = ADBManager(retry_attempts=3)

# 执行截图操作，失败自动重试
result = manager.execute_with_retry(
    serial="10ACBE28M70044L",
    operation=lambda s: capture_screenshot(s, "screen.png"),
    operation_name="Screenshot capture"
)

if result:
    print("Screenshot captured successfully")
else:
    print("Failed after all retries")
```

### 注册事件回调

```python
from pixelle_video.device_farm.hardware import ADBManager

manager = ADBManager()

# 设备连接时触发
def on_connected(serial):
    print(f"Device connected: {serial}")

# 设备断开时触发
def on_disconnected(serial):
    print(f"Device disconnected: {serial}")

# 设备重连时触发
def on_reconnected(serial):
    print(f"Device reconnected: {serial}")

# 注册回调
manager.register_callback('connected', on_connected)
manager.register_callback('disconnected', on_disconnected)
manager.register_callback('reconnected', on_reconnected)

# 启动监控
manager.start_monitoring()
```

### 查看设备健康状态

```python
from pixelle_video.device_farm.hardware import ADBManager

manager = ADBManager()
manager.scan_devices_with_retry()

# 获取单个设备健康状态
health = manager.get_device_health("10ACBE28M70044L")
if health:
    print(f"State: {health.state.value}")
    print(f"Consecutive failures: {health.consecutive_failures}")
    print(f"Total reconnects: {health.total_reconnects}")
    print(f"Is healthy: {health.is_healthy()}")

# 获取所有设备健康状态
all_health = manager.get_all_health_status()
for serial, health in all_health.items():
    print(f"{serial}: {health.state.value}")

# 获取健康设备列表
healthy_devices = manager.get_healthy_devices()
print(f"Healthy devices: {healthy_devices}")
```

## 工具脚本

### 1. 测试脚本 (`scripts/test_adb_manager.py`)

测试 ADB Manager 的各项功能：

```bash
# 运行所有测试
python scripts/test_adb_manager.py

# 选择特定测试
python scripts/test_adb_manager.py
# 然后选择：
# 1. 基础扫描测试
# 2. 后台监控测试
# 3. 操作重试测试
# 4. 上下文管理器测试
# 5. 重连模拟测试
```

**测试内容：**
- ✅ 设备扫描（带重试）
- ✅ 后台监控和事件回调
- ✅ 操作执行（带重试）
- ✅ 上下文管理器
- ✅ 设备重连模拟

### 2. 健康监控仪表板 (`scripts/04_device_health_monitor.py`)

实时监控设备健康状态：

```bash
# 监控所有设备
python scripts/04_device_health_monitor.py

# 监控特定设备
python scripts/04_device_health_monitor.py --devices vivo_v2199a_001,vivo_v2199a_002
```

**仪表板显示：**
- 📱 设备状态（连接/离线/未授权等）
- ⏱️ 在线时长
- 🔄 重连次数
- ❌ 失败次数
- 💚 健康状态
- 📋 最近事件
- 📊 统计信息

**示例输出：**
```
================================================================================
Device Health Dashboard - Update #5 - 14:23:45
================================================================================

📱 Device Status:
--------------------------------------------------------------------------------

✅ Vivo V2199A #1 (10ACBE28M70044L)
   State: CONNECTED
   Uptime: 5m 23s
   Last seen: 2s ago
   Failures: 0
   Reconnects: 1
   Health: 💚 HEALTHY

⚠️  Vivo V2199A #2 (10ACBE28M70045L)
   State: OFFLINE
   Uptime: N/A
   Last seen: 45s ago
   Failures: 3
   Reconnects: 0
   Health: 💔 UNHEALTHY

📋 Recent Events (last 5):
--------------------------------------------------------------------------------
[14:23:43] ✅ Device reconnected: 10ACBE28M70044L
[14:23:15] ⚠️  Device disconnected: 10ACBE28M70044L
[14:22:50] 🔌 Device connected: 10ACBE28M70045L
[14:22:30] 🔌 Device connected: 10ACBE28M70044L

📊 Statistics:
--------------------------------------------------------------------------------
Total devices: 2
Connected: 1
Disconnected: 1
Total reconnections: 1
```

### 3. 增强校准工具 (`scripts/05_enhanced_calibrate.py`)

带自动重试和监控的设备校准：

```bash
# 校准设备
python scripts/05_enhanced_calibrate.py --device vivo_v2199a_001

# 从参考设备复制校准
python scripts/05_enhanced_calibrate.py --device vivo_v2199a_002 --reference vivo_v2199a_001
```

**增强功能：**
- ✅ 硬件检查（带重试）
- ✅ 截图捕获（带重试）
- ✅ 实时健康监控
- ✅ 自动重连
- ✅ 校准过程中的 `health` 命令

**新增命令：**
```
calibrate> health          # 查看设备健康状态
calibrate> save home 540 1200  # 保存校准点
calibrate> test 540 1200   # 测试点击
calibrate> list            # 列出所有点
calibrate> done            # 完成校准
```

## 配置参数

### ADBManager 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `retry_attempts` | int | 3 | 操作失败后的重试次数 |
| `retry_delay` | float | 1.0 | 初始重试延迟（秒） |
| `retry_backoff` | float | 2.0 | 重试延迟的退避倍数 |
| `monitor_interval` | float | 30.0 | 后台监控的检查间隔（秒） |
| `auto_restart_adb` | bool | True | 失败时是否自动重启 ADB 服务器 |
| `health_check_timeout` | int | 5 | 健康检查操作的超时时间（秒） |

### 设备状态

| 状态 | 说明 |
|------|------|
| `CONNECTED` | 设备已连接且可用 |
| `DISCONNECTED` | 设备已断开连接 |
| `OFFLINE` | 设备离线（USB 连接但 ADB 不可用） |
| `UNAUTHORIZED` | 设备未授权（需要在设备上确认 USB 调试） |
| `RECONNECTING` | 正在尝试重新连接 |
| `UNKNOWN` | 未知状态 |

## 最佳实践

### 1. 使用上下文管理器

```python
# 推荐：自动管理监控生命周期
with ADBManager() as manager:
    # 执行操作
    pass

# 不推荐：手动管理
manager = ADBManager()
manager.start_monitoring()
try:
    # 执行操作
    pass
finally:
    manager.stop_monitoring()
```

### 2. 合理设置重试参数

```python
# 快速失败（适合交互式操作）
manager = ADBManager(
    retry_attempts=2,
    retry_delay=0.5,
    retry_backoff=1.5
)

# 持久重试（适合后台任务）
manager = ADBManager(
    retry_attempts=5,
    retry_delay=2.0,
    retry_backoff=2.0
)
```

### 3. 监控关键设备

```python
manager = ADBManager(monitor_interval=15.0)

# 注册关键设备的回调
def on_critical_device_disconnected(serial):
    if serial == "10ACBE28M70044L":  # 关键设备
        logger.error(f"Critical device disconnected: {serial}")
        # 发送告警、暂停任务等

manager.register_callback('disconnected', on_critical_device_disconnected)
manager.start_monitoring()
```

### 4. 定期检查健康状态

```python
import time

manager = ADBManager()
manager.start_monitoring()

while True:
    # 每分钟检查一次
    time.sleep(60)
    
    unhealthy = []
    for serial, health in manager.get_all_health_status().items():
        if not health.is_healthy():
            unhealthy.append(serial)
    
    if unhealthy:
        logger.warning(f"Unhealthy devices: {unhealthy}")
```

## 故障排查

### 问题 1：设备频繁断开重连

**症状：**
- 设备状态在 CONNECTED 和 DISCONNECTED 之间频繁切换
- 重连次数持续增加

**可能原因：**
1. USB 线缆质量差或接触不良
2. USB 端口供电不足
3. 设备 USB 调试不稳定

**解决方案：**
```bash
# 1. 更换高质量 USB 线缆
# 2. 使用带电源的 USB Hub
# 3. 在设备上重新启用 USB 调试

# 4. 增加监控间隔，减少检查频率
manager = ADBManager(monitor_interval=60.0)

# 5. 检查 ADB 日志
adb logcat | grep -i usb
```

### 问题 2：ADB 命令超时

**症状：**
- 操作经常超时
- 日志显示 "ADB command timed out"

**解决方案：**
```python
# 增加超时时间
manager = ADBManager(health_check_timeout=10)

# 或者在执行特定操作时使用更长的超时
from pixelle_video.device_farm.hardware.adb_observer import _run_adb_command

returncode, stdout, stderr = _run_adb_command(
    ['-s', serial, 'shell', 'command'],
    timeout=30  # 30 秒超时
)
```

### 问题 3：设备显示为 UNAUTHORIZED

**症状：**
- 设备状态为 UNAUTHORIZED
- 无法执行任何 ADB 命令

**解决方案：**
```bash
# 1. 在设备上查看并接受 USB 调试授权提示
# 2. 如果没有提示，撤销所有授权后重新连接
adb kill-server
adb start-server

# 3. 检查设备的 USB 调试设置
# 设置 -> 开发者选项 -> USB 调试
```

### 问题 4：监控线程占用过多资源

**症状：**
- CPU 使用率高
- 程序响应变慢

**解决方案：**
```python
# 增加监控间隔
manager = ADBManager(monitor_interval=60.0)  # 每分钟检查一次

# 或者只在需要时启动监控
manager = ADBManager()
# 不调用 start_monitoring()，只在需要时手动扫描
devices = manager.scan_devices_with_retry()
```

## 集成到现有代码

### 替换现有的 ADB 调用

**之前：**
```python
from pixelle_video.device_farm.hardware import scan_adb_devices, capture_screenshot

# 直接调用，失败就失败
devices = scan_adb_devices()
img = capture_screenshot(serial, "screen.png")
```

**之后：**
```python
from pixelle_video.device_farm.hardware import ADBManager, capture_screenshot

# 使用管理器，自动重试
manager = ADBManager(retry_attempts=3)
devices = manager.scan_devices_with_retry()
img = manager.execute_with_retry(
    serial,
    lambda s: capture_screenshot(s, "screen.png"),
    operation_name="Screenshot"
)
```

### 在 Device Farm 中使用

```python
from pixelle_video.device_farm.hardware import ADBManager
from pixelle_video.device_farm.registry import DeviceRegistry

class EnhancedDeviceFarm:
    def __init__(self):
        self.registry = DeviceRegistry()
        self.adb_manager = ADBManager(
            retry_attempts=3,
            monitor_interval=30.0
        )
        
        # 注册回调
        self.adb_manager.register_callback('disconnected', self._on_device_lost)
        self.adb_manager.register_callback('reconnected', self._on_device_recovered)
        
        # 启动监控
        self.adb_manager.start_monitoring()
    
    def _on_device_lost(self, serial):
        # 标记设备为不可用
        device = self.registry.get_device_by_serial(serial)
        if device:
            logger.warning(f"Device lost: {device.name}")
            # 暂停该设备的任务
    
    def _on_device_recovered(self, serial):
        # 恢复设备
        device = self.registry.get_device_by_serial(serial)
        if device:
            logger.success(f"Device recovered: {device.name}")
            # 恢复该设备的任务
    
    def execute_on_device(self, phone_id, operation):
        device = self.registry.get_device(phone_id)
        if not device:
            raise ValueError(f"Device not found: {phone_id}")
        
        # 使用管理器执行操作（带重试）
        return self.adb_manager.execute_with_retry(
            device.adb_serial,
            operation,
            operation_name=f"Operation on {phone_id}"
        )
```

## 性能考虑

### 监控开销

- **CPU 使用**：监控线程在空闲时几乎不占用 CPU
- **内存使用**：每个设备约 1-2 KB 的健康数据
- **网络/USB**：每次检查执行一次 `adb devices` 命令

### 优化建议

1. **调整监控间隔**：根据需求设置合适的间隔
   - 实时监控：10-15 秒
   - 常规监控：30-60 秒
   - 轻量监控：120+ 秒

2. **选择性监控**：只监控关键设备
   ```python
   # 不启动全局监控
   manager = ADBManager()
   
   # 只在需要时检查特定设备
   health = manager.get_device_with_retry(critical_serial)
   ```

3. **批量操作**：减少单独的 ADB 调用
   ```python
   # 一次扫描获取所有设备
   devices = manager.scan_devices_with_retry()
   
   # 批量处理
   for device in devices:
       # 处理每个设备
       pass
   ```

## 更新日志

### v1.0.0 (2026-05-30)

**新增功能：**
- ✅ ADBManager 核心类
- ✅ 自动重试机制（指数退避）
- ✅ 设备健康监控
- ✅ 自动重连功能
- ✅ 后台监控线程
- ✅ 事件回调系统
- ✅ 上下文管理器支持

**工具脚本：**
- ✅ test_adb_manager.py - 功能测试
- ✅ 04_device_health_monitor.py - 实时监控仪表板
- ✅ 05_enhanced_calibrate.py - 增强校准工具

**文档：**
- ✅ ADB_MANAGER_GUIDE.md - 完整使用指南

## 下一步计划

### 短期（1-2 周）
- [ ] 添加设备性能指标（响应时间、吞吐量）
- [ ] 支持设备分组管理
- [ ] 添加告警通知（邮件、Webhook）
- [ ] Web 界面监控仪表板

### 中期（1-2 月）
- [ ] 设备负载均衡
- [ ] 任务队列与设备调度
- [ ] 历史数据持久化
- [ ] 设备健康趋势分析

### 长期（3+ 月）
- [ ] 分布式设备农场支持
- [ ] 云端设备管理
- [ ] AI 驱动的故障预测
- [ ] 自动化测试集成

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License

---

**文档版本：** 1.0.0  
**最后更新：** 2026-05-30  
**维护者：** Device Farm Team
