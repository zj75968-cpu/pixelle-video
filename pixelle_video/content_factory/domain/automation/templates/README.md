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
