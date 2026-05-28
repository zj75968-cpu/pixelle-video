# CH9329 硬件模式纯净化重构设计

**日期**: 2026-05-28  
**作者**: Kiro AI  
**状态**: 已批准

## 一、背景与目标

### 1.1 当前问题

Pixelle-Video 项目在设备控制方面存在三种实现方式的混杂：

1. **ADB 网络控制**：已废弃但代码残留
2. **Phone Agent HTTP 控制**：基于 Termux 的远程控制方案，涉及 24 个文件
3. **CH9329 硬件串口控制**：当前使用的方案

这种混杂导致：
- 配置文件复杂（`distribution_mode` 和 `distribution.mode` 同时存在）
- 代码库臃肿（~150 个 Python 文件，其中 30% 与废弃方案相关）
- 维护成本高（需要理解三套不同的控制逻辑）
- 新开发者困惑（不清楚应该使用哪种方式）

### 1.2 重构目标

**核心原则**：保留 CH9329 硬件串口控制，彻底移除所有其他设备控制方式。

**预期收益**：
- 代码库减少约 27%（从 ~150 个文件降至 ~110 个）
- 配置文件简化 38%（从 96 行降至 ~60 行）
- 测试脚本减少 86%（从 35 个降至 5 个）
- 架构清晰，易于理解和维护

## 二、架构设计

### 2.1 保留的核心组件

```
pixelle_video/
├── services/
│   ├── xhs_publisher.py          # 小红书发布服务（CH9329）
│   ├── device_manager.py         # 设备管理器（简化版）
│   ├── android_device_dispatcher.py  # 硬件调度器（简化版）
│   └── publish_scheduler.py      # 发布调度器
├── utils/
│   ├── ch9329.py                 # CH9329 硬件控制器
│   ├── lsky.py                   # Lsky Pro 图床上传
│   └── dedup.py                  # 图像去重
└── config/
    ├── schema.py                 # 配置模型（简化版）
    └── manager.py                # 配置管理器
```

### 2.2 删除的组件

#### Phone Agent 相关（24 个文件）

```
api/routers/phone_agent.py
pixelle_video/services/phone_agent_client.py
pixelle_video/services/phone_agent_setup.py
scripts/phone_agent.py
scripts/local_agent.py
scripts/setup_termux.sh
scripts/install_termux_boot.sh
scripts/termux_boot_start_agent.sh
scripts/smoke_agent_repair.py
```

#### ADB 相关

```
check_adb.py
```

#### Scratch 测试脚本（保留 5 个，删除 30 个）

**保留**：
- `scratch/check_publish_err.py` - 发布错误诊断
- `scratch/mvp_publish.py` - MVP 发布测试
- `scratch/test_hardware_flow.py` - 硬件流程测试
- `scratch/check_vps_details.py` - VPS 详情检查
- `scratch/diag.sh` - 诊断脚本

**删除**：所有其他 30 个测试脚本（包括所有 phone_agent、termux、adb 相关脚本）

## 三、配置结构重构

### 3.1 删除的配置类

从 `pixelle_video/config/schema.py` 删除：

```python
class PhoneAgentConfig(BaseModel):
    """HTTP Agent configuration for phone control without USB ADB."""
    # 整个类删除（107-129 行）

class RemotePathsConfig(BaseModel):
    """Remote directory paths on target phone"""
    # 整个类删除（180-186 行）

class DistributionConfig(BaseModel):
    """Android Tasker SSH distribution configuration"""
    # 整个类删除（188-197 行）
```

从 `PixelleVideoConfig` 类删除字段：
```python
distribution_mode: str  # 删除
phone_agent: PhoneAgentConfig  # 删除
distribution: DistributionConfig  # 删除
```

### 3.2 简化后的配置结构

**config.yaml**：

