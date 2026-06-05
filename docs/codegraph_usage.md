# CodeGraph 使用指南

## 🎯 CodeGraph 是什么？

CodeGraph 是一个为 AI 编程助手提供**语义代码智能**的工具，可以：
- 🔍 **减少 35% 成本** - 更少的 token 消耗
- ⚡ **减少 70% 工具调用** - 更快的响应速度
- 💻 **100% 本地运行** - 数据不离开你的电脑

## 📊 当前项目索引状态

```
项目: F:\codex project\小红书
文件数: 188 个
节点数: 2,967 个 (函数、类、变量等)
边数: 6,291 个 (依赖关系)
数据库: 6.75 MB
```

## 🚀 常用命令

### 1. 查询符号
```bash
codegraph query "publish"
```
搜索所有包含 "publish" 的函数、类、变量

### 2. 查看文件结构
```bash
codegraph files
```
显示项目文件树

### 3. 查找调用者
```bash
codegraph callers "publish_video"
```
找出所有调用 `publish_video` 的地方

### 4. 查找被调用者
```bash
codegraph callees "publish_video"
```
找出 `publish_video` 调用了哪些函数

### 5. 影响分析
```bash
codegraph impact "CH9329Controller"
```
分析修改 `CH9329Controller` 会影响哪些代码

### 6. 测试影响分析
```bash
codegraph affected api/routers/publish.py
```
找出修改 `publish.py` 后需要运行哪些测试

### 7. 同步更新
```bash
codegraph sync
```
增量更新索引（只索引修改过的文件）

### 8. 重新索引
```bash
codegraph index
```
完全重新索引整个项目

### 9. 查看状态
```bash
codegraph status
```
查看索引统计信息

## 🔧 在 Claude Code 中使用

安装完成后，重启 Claude Code，CodeGraph 会作为 MCP 服务器自动加载。

你可以直接问 Claude：
- "查找所有调用 publish_scheduler 的地方"
- "分析修改 CH9329Controller 的影响范围"
- "这个项目的文件结构是什么样的？"

Claude 会自动使用 CodeGraph 提供更准确、更快速的答案。

## 📝 项目特定查询示例

### 查找发布相关功能
```bash
codegraph query "publish" --kind function
```

### 查找 CH9329 设备控制
```bash
codegraph query "CH9329" --kind class
```

### 查找 API 路由
```bash
codegraph query "router" --kind route
```

### 分析 Android 设备调度器的影响
```bash
codegraph impact "AndroidDeviceDispatcher"
```

## 🔄 保持索引更新

每次修改代码后运行：
```bash
codegraph sync
```

或者在 git hook 中自动运行（可选）。

## 📚 更多信息

- 官方文档: https://colbymchenry.github.io/codegraph/
- GitHub: https://github.com/colbymchenry/codegraph
- 当前版本: 0.9.6

## 🎨 节点类型统计

当前项目包含：
- import: 958 个
- variable: 641 个
- function: 560 个
- method: 421 个
- file: 181 个
- class: 161 个
- route: 45 个

## 🌐 支持的语言

当前项目：
- Python: 179 个文件
- YAML: 7 个文件
- XML: 2 个文件
