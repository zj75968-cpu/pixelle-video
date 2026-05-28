# -*- coding: utf-8 -*-
import os
import random
from PIL import Image, ImageEnhance
from loguru import logger

def pixel_de_duplicate(input_path: str, output_path: str) -> bool:
    """
    像素级消重工具。
    对图片做微弱的像素调整和元数据清空，绕过机器去重检测。
    
    Args:
        input_path: 原始图片路径
        output_path: 处理后的保存路径
        
    Returns:
        bool: 是否处理成功
    """
    if not os.path.exists(input_path):
        logger.error(f"Deduplication failed: source file {input_path} does not exist.")
        return False
        
    try:
        with Image.open(input_path) as img:
            # 1. 稍微裁剪 1-2 像素
            width, height = img.size
            if width > 10 and height > 10:
                crop_pixels = random.randint(1, 2)
                img = img.crop((crop_pixels, crop_pixels, width - crop_pixels, height - crop_pixels))
                width, height = img.size
            
            # 2. 极其微弱的亮度微调 (0.99 - 1.01)
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(random.uniform(0.99, 1.01))
            
            # 3. 极其微弱的对比度微调 (0.99 - 1.01)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(random.uniform(0.99, 1.01))
            
            # 4. 微小的旋转 (如 -0.2 到 0.2 度) 并做无黑边裁剪
            angle = random.uniform(-0.2, 0.2)
            img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
            
            # 5. 再次强行转换成 RGB，清空 EXIF 信息，以 JPEG 保存
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            # 保存时丢弃 exif 字段达到删除元数据指纹目的
            img.save(output_path, "JPEG", quality=95)
            logger.info(f"Deduplication complete. Saved to {output_path} (pixels: {width}x{height})")
            return True
            
    except Exception as e:
        logger.error(f"Error during image pixel deduplication: {e}")
        return False