```yaml
project_name: Pixelle-Video
admin_password: '5793'

llm:
  api_key: xxx
  base_url: xxx
  model: xxx

post_model_presets:
  post_content:
    api_key: xxx
    base_url: xxx
    model: xxx
  post_image:
    api_key: xxx
    base_url: xxx
    model: xxx
  post_vision:
    api_key: xxx
    base_url: xxx
    model: xxx

comfyui:
  comfyui_url: http://127.0.0.1:8188
  comfyui_api_key: ''
  runninghub_api_key: xxx
  runninghub_consumer_api_key: xxx
  runninghub_base_url: https://www.runninghub.cn
  runninghub_concurrent_limit: 1
  runninghub_instance_type: plus
  show_unavailable_workflows: false
  public_base_url: ''
  tts:
    inference_mode: local
    local:
      voice: zh-CN-YunjianNeural
      speed: 1.2
    comfyui:
      default_workflow: null
  image:
    default_workflow: chatfire/gpt-image-2
    prompt_prefix: Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style
  video:
    default_workflow: runninghub/video_wan2.2.json
    prompt_prefix: ''

template:
  default_template: 1080x1920/default.html

xhs_publish:
  strict_mode: false
  daily_schedule_times:
    - 09:00
    - '12:00'
    - '18:00'
  hardware:
    com_port: COM3
    baudrate: 9600
    unlock_pin: ''
  lsky_pro:
    url: 'http://192.168.1.100/api/v1/upload'
    token: 'Bearer <your-token>'
    album_id: null
  coordinates:
    browser_address_bar_x: 0.5
    browser_address_bar_y: 0.08
    browser_image_x: 0.5
    browser_image_y: 0.5
    browser_save_btn_x: 0.5
    browser_save_btn_y: 0.85
    xhs_icon_x: 0.3
    xhs_icon_y: 0.5
    xhs_add_btn_x: 0.5
    xhs_add_btn_y: 0.95
    xhs_first_album_x: 0.25
    xhs_first_album_y: 0.25
    xhs_next_btn_x: 0.85
    xhs_next_btn_y: 0.08
    xhs_publish_btn_x: 0.5
    xhs_publish_btn_y: 0.92
```

## 四、服务层简化

### 4.1 android_device_dispatcher.py

**重构前**：包含多种分发模式的复杂逻辑

**重构后**：

```python
# pixelle_video/services/android_device_dispatcher.py
"""
硬件设备调度器（CH9329 串口控制）
"""
import asyncio
from typing import Callable
from loguru import logger
from pixelle_video.services.publish_scheduler import PublishJob
from pixelle_video.services.xhs_publisher import XHSPublisher

class DistributionAdapter:
    """
    发帖分发器（CH9329 物理硬件串口控制）。
    """
    @classmethod
    def get_mode(cls) -> str:
        """获取当前系统的发帖分发模式"""
        return "hardware"

    async def execute_job(
        self,
        job: PublishJob,
        progress_callback: Callable[[str], None]
    ) -> bool:
        """
        使用硬件直控模式执行发帖任务。
        
        Args:
            job: 待执行的任务实例，其中 job.serial 应为硬件 COM 口名（例如 "COM3"）
            progress_callback: 进度汇报回调
            
        Returns:
            True 执行成功，False 失败
        """
        logger.info(f"Executing job {job.job_id} using hardware mode. COM port: {job.serial}")
        
        publisher = XHSPublisher(serial=job.serial, job_id=job.job_id)
        
        if job.kind == "video":
            success = await publisher.publish_video(
                video_path=job.video_path or "",
                title=job.title,
                body=job.body,
                hashtags=job.hashtags,
                progress_callback=progress_callback,
            )
        else:
            success = await publisher.publish(
                images=job.images,
                title=job.title,
                body=job.body,
                hashtags=job.hashtags,
                progress_callback=progress_callback,
            )
            
        return success
```

### 4.2 device_manager.py

**保留功能**：
- 设备注册（serial 代表 COM 端口名，如 "COM3"）
- 设备状态管理
- 连接状态检查

**删除功能**：
- 所有 ADB 相关方法
- WiFi 连接相关方法
- `adb_available` 属性

**简化后的接口**：

```python
class DeviceManager:
    def add_device(self, serial: str, name: str, theme: str, notes: str) -> Device:
        """注册新设备（serial 为 COM 端口名）"""
        
    def remove_device(self, serial: str) -> bool:
        """移除设备"""
        
    def get_all(self) -> List[Device]:
        """获取所有设备"""
        
    def get_device(self, serial: str) -> Optional[Device]:
        """获取指定设备"""
```

