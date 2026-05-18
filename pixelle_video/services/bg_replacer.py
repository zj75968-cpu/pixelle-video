"""背景色替换 - 检测图片背景颜色并替换为指定颜色。

策略：采样图片四角像素估算背景色，对在容差范围内的像素批量替换。
依赖：Pillow, numpy（项目已有）
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from loguru import logger

# ─── 类型别名 ─────────────────────────────────────────────────────────────────
RGB = tuple[int, int, int]


# ─── 背景色检测 ───────────────────────────────────────────────────────────────

def detect_background_color(image_path: str, sample_radius: int = 8) -> RGB:
    """
    通过采样四角像素估算图片背景色。

    Args:
        image_path: 图片路径
        sample_radius: 角落采样像素宽度

    Returns:
        (R, G, B) 元组
    """
    import numpy as np
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]
    r = min(sample_radius, h // 4, w // 4)

    corners = [
        arr[:r, :r],       # 左上
        arr[:r, -r:],      # 右上
        arr[-r:, :r],      # 左下
        arr[-r:, -r:],     # 右下
    ]
    all_pixels = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    median = np.median(all_pixels, axis=0).astype(int)
    return (int(median[0]), int(median[1]), int(median[2]))


# ─── 背景色替换 ───────────────────────────────────────────────────────────────

def replace_background_color(
    image_path: str,
    new_color: RGB,
    tolerance: int = 40,
    output_path: str | None = None,
) -> str:
    """
    将图片背景色替换为指定颜色。

    Args:
        image_path: 源图片路径
        new_color: 新背景色 (R, G, B)
        tolerance: 颜色距离容差 (0~255)，越大替换范围越广
        output_path: 输出路径，None 则自动命名（原文件名加 _bg 后缀）

    Returns:
        修改后图片的路径
    """
    import numpy as np
    from PIL import Image

    if output_path is None:
        p = Path(image_path)
        output_path = str(p.parent / f"{p.stem}_bg{p.suffix}")

    img = Image.open(image_path).convert("RGBA")
    arr = np.array(img, dtype=np.float32)

    # 检测背景色
    bg_color = detect_background_color(image_path)
    logger.debug(
        f"检测背景色 RGB{bg_color} → 替换为 RGB{new_color}  (容差={tolerance})"
    )

    # 计算每个像素与背景色的欧氏距离
    rgb = arr[:, :, :3]
    bg = np.array(bg_color, dtype=np.float32)
    dist = np.sqrt(np.sum((rgb - bg) ** 2, axis=2))

    # 构建替换掩码并应用
    mask = dist <= tolerance
    new_rgb = np.array(new_color, dtype=np.float32)
    arr[mask, 0] = new_rgb[0]
    arr[mask, 1] = new_rgb[1]
    arr[mask, 2] = new_rgb[2]
    arr[mask, 3] = 255  # 不透明

    result = Image.fromarray(arr.astype("uint8"), "RGBA").convert("RGB")
    result.save(output_path, quality=95)
    logger.info(f"背景替换完成: {Path(image_path).name} → {Path(output_path).name}")
    return output_path


# ─── 批量处理 ─────────────────────────────────────────────────────────────────

def apply_bg_to_images(
    image_paths: list[str],
    new_color: RGB,
    tolerance: int = 40,
    output_dir: str | None = None,
) -> list[str]:
    """
    批量替换多张图片的背景色。

    Args:
        image_paths: 源图片路径列表
        new_color: 新背景色 (R, G, B)
        tolerance: 颜色容差
        output_dir: 输出目录，None 则同目录输出

    Returns:
        处理后的图片路径列表（处理失败则保留原路径）
    """
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    results: list[str] = []
    for path in image_paths:
        try:
            if output_dir:
                p = Path(path)
                out = str(Path(output_dir) / f"{p.stem}_bg{p.suffix}")
            else:
                out = None
            results.append(replace_background_color(path, new_color, tolerance, out))
        except Exception as e:
            logger.error(f"背景替换失败 {path}: {e}")
            results.append(path)  # 失败则保留原图

    return results


# ─── 颜色工具 ─────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> RGB:
    """将 #RRGGBB 十六进制字符串转换为 (R, G, B) 元组。"""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def rgb_to_hex(rgb: RGB) -> str:
    """将 (R, G, B) 元组转换为 #RRGGBB 字符串。"""
    return "#{:02X}{:02X}{:02X}".format(*rgb)
