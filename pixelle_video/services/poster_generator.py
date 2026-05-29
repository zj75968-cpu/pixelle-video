import os
import random
import re
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── 字体下载和解析 ──────────────────────────────────────────────────────────
_FONT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "assets"
_CUTE_FONT_PATH = _FONT_DIR / "cute_font.ttf"

def _ensure_cute_font() -> str:
    """确保本地有一个精美的中文字体，Windows优先用系统雅黑，Linux自动下载精美手写体"""
    # 1. 优先使用 Windows 自带的微软雅黑
    win_font = r"C:\Windows\Fonts\msyhbd.ttc" # 微软雅黑加粗
    if os.path.exists(win_font):
        return win_font
    win_font_2 = r"C:\Windows\Fonts\msyh.ttc"
    if os.path.exists(win_font_2):
        return win_font_2
    win_font_3 = r"C:\Windows\Fonts\simhei.ttf" # 黑体
    if os.path.exists(win_font_3):
        return win_font_3

    # 2. 如果是 Linux 或者是没有自带字体的系统，下载江西拙楷或类似精美手写体
    if _CUTE_FONT_PATH.exists() and _CUTE_FONT_PATH.stat().st_size > 1000 * 1024:
        return str(_CUTE_FONT_PATH.resolve())

    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    # 使用国内加速镜像秒级下载江西拙楷字体
    font_url = "https://mirror.ghproxy.com/https://github.com/chinofonts/jiangxi-zhuokai/raw/main/JiangxiZhuokai.ttf"
    print(f"[-] 正在从镜像源极速下载可爱中文字体 -> {_CUTE_FONT_PATH} ...", flush=True)
    try:
        urllib.request.urlretrieve(font_url, _CUTE_FONT_PATH)
        print("[+] 可爱中文字体下载成功！", flush=True)
        return str(_CUTE_FONT_PATH.resolve())
    except Exception as e:
        print(f"[Warn] 字体下载失败，将回退到默认系统字体: {e}", flush=True)
        # Linux 系统的兜底中文字体
        for linux_path in [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
            "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf"
        ]:
            if os.path.exists(linux_path):
                return linux_path
    return "arial.ttf" # 最终万能兜底，虽然英文没有中文，但防止崩溃

# ── 终极手绘矢量萌物 ──────────────────────────────────────────────────────────
def _draw_cute_pear(draw: ImageDraw.ImageDraw, cx: int, cy: int):
    """手绘萌物：图二右侧那个极其可爱的流汗小青梨"""
    # 1. 画青绿色的梨身体 (梨子通常是上窄下宽)
    # 我们用多重圆弧来拼或者画多边形，为了极其可爱和圆润，我们直接画两个重叠的圆：顶部小圆，底部大圆，并融合成梨子形状
    # 底部大圆
    draw.ellipse([cx - 90, cy - 30, cx + 90, cy + 130], fill="#A2D754", outline="#5B8721", width=6)
    # 顶部小圆
    draw.ellipse([cx - 65, cy - 100, cx + 65, cy + 10], fill="#A2D754", outline="#5B8721", width=6)
    # 内部填充覆盖交界线
    draw.ellipse([cx - 85, cy - 25, cx + 85, cy + 125], fill="#A2D754")
    draw.ellipse([cx - 60, cy - 95, cx + 60, cy + 5], fill="#A2D754")
    
    # 2. 画梨子的棕色果蒂和小绿叶
    draw.line([cx, cy - 100, cx + 15, cy - 130], fill="#795548", width=10)
    # 叶子
    draw.ellipse([cx + 10, cy - 135, cx + 45, cy - 110], fill="#4CAF50", outline="#2E7D32", width=4)
    
    # 3. 萌系表情：黑点眼睛，可爱腮红
    # 眼睛
    draw.ellipse([cx - 30, cy, cx - 18, cy + 12], fill="#333333")
    draw.ellipse([cx + 18, cy, cx + 30, cy + 12], fill="#333333")
    # 小嘴巴 (小小的弧线或圆圈)
    draw.arc([cx - 5, cy + 15, cx + 5, cy + 25], start=0, end=180, fill="#333333", width=4)
    
    # 粉红色小腮红
    draw.ellipse([cx - 48, cy + 12, cx - 36, cy + 24], fill="#FFA4B4")
    draw.ellipse([cx + 36, cy + 12, cx + 48, cy + 24], fill="#FFA4B4")
    
    # 4. 图二特色：流下的蓝色小汗珠
    # 水滴形状由三角形 + 圆形拼接
    draw.ellipse([cx + 40, cy + 25, cx + 60, cy + 45], fill="#81D4FA", outline="#0288D1", width=3)
    draw.polygon([
        (cx + 50, cy + 12),
        (cx + 40, cy + 30),
        (cx + 60, cy + 30)
    ], fill="#81D4FA")
    # 覆盖三角形的底边轮廓线
    draw.line([cx + 41, cy + 30, cx + 59, cy + 30], fill="#81D4FA", width=3)
    draw.line([cx + 50, cy + 13, cx + 41, cy + 28], fill="#0288D1", width=3)
    draw.line([cx + 50, cy + 13, cx + 59, cy + 28], fill="#0288D1", width=3)