## 五、API 路由清理

### 5.1 删除 phone_agent 路由

**从 `api/routers/__init__.py` 删除**：

```python
# 删除这一行
from api.routers.phone_agent import router as phone_agent_router

# 从 __all__ 中删除
__all__ = [
    # ... 其他路由
    # "phone_agent_router",  # 删除这一行
]
```

**从 `api/app.py` 删除**：

```python
# 删除这一行
app.include_router(phone_agent_router)
```

### 5.2 简化 devices 路由

**api/routers/devices.py** 已经重构为硬件模式，保持不变：

```python
@router.post("/connect-wifi", response_model=DeviceResponse)
async def connect_wifi(body: DeviceConnectWiFiRequest):
    """Connect WiFi is not supported in hardware mode."""
    raise HTTPException(
        status_code=501,
        detail="WiFi ADB connection is not supported in CH9329 hardware control mode."
    )

@router.get("/diagnose/status")
async def diagnose_adb():
    """Diagnose serial status."""
    return {
        "adb_available": False,
        "hardware_mode": True,
        "com_port": com_port,
        # ...
    }
```

## 六、Web UI 清理

### 6.1 Settings 页面（web/views/9_Settings.py）

**删除内容**：

1. **Phone Agent 状态卡片**（第 159-190 行）：
```python
# 删除整个 Phone Agent 状态检查和显示逻辑
pa_url = cfg.phone_agent.url.strip()
# ... 
_status_card("Phone Agent（HTTP）", pa_ok, pa_detail)
```

2. **Phone Agent 配置区域**（第 252-378 行）：
```python
# 删除整个 "6. Phone Agent 配置" 区域
with st.expander("📱 6. Phone Agent 配置", expanded=False):
    # ... 所有 phone_agent 配置 UI
```

**保留内容**：
- LLM 配置
- ComfyUI 配置
- 小红书发布配置（硬件部分）
- Lsky Pro 配置

### 6.2 Publish 页面（web/views/4_Publish.py）

**删除内容**：
- 所有 phone_agent 相关的设备选择 UI
- Termux 配置相关的提示和链接

**保留内容**：
- 硬件设备选择（COM 端口）
- 发布任务管理
- 调度配置

### 6.3 Post 页面（web/views/_post.py）

**删除内容**：
- Phone Agent 相关的发布选项
- Termux 设备状态显示

## 七、数据迁移

### 7.1 设备数据迁移

**当前设备数据格式**（可能包含 phone_agent 设备）：
```json
{
  "serial": "phone_agent:abc123",
  "name": "iQOO Phone",
  "theme": "美食",
  "connected": true
}
```

**迁移后格式**（仅硬件设备）：
```json
{
  "serial": "COM3",
  "name": "Device 1",
  "theme": "美食",
  "connected": true
}
```

**迁移策略**：
- 删除所有 `serial` 以 `phone_agent:` 开头的设备记录
- 保留 `serial` 为 COM 端口名的设备记录

### 7.2 配置文件迁移

**自动迁移脚本**（在首次启动时执行）：

```python
# pixelle_video/config/migration.py
def migrate_config_v1_to_v2(config_dict: dict) -> dict:
    """
    迁移配置文件：移除 phone_agent 和 distribution 相关配置
    """
    # 删除废弃字段
    config_dict.pop("phone_agent", None)
    config_dict.pop("distribution", None)
    config_dict.pop("distribution_mode", None)
    
    return config_dict
```

## 八、测试策略

### 8.1 回归测试

**测试范围**：
1. 设备管理 API（注册、删除、列表）
2. 发布流程（图文、视频）
3. CH9329 硬件控制（点击、输入、截图）
4. Lsky Pro 图床上传
5. 配置加载和验证

