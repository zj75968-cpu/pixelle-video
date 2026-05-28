# 配置迁移指南

## 从 Phone Agent 模式迁移到纯硬件模式

### 自动迁移

配置加载器会自动忽略以下废弃字段：
- `phone_agent`
- `distribution`
- `distribution_mode`

### 手动清理（可选）

如果您想手动清理配置文件，删除以下配置块：

```yaml
# 删除这些配置
phone_agent:
  url: ''
  token: ''
  
distribution_mode: legacy

distribution:
  mode: phone_agent
```

### 设备数据迁移

如果您之前使用 Phone Agent 设备，这些设备将不再可用。
请重新注册硬件设备（COM 端口）。

### 恢复 Phone Agent（如需要）

如果未来需要恢复 Phone Agent 功能：

```bash
git log --all --full-history -- "*phone_agent*"
git checkout <commit-hash> -- pixelle_video/services/phone_agent_client.py
```