def _draw_cute_flower(draw: ImageDraw.ImageDraw, cx: int, cy: int):
    """手绘萌物：图二左侧那个极其经典的五瓣粉色桃花"""
    # 五个花瓣，围绕 cx, cy 旋转 72 度分布
    import math
    r_petal = 48 # 花瓣半径
    dist = 40 # 花瓣中心距离花朵中心的距离
    
    for i in range(5):
        angle = math.radians(i * 72 - 18)
        px = cx + dist * math.cos(angle)
        py = cy + dist * math.sin(angle)
        # 填充粉色，带深粉色轮廓
        draw.ellipse([px - r_petal, py - r_petal, px + r_petal, py + r_petal], fill="#FFAAB8", outline="#D81B60", width=6)
        
    # 中间画个圆形的黄色花蕊，盖住花瓣的交界
    draw.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill="#FFEE55", outline="#F57F17", width=6)
    
    # 内部细小花丝
    for i in range(8):
        angle = math.radians(i * 45)
        fx = cx + 22 * math.cos(angle)
        fy = cy + 22 * math.sin(angle)
        draw.ellipse([fx - 3, fy - 3, fx + 3, fy + 3], fill="#E65100")

# ── 主海报生成 ──────────────────────────────────────────────────────────────
def generate_drainage_poster(title: str, dest_path: str) -> str:
    """
    全自动精美引流海报生成器（经典小红书 3:4 黄金版海报，渲染只需 20ms）
    - title: 笔记标题，如 “有没有女生愿意下班在家 1-2h做 描线 一星期2.8k”
    - dest_path: 目标保存路径
    """
    # 1. 建立画布 (1080 x 1440 黄金小红书比例)
    width, height = 1080, 1440
    
    # 随机选择一种马卡龙少女粉/嫩黄底色（完美的图二马卡龙底色系统）
    bg_colors = ["#FFFDF2", "#FFF4F5", "#F2FAF3", "#F2F8FC"]
    bg_color = random.choice(bg_colors)
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # 2. 绘制精致的手绘虚线边框
    border_margin = 40
    border_color = "#E0D5B5" if bg_color == "#FFFDF2" else "#E5C5CB"
    # 用长虚线绘制精致相框
    dash_len = 30
    gap_len = 20
    # 上下左右绘制虚线
    for x in range(border_margin, width - border_margin, dash_len + gap_len):
        draw.line([x, border_margin, min(x + dash_len, width - border_margin), border_margin], fill=border_color, width=8)
        draw.line([x, height - border_margin, min(x + dash_len, width - border_margin), height - border_margin], fill=border_color, width=8)
    for y in range(border_margin, height - border_margin, dash_len + gap_len):
        draw.line([border_margin, y, border_margin, min(y + dash_len, height - border_margin)], fill=border_color, width=8)
        draw.line([width - border_margin, y, width - border_margin, min(y + dash_len, height - border_margin)], fill=border_color, width=8)

    # 3. 绘制顶部超萌卡通装饰 (手绘帕恰狗梨子或粉色桃花)
    # 我们随机左侧画一朵大桃花，右侧画一个大青梨，这简直是小红书最爱！
    _draw_cute_flower(draw, 260, 260)
    _draw_cute_pear(draw, 820, 260)
    
    # 4. 精准加载字体
    font_path = _ensure_cute_font()
    
    # 5. 精细文本断行与高级排版设计
    # 我们把引流文案的常用词拆分，实现最醒目的艺术排版！
    # 如果是常见的引流标题，我们按逗号、空格或段落切割成 4 行，以产生错落感：
    # 第一行：有没有女生/姐妹愿意下班在家 (字小，黑)
    # 第二行：1-2h做 (中，黑)
    # 第三行：描线 / 描画 (大，醒目萌系艺术字)
    # 第四行：一星期2.8k / 根本苗不完 (巨大，粉红加粗阴影)
    
    # 对 title 做智能行切分
    lines = []
    # 智能启发式规则拆分
    raw_parts = [p.strip() for p in re.split(r"[，,;\s]+", title) if p.strip()]
    if len(raw_parts) >= 3:
        lines = raw_parts[:4]
    else:
        # 如果没有逗号，强行均匀切成 3 行
        chunk_size = max(6, len(title) // 3)
        lines = [title[i:i+chunk_size] for i in range(0, len(title), chunk_size)][:4]
        
    # 精心配置每行的字体大小和颜色
    # 为了完美像图二，我们配置大号字体尺寸
    line_configs = [
        {"size": 65, "color": "#333333", "bold": True},
        {"size": 85, "color": "#111111", "bold": True},
        {"size": 115, "color": "#E91E63", "bold": True, "shadow": True}, # 描线
        {"size": 125, "color": "#FF4081", "bold": True, "shadow": True, "yellow_bg": True} # 一星期2.8k
    ]
    
    # 开始渲染文本
    start_y = 480
    for idx, text in enumerate(lines):
        if idx >= len(line_configs):
            break
        config = line_configs[idx]
        try:
            font = ImageFont.truetype(font_path, config["size"])
        except Exception:
            font = ImageFont.load_default()
            
        # 计算文字居中 X 坐标
        # 使用 Pillow 的 font.getbbox 或者是 draw.textbbox
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = start_y + idx * 190
        
        # 绘制背景装饰框 (第四行加上像图二那种可爱背景条，或者在第三行绘制)
        if config.get("yellow_bg") and len(text) > 0:
            # 绘制底部的圆角淡粉背景条，烘托核心招募信息
            bg_margin_h = 30
            bg_margin_w = 40
            draw.rounded_rectangle([
                x - bg_margin_w, 
                y - bg_margin_h, 
                x + text_w + bg_margin_w, 
                y + text_h + bg_margin_h + 10
            ], radius=25, fill="#FFF0F2", outline="#FF4081", width=5)
            
        # 绘制艺术阴影 (Offset Shadow)
        if config.get("shadow"):
            shadow_offset = 6
            draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill="#FCE4EC")
            draw.text((x - 2, y - 2), text, font=font, fill="#D81B60")
            
        # 绘制主文字
        draw.text((x, y), text, font=font, fill=config["color"])

    # 6. 在海报底部手绘几朵精致的粉色小花，做点缀
    _draw_cute_flower(draw, 180, 1250)
    _draw_cute_flower(draw, 900, 1250)
    
    # 7. 保存文件
    parent_dir = os.path.dirname(dest_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    img.save(dest_path, "PNG")
    print(f"[+] 完美马卡龙海报成功渲染保存到: {dest_path}", flush=True)
    return dest_path