**测试用例**：
```python
# tests/test_hardware_publish.py
async def test_publish_image_post():
    """测试图文发布流程"""
    publisher = XHSPublisher(serial="COM3", job_id="test_001")
    success = await publisher.publish(
        images=["test_image.jpg"],
        title="测试标题",
        body="测试内容",
        hashtags=["测试"]
    )
    assert success is True

async def test_ch9329_control():
    """测试 CH9329 硬件控制"""
    controller = CH9329Controller(port="COM3")
    assert controller.connect() is True
    assert controller.click(0.5, 0.5) is True
    controller.disconnect()
```

### 8.2 手动测试清单

- [ ] Web UI 启动正常
- [ ] Settings 页面不显示 Phone Agent 配置
- [ ] 设备管理页面正常工作
- [ ] 发布任务可以正常创建和执行
- [ ] CH9329 硬件控制正常
- [ ] 配置文件加载无错误

## 九、实施计划

### 9.1 实施步骤

**阶段 1：准备工作**（1 小时）
1. 创建新分支 `refactor/ch9329-cleanup`
2. 备份当前配置文件
3. 运行现有测试确保基线

**阶段 2：删除文件**（1 小时）
1. 删除 Phone Agent 相关文件（24 个）
2. 删除 ADB 相关文件
3. 删除 Scratch 测试脚本（30 个）
4. 删除 API 路由引用

**阶段 3：配置重构**（1 小时）
1. 修改 `config/schema.py`
2. 更新 `config.yaml`
3. 实现配置迁移逻辑
4. 更新配置加载器

**阶段 4：服务层简化**（1.5 小时）
1. 简化 `android_device_dispatcher.py`
2. 简化 `device_manager.py`
3. 更新 `xhs_publisher.py` 引用
4. 删除未使用的导入

**阶段 5：Web UI 清理**（1 小时）
1. 修改 `web/views/9_Settings.py`
2. 修改 `web/views/4_Publish.py`
3. 修改 `web/views/_post.py`
4. 测试 UI 功能

**阶段 6：测试与验证**（1.5 小时）
1. 运行单元测试
2. 手动测试发布流程
3. 验证配置加载
4. 检查日志无错误

**阶段 7：文档更新**（0.5 小时）
1. 更新 README.md
2. 更新配置文档
3. 添加迁移说明

**总计**：约 7.5 小时

### 9.2 回滚计划

如果重构出现问题：

```bash
# 回滚到重构前
git checkout main
git branch -D refactor/ch9329-cleanup

# 或者从 Git 历史恢复特定文件
git checkout <commit-hash> -- <file-path>
```

## 十、风险评估

### 10.1 高风险项

**风险**：删除文件后发现有未知依赖  
**缓解**：
- 使用 IDE 的"查找引用"功能检查所有删除文件的引用
- 分阶段删除，每次删除后运行测试
- 保留 Git 历史，可随时恢复

**风险**：配置迁移失败导致用户配置丢失  
**缓解**：
- 在迁移前自动备份 `config.yaml`
- 提供手动迁移指南
- 配置加载失败时使用默认值

### 10.2 中风险项

**风险**：Web UI 删除后影响用户体验  
**缓解**：
- 保留核心功能（设备管理、发布任务）
- 提供清晰的错误提示
- 更新用户文档

**风险**：测试覆盖不足  
**缓解**：
- 编写针对性的回归测试
- 手动测试关键流程
- 在测试环境先验证

## 十一、成功标准

重构完成后应满足：

1. **功能完整性**：
   - ✅ CH9329 硬件发布功能正常
   - ✅ 设备管理功能正常
   - ✅ Web UI 正常运行
   - ✅ API 接口正常响应

2. **代码质量**：
   - ✅ 无未使用的导入
   - ✅ 无死代码
   - ✅ 配置结构清晰
   - ✅ 代码库减少 27%

3. **文档完整性**：
   - ✅ README 更新
   - ✅ 配置文档更新
   - ✅ 迁移指南完整

4. **测试通过**：
   - ✅ 所有单元测试通过
   - ✅ 手动测试清单完成
   - ✅ 无回归问题

## 十二、未来扩展

如果未来需要支持其他设备控制方式：

### 12.1 适配器模式

创建统一的设备控制接口：

```python
# pixelle_video/adapters/base.py
from abc import ABC, abstractmethod

class DeviceControlAdapter(ABC):
    @abstractmethod
    async def publish(self, images, title, body, hashtags) -> bool:
        """发布内容到平台"""
        pass
    
    @abstractmethod
    def connect(self) -> bool:
        """连接设备"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """断开设备"""
        pass

# pixelle_video/adapters/ch9329.py
class CH9329Adapter(DeviceControlAdapter):
    """CH9329 硬件适配器"""
    # 实现接口

# pixelle_video/adapters/phone_agent.py (未来可选)
class PhoneAgentAdapter(DeviceControlAdapter):
    """Phone Agent HTTP 适配器"""
    # 实现接口
```

### 12.2 配置驱动

通过配置选择适配器：

```yaml
xhs_publish:
  control_mode: hardware  # hardware | phone_agent | adb
  hardware:
    com_port: COM3
  # phone_agent:  # 未来可选
  #   url: xxx
```

### 12.3 恢复步骤

从 Git 历史恢复 Phone Agent：

```bash
# 1. 查找删除的文件
git log --all --full-history -- "*phone_agent*"

# 2. 恢复文件
git checkout <commit-hash> -- pixelle_video/services/phone_agent_client.py

# 3. 创建适配器
# 按照适配器模式重新集成
```

## 十三、附录

### 13.1 完整删除文件清单

```
# Phone Agent 相关（24 个文件）
api/routers/phone_agent.py
pixelle_video/services/phone_agent_client.py
pixelle_video/services/phone_agent_setup.py
scripts/phone_agent.py
scripts/local_agent.py
scripts/setup_termux.sh
scripts/install_termux_boot.sh
scripts/termux_boot_start_agent.sh
scripts/smoke_agent_repair.py

# ADB 相关
check_adb.py

# Scratch 测试脚本（删除 30 个，保留 5 个）
scratch/local_publish_test.py
scratch/download_and_push_cf.py
scratch/download_win_cf.py
scratch/test_agent_dispatch.py
scratch/publish_xhs_demo.py
scratch/test_comment_and_delete.py
scratch/dump_detail_hierarchy.py
scratch/test_dots_menu.py
scratch/test_grafted_pipeline.py
scratch/search_xml.py
scratch/test_e2e_grafted.py
scratch/view_last_lines.py
scratch/check_running_processes.py
scratch/clear_test_jobs.py
scratch/print_queue.py
scratch/check_vps_services.py
scratch/test_vps_http.py
scratch/test_vps_ports.py
scratch/diagnose_quick.py
scratch/check_registered_url.py
scratch/check_agent_registration.py
scratch/check_phone_processes.py
scratch/vps_diagnose.py
scratch/debug_phone_termux.py
scratch/phone_force_wake.py
scratch/setup_iqoo_agent.py
scratch/deploy_and_clear.py
scratch/check_vps_network.py
scratch/check_vps_nginx_config.py
scratch/diagnose_vps_nginx.py
scratch/deploy_unbuffered.py
```

### 13.2 保留的 Scratch 脚本

```
scratch/check_publish_err.py      # 发布错误诊断
scratch/mvp_publish.py             # MVP 发布测试
scratch/test_hardware_flow.py     # 硬件流程测试
scratch/check_vps_details.py      # VPS 详情检查
scratch/diag.sh                    # 诊断脚本
```

### 13.3 配置字段映射

| 删除前 | 删除后 | 说明 |
|--------|--------|------|
| `distribution_mode` | 删除 | 不再需要模式选择 |
| `phone_agent.*` | 删除 | Phone Agent 配置全部删除 |
| `distribution.*` | 删除 | 分发配置全部删除 |
| `xhs_publish.hardware.*` | 保留 | CH9329 硬件配置 |
| `xhs_publish.lsky_pro.*` | 保留 | Lsky Pro 图床配置 |
| `xhs_publish.coordinates.*` | 保留 | 坐标配置 |

---

**设计完成日期**: 2026-05-28  
**预计实施时间**: 7.5 小时  
**预期代码减少**: 27%（约 40 个文件）
