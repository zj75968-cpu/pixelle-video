# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Generate complex 2D animated MP4 samples for local demos.

This renderer is for environments where ComfyUI video models are not installed
yet. It produces scene-level animation rather than simple moving text cards:
characters, rooms, props, camera-like parallax, transitions, and beat-synced
actions are drawn frame by frame and encoded with FFmpeg.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import edge_tts
from edge_tts.exceptions import NoAudioReceived
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output"

WIDTH = 720
HEIGHT = 1280
FPS = 15


@dataclass(frozen=True)
class SampleSpec:
    title: str
    beats: tuple[str, str, str]
    scenario: str
    palette: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
    voice: str = "zh-CN-YunjianNeural"
    speed: str = "+8%"

    @property
    def narration(self) -> str:
        return f"{self.title}。第一，{self.beats[0]}。第二，{self.beats[1]}。第三，{self.beats[2]}。"


SAMPLES: tuple[SampleSpec, ...] = (
    SampleSpec(
        "三个提升专注力的小方法",
        ("先关掉最吵的一个提醒", "只做二十五分钟的小冲刺", "结束后写下下一步"),
        "focus",
        ((15, 23, 42), (32, 146, 170), (245, 203, 92)),
    ),
    SampleSpec(
        "睡前十分钟整理法",
        ("把明天最重要的一件事写下来", "把桌面只留三样东西", "给手机设置固定停用时间"),
        "bedtime",
        ((21, 31, 56), (121, 91, 173), (255, 213, 128)),
        voice="zh-CN-XiaoxiaoNeural",
    ),
    SampleSpec(
        "一分钟快速减压",
        ("呼气比吸气多两秒", "把肩膀向后慢慢放下", "只观察一个真实的声音"),
        "breathing",
        ((6, 36, 67), (41, 157, 143), (232, 196, 106)),
        voice="zh-CN-YunxiNeural",
    ),
    SampleSpec(
        "让早晨更顺的三个动作",
        ("起床先喝一杯温水", "打开窗帘让光进来", "把第一件小事立刻完成"),
        "morning",
        ((25, 63, 96), (252, 164, 84), (255, 236, 179)),
        voice="zh-CN-YunyangNeural",
    ),
    SampleSpec(
        "低成本提升审美",
        ("每天收集三张喜欢的图", "说清楚喜欢它的原因", "模仿一处构图或配色"),
        "gallery",
        ((20, 24, 45), (118, 90, 230), (255, 218, 94)),
        voice="zh-CN-XiaoyiNeural",
    ),
    SampleSpec(
        "新手学习 AI 工具的顺序",
        ("先学会描述目标", "再固定一个常用模板", "最后建立自己的案例库"),
        "ai_lab",
        ((8, 18, 42), (0, 188, 212), (160, 255, 130)),
    ),
    SampleSpec(
        "拖延时先做这三步",
        ("把任务缩小到两分钟", "把材料放到手边", "开始前只承诺做第一步"),
        "procrastination",
        ((32, 26, 54), (245, 111, 91), (255, 212, 128)),
        voice="zh-CN-YunyeNeural",
    ),
    SampleSpec(
        "写作没灵感怎么办",
        ("先列问题，不急着写答案", "用一句话写出核心观点", "把例子放到观点后面"),
        "writing",
        ((25, 35, 52), (80, 150, 205), (238, 107, 77)),
        voice="zh-CN-liaoning-XiaobeiNeural",
    ),
    SampleSpec(
        "工作复盘的三句话",
        ("今天真正推进了什么", "哪里卡住了，原因是什么", "明天先从哪一步开始"),
        "review",
        ((8, 22, 48), (65, 124, 158), (242, 199, 86)),
        voice="zh-CN-YunjianNeural",
    ),
    SampleSpec(
        "保持长期行动的办法",
        ("把目标变成固定时间", "允许每天只做最低版本", "每周复盘一次节奏"),
        "habit",
        ((12, 35, 65), (72, 149, 239), (255, 224, 102)),
        voice="zh-CN-XiaoxiaoNeural",
    ),
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 1.0 if x >= edge1 else 0.0
    x = clamp((x - edge0) / (edge1 - edge0))
    return x * x * (3 - 2 * x)


def ease_out_back(x: float) -> float:
    x = clamp(x)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def color_mix(a: tuple[int, int, int], b: tuple[int, int, int], x: float) -> tuple[int, int, int]:
    return tuple(int(lerp(a[i], b[i], x)) for i in range(3))


def get_ffmpeg_exe() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for candidate in (PROJECT_ROOT / "ffmpeg-temp").glob("*/bin/ffmpeg.exe"):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("FFmpeg not found in PATH or ffmpeg-temp/*/bin.")


def get_ffprobe_exe() -> str:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    for candidate in (PROJECT_ROOT / "ffmpeg-temp").glob("*/bin/ffprobe.exe"):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("FFprobe not found in PATH or ffmpeg-temp/*/bin.")


def font_path() -> str:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simhei.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simsun.ttc",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("No Chinese font found in Windows Fonts.")


FONT_PATH = font_path()
TITLE_FONT = ImageFont.truetype(FONT_PATH, 46)
SUBTITLE_FONT = ImageFont.truetype(FONT_PATH, 34)
SMALL_FONT = ImageFont.truetype(FONT_PATH, 24)
TINY_FONT = ImageFont.truetype(FONT_PATH, 18)
GRID_TITLE_FONT = ImageFont.truetype(FONT_PATH, 26)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for char in text:
        test = line + char
        if text_size(draw, test, font)[0] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = char
    if line:
        lines.append(line)
    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    max_width: int,
    line_gap: int = 6,
) -> int:
    lines = wrap_text(draw, text, font, max_width)
    yy = y
    for line in lines:
        w, h = text_size(draw, line, font)
        draw.text(((WIDTH - w) / 2, yy), line, font=font, fill=fill)
        yy += h + line_gap
    return yy


def rounded_rect(
    img: Image.Image,
    box: tuple[float, float, float, float],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def shadowed_rect(
    img: Image.Image,
    box: tuple[float, float, float, float],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    shadow_alpha: int = 90,
    blur: int = 18,
    offset: tuple[int, int] = (0, 12),
) -> None:
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    sx0, sy0, sx1, sy1 = box
    ox, oy = offset
    d.rounded_rectangle((sx0 + ox, sy0 + oy, sx1 + ox, sy1 + oy), radius=radius, fill=(0, 0, 0, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(shadow)
    rounded_rect(img, box, radius, fill, outline)


def draw_background(spec: SampleSpec, t: float, duration: float) -> Image.Image:
    p1, p2, p3 = spec.palette
    yy = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, WIDTH, dtype=np.float32)[None, :]
    a = np.array(p1, dtype=np.float32)
    b = np.array(p2, dtype=np.float32)
    c = np.array(p3, dtype=np.float32)
    grad = (1 - yy)[:, :, None] * a + yy[:, :, None] * b
    waves = (np.sin(xx * 7.0 + yy * 5.2 + t * 0.9) + 1) / 2
    glow = waves[:, :, None] * c * 0.18
    vignette = 1 - 0.55 * ((xx - 0.5) ** 2 + (yy - 0.5) ** 2)
    arr = np.clip((grad + glow) * vignette[:, :, None], 0, 255).astype(np.uint8)
    return Image.fromarray(arr).convert("RGBA")


def draw_floor(img: Image.Image, y: int = 945) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.polygon([(0, y), (WIDTH, y - 50), (WIDTH, HEIGHT), (0, HEIGHT)], fill=(8, 12, 24, 125))
    for i in range(9):
        yy = y + i * 38
        d.line((0, yy, WIDTH, yy - 50), fill=(255, 255, 255, 22), width=1)
    img.alpha_composite(overlay)


def draw_stage_header(img: Image.Image, spec: SampleSpec, t: float, duration: float, idx: int, total: int) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (42, 44, WIDTH - 42, 150), 28, (12, 18, 31, 170), (255, 255, 255, 45), 65)
    draw_centered_text(d, spec.title, 69, TITLE_FONT, (255, 255, 255, 245), WIDTH - 120)
    d.text((56, 1215), f"Pixelle complex animation {idx + 1}/{total}", font=TINY_FONT, fill=(255, 255, 255, 155))
    progress = clamp(t / duration)
    d.rounded_rectangle((56, 1244, WIDTH - 56, 1253), radius=8, fill=(255, 255, 255, 45))
    p3 = spec.palette[2]
    d.rounded_rectangle((56, 1244, 56 + (WIDTH - 112) * progress, 1253), radius=8, fill=(*p3, 235))
    img.alpha_composite(overlay)


def draw_subtitle(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    beat_idx = min(2, int(clamp(t / duration) * 3))
    beat = spec.beats[beat_idx]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (52, 1030, WIDTH - 52, 1160), 26, (13, 19, 31, 205), (255, 255, 255, 42), 80)
    d.text((78, 1050), f"0{beat_idx + 1}", font=SMALL_FONT, fill=(*spec.palette[2], 255))
    draw_centered_text(d, beat, 1088, SUBTITLE_FONT, (255, 255, 255, 245), WIDTH - 150)
    img.alpha_composite(overlay)


def draw_character(
    img: Image.Image,
    x: float,
    y: float,
    scale: float,
    t: float,
    shirt: tuple[int, int, int],
    facing: int = 1,
    action: str = "idle",
) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    s = scale
    bob = math.sin(t * 4.8) * 5 * s
    if action == "walk":
        arm = math.sin(t * 6.0) * 35
        leg = math.sin(t * 6.0) * 28
    elif action == "reach":
        arm = 55 * smoothstep(0.0, 1.0, (math.sin(t * 2.0) + 1) / 2)
        leg = 8
    elif action == "write":
        arm = 35 + math.sin(t * 12.0) * 12
        leg = 4
    elif action == "breathe":
        arm = 8
        leg = 0
        bob = -math.sin(t * 2.3) * 6 * s
    else:
        arm = math.sin(t * 2.2) * 8
        leg = math.sin(t * 2.0) * 5

    foot_y = y + bob
    hip = (x, foot_y - 118 * s)
    neck = (x, foot_y - 244 * s)
    head_c = (x + facing * 6 * s, foot_y - 300 * s)
    skin = (255, 206, 164, 255)
    dark = (22, 30, 44, 255)
    pants = (34, 54, 83, 255)

    shadow_w = 95 * s
    d.ellipse((x - shadow_w, foot_y - 18 * s, x + shadow_w, foot_y + 12 * s), fill=(0, 0, 0, 65))
    d.line((hip[0] - 22 * s, hip[1], x - 42 * s - leg * facing, foot_y), fill=pants, width=max(4, int(15 * s)))
    d.line((hip[0] + 22 * s, hip[1], x + 42 * s + leg * facing, foot_y), fill=pants, width=max(4, int(15 * s)))
    d.ellipse((x - 70 * s - leg * facing, foot_y - 6 * s, x - 22 * s - leg * facing, foot_y + 10 * s), fill=dark)
    d.ellipse((x + 18 * s + leg * facing, foot_y - 6 * s, x + 68 * s + leg * facing, foot_y + 10 * s), fill=dark)
    d.rounded_rectangle(
        (x - 50 * s, foot_y - 245 * s, x + 50 * s, foot_y - 116 * s),
        radius=int(28 * s),
        fill=(*shirt, 255),
        outline=(255, 255, 255, 35),
        width=max(1, int(2 * s)),
    )
    shoulder_y = foot_y - 222 * s
    left_hand = (x - 98 * s, shoulder_y + (28 + arm) * s)
    right_hand = (x + 98 * s, shoulder_y + (28 - arm) * s)
    if action == "write":
        left_hand = (x - 82 * s, shoulder_y + 58 * s)
        right_hand = (x + 88 * s, shoulder_y + (78 + math.sin(t * 12) * 10) * s)
    if action == "reach":
        right_hand = (x + facing * 128 * s, shoulder_y - 42 * s)
    d.line((x - 40 * s, shoulder_y, left_hand[0], left_hand[1]), fill=skin, width=max(4, int(13 * s)))
    d.line((x + 40 * s, shoulder_y, right_hand[0], right_hand[1]), fill=skin, width=max(4, int(13 * s)))
    d.ellipse((left_hand[0] - 11 * s, left_hand[1] - 11 * s, left_hand[0] + 11 * s, left_hand[1] + 11 * s), fill=skin)
    d.ellipse((right_hand[0] - 11 * s, right_hand[1] - 11 * s, right_hand[0] + 11 * s, right_hand[1] + 11 * s), fill=skin)
    d.line((neck[0], neck[1], hip[0], hip[1]), fill=(255, 255, 255, 70), width=max(2, int(3 * s)))
    d.ellipse((head_c[0] - 42 * s, head_c[1] - 42 * s, head_c[0] + 42 * s, head_c[1] + 42 * s), fill=skin)
    d.pieslice((head_c[0] - 45 * s, head_c[1] - 48 * s, head_c[0] + 45 * s, head_c[1] + 30 * s), 185, 355, fill=dark)
    eye_x = head_c[0] + facing * 18 * s
    d.ellipse((eye_x - 5 * s, head_c[1] - 6 * s, eye_x + 3 * s, head_c[1] + 2 * s), fill=dark)
    d.arc((head_c[0] - 14 * s, head_c[1] + 12 * s, head_c[0] + 16 * s, head_c[1] + 28 * s), 10, 170, fill=(147, 89, 74, 255), width=max(1, int(2 * s)))
    img.alpha_composite(overlay)


def draw_laptop(img: Image.Image, x: float, y: float, w: float, h: float, glow: tuple[int, int, int], t: float) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (x, y, x + w, y + h), 18, (18, 28, 44, 245), (255, 255, 255, 35), 55, 14)
    screen = (x + 14, y + 14, x + w - 14, y + h - 18)
    d.rounded_rectangle(screen, radius=12, fill=(8, 17, 28, 255), outline=(*glow, 120), width=2)
    for i in range(6):
        yy = screen[1] + 24 + i * 22
        line_w = (w - 70) * (0.45 + 0.45 * ((math.sin(t * 2 + i) + 1) / 2))
        d.rounded_rectangle((screen[0] + 18, yy, screen[0] + 18 + line_w, yy + 8), radius=4, fill=(*glow, 110))
    d.rounded_rectangle((x - 18, y + h, x + w + 18, y + h + 18), radius=9, fill=(14, 21, 34, 255))
    img.alpha_composite(overlay)


def draw_phone(img: Image.Image, x: float, y: float, scale: float, t: float, quiet: float = 0.0) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    w, h = 82 * scale, 150 * scale
    d.rounded_rectangle((x, y, x + w, y + h), radius=int(20 * scale), fill=(14, 18, 28, 255), outline=(255, 255, 255, 55), width=2)
    d.rounded_rectangle((x + 8 * scale, y + 16 * scale, x + w - 8 * scale, y + h - 16 * scale), radius=int(12 * scale), fill=(25, 42, 64, 255))
    d.ellipse((x + w * 0.45, y + h - 12 * scale, x + w * 0.55, y + h - 5 * scale), fill=(255, 255, 255, 80))
    if quiet < 0.95:
        for i in range(3):
            a = 1 - smoothstep(0.2 + i * 0.12, 1.0, quiet)
            yy = y - 12 * scale - i * 32 * scale - math.sin(t * 3 + i) * 5
            d.rounded_rectangle((x - 68 * scale, yy, x + 96 * scale, yy + 24 * scale), radius=10, fill=(255, 96, 96, int(160 * a)))
    img.alpha_composite(overlay)


def draw_checklist(img: Image.Image, x: float, y: float, items: tuple[str, str, str], reveal: float, accent: tuple[int, int, int]) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (x, y, x + 230, y + 220), 22, (245, 247, 250, 230), (255, 255, 255, 130), 55, 12)
    for i, item in enumerate(items):
        item_reveal = smoothstep(i * 0.22, i * 0.22 + 0.26, reveal)
        yy = y + 34 + i * 56
        d.rounded_rectangle((x + 28, yy, x + 52, yy + 24), radius=7, outline=(*accent, 230), width=3)
        if item_reveal > 0.5:
            d.line((x + 31, yy + 13, x + 39, yy + 21, x + 55, yy + 2), fill=(*accent, 255), width=4)
        d.text((x + 66, yy - 2), item[:8], font=TINY_FONT, fill=(28, 38, 54, int(255 * item_reveal)))
    img.alpha_composite(overlay)


def draw_window(img: Image.Image, x: float, y: float, w: float, h: float, open_amount: float, sun: tuple[int, int, int]) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=(12, 27, 48, 190), outline=(255, 255, 255, 55), width=2)
    d.ellipse((x + w * 0.6, y + h * 0.18, x + w * 0.84, y + h * 0.42), fill=(*sun, 210))
    d.line((x + w / 2, y, x + w / 2, y + h), fill=(255, 255, 255, 45), width=2)
    curtain_w = w * 0.45 * (1 - open_amount)
    d.rectangle((x, y, x + curtain_w, y + h), fill=(72, 65, 130, 180))
    d.rectangle((x + w - curtain_w, y, x + w, y + h), fill=(72, 65, 130, 180))
    for i in range(4):
        beam_x = x + 40 + i * 60 + open_amount * 40
        d.polygon(
            [(beam_x, y + h), (beam_x + 34, y + h), (beam_x + 130, y + h + 360), (beam_x + 60, y + h + 360)],
            fill=(*sun, int(55 * open_amount)),
        )
    img.alpha_composite(overlay)


def draw_focus_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 920)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (118, 730, 610, 794), 22, (48, 67, 86, 245), (255, 255, 255, 45), 80)
    d.rounded_rectangle((162, 792, 204, 976), radius=14, fill=(38, 52, 68, 255))
    d.rounded_rectangle((526, 792, 568, 976), radius=14, fill=(38, 52, 68, 255))
    img.alpha_composite(overlay)
    draw_laptop(img, 300, 608, 230, 150, p2, t)
    quiet = smoothstep(0.0, 0.32, phase)
    draw_phone(img, 540 + 20 * math.sin(t * 2), 560, 1.05, t, quiet)
    draw_character(img, 232, 942, 1.0, t, color_mix(p2, p3, 0.25), facing=1, action="write" if phase > 0.28 else "reach")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    ring = smoothstep(0.28, 0.62, phase)
    cx, cy = 205, 410
    d.ellipse((cx - 88, cy - 88, cx + 88, cy + 88), outline=(*p3, 70), width=12)
    d.arc((cx - 88, cy - 88, cx + 88, cy + 88), -90, -90 + 360 * ring, fill=(*p3, 255), width=12)
    d.text((cx - 30, cy - 20), "25", font=TITLE_FONT, fill=(255, 255, 255, 235))
    img.alpha_composite(overlay)
    draw_checklist(img, 416, 330, ("关提醒", "25分钟", "写下一步"), smoothstep(0.58, 1.0, phase), p3)


def draw_bedtime_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 930)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle((62, 300, 280, 650), radius=24, fill=(18, 29, 55, 210), outline=(255, 255, 255, 40), width=2)
    d.ellipse((165, 360, 235, 430), fill=(*p3, 210))
    for i in range(5):
        d.ellipse((100 + i * 38, 335 + (i % 2) * 36, 104 + i * 38, 339 + (i % 2) * 36), fill=(255, 255, 255, 145))
    shadowed_rect(overlay, (68, 760, 330, 910), 30, (70, 76, 128, 240), (255, 255, 255, 35), 70)
    d.rounded_rectangle((100, 710, 236, 780), radius=22, fill=(240, 231, 211, 245))
    shadowed_rect(overlay, (384, 705, 626, 774), 18, (56, 45, 77, 245), (255, 255, 255, 45), 75)
    d.rounded_rectangle((418, 774, 448, 956), radius=11, fill=(50, 42, 64, 255))
    d.rounded_rectangle((562, 774, 592, 956), radius=11, fill=(50, 42, 64, 255))
    img.alpha_composite(overlay)
    clear = smoothstep(0.12, 0.62, phase)
    for i in range(5):
        x = lerp(420 + i * 36, 560 + (i % 2) * 28, clear)
        y = lerp(672 - (i % 2) * 38, 840 + i * 12, clear)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        d.rounded_rectangle((x, y, x + 48, y + 36), radius=8, fill=(*color_mix(p2, p3, i / 5), 220))
        img.alpha_composite(overlay)
    draw_character(img, 330 + 45 * smoothstep(0.1, 0.55, phase), 948, 0.92, t, color_mix(p2, p3, 0.3), facing=1, action="reach")
    draw_checklist(img, 392, 358, ("写明天重点", "桌面留三样", "手机停用"), smoothstep(0.48, 1.0, phase), p3)


def draw_breathing_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 945)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    breathe = (math.sin(t * 1.25) + 1) / 2
    for i in range(5):
        r = 90 + i * 58 + breathe * 38
        d.ellipse((WIDTH / 2 - r, 435 - r, WIDTH / 2 + r, 435 + r), outline=(*p2, max(18, 95 - i * 15)), width=5)
    d.rounded_rectangle((105, 690, 615, 720), radius=14, fill=(255, 255, 255, 35))
    exhale = smoothstep(0.0, 1.0, breathe)
    d.rounded_rectangle((105, 690, 105 + 510 * exhale, 720), radius=14, fill=(*p3, 170))
    for i in range(7):
        x = 116 + i * 78
        y = 805 + math.sin(t * 2 + i) * 24
        d.arc((x - 24, y - 16, x + 24, y + 16), 0, 180, fill=(255, 255, 255, 85), width=3)
    img.alpha_composite(overlay)
    draw_character(img, WIDTH / 2, 948, 1.12, t, color_mix(p2, p3, 0.2), facing=1, action="breathe")
    draw_checklist(img, 412, 320, ("呼气更长", "肩膀放下", "听一个声音"), smoothstep(0.52, 1.0, phase), p3)


def draw_morning_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_window(img, 82, 258, 300, 390, smoothstep(0.18, 0.58, phase), p3)
    draw_floor(img, 930)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (420, 715, 650, 885), 28, (72, 58, 75, 238), (255, 255, 255, 45), 80)
    d.rounded_rectangle((450, 665, 575, 725), radius=20, fill=(255, 241, 210, 245))
    glass_x = 470 + 20 * math.sin(t * 2)
    d.rounded_rectangle((glass_x, 630, glass_x + 42, 705), radius=10, fill=(160, 225, 255, 105), outline=(255, 255, 255, 95), width=2)
    d.rectangle((glass_x + 5, 668, glass_x + 37, 700), fill=(96, 196, 232, 110))
    img.alpha_composite(overlay)
    x = lerp(530, 288, smoothstep(0.0, 0.5, phase))
    draw_character(img, x, 946, 0.95, t, color_mix(p2, p3, 0.3), facing=-1, action="walk" if phase < 0.48 else "reach")
    draw_checklist(img, 410, 335, ("喝温水", "打开窗帘", "先做小事"), smoothstep(0.52, 1.0, phase), p3)


def draw_gallery_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 980)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(6):
        col = i % 3
        row = i // 3
        x = 80 + col * 188 + math.sin(t * 0.7 + i) * 9
        y = 275 + row * 205 + math.cos(t * 0.6 + i) * 8
        w, h = 135, 155
        fill = color_mix(p2, p3, (i % 3) / 3)
        shadowed_rect(overlay, (x, y, x + w, y + h), 16, (245, 245, 238, 225), (255, 255, 255, 70), 45, 10)
        d.rounded_rectangle((x + 12, y + 12, x + w - 12, y + h - 38), radius=10, fill=(*fill, 185))
        d.line((x + 18, y + h - 24, x + w - 18, y + h - 24), fill=(33, 41, 58, 100), width=4)
    lens_x = lerp(95, 440, (math.sin(t * 0.9) + 1) / 2)
    lens_y = lerp(335, 530, (math.cos(t * 0.8) + 1) / 2)
    d.ellipse((lens_x, lens_y, lens_x + 112, lens_y + 112), outline=(*p3, 230), width=8)
    d.line((lens_x + 90, lens_y + 90, lens_x + 158, lens_y + 158), fill=(*p3, 230), width=10)
    img.alpha_composite(overlay)
    draw_character(img, 354, 1010, 0.82, t, color_mix(p2, p3, 0.2), facing=1, action="reach")
    draw_checklist(img, 426, 748, ("收集喜欢", "说出原因", "模仿一处"), smoothstep(0.50, 1.0, phase), p3)


def draw_ai_lab_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 960)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(12):
        x = 68 + i * 52
        y = 270 + math.sin(t * 0.8 + i) * 18
        d.rounded_rectangle((x, y, x + 34, y + 120), radius=12, fill=(*color_mix(p2, p3, i / 12), 55))
    img.alpha_composite(overlay)
    draw_laptop(img, 235, 590, 270, 180, p2, t)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    labels = ("目标", "模板", "案例库")
    for i, label in enumerate(labels):
        appear = ease_out_back(smoothstep(i * 0.23, i * 0.23 + 0.28, phase))
        x = lerp(-160, 80 + i * 195, appear)
        y = 420 + (i % 2) * 70
        shadowed_rect(overlay, (x, y, x + 145, y + 72), 20, (14, 31, 50, 225), (*p3, 80), 45, 10)
        d.text((x + 38, y + 22), label, font=SMALL_FONT, fill=(255, 255, 255, 238))
    for i in range(6):
        x = 92 + i * 88
        y = 820 + math.sin(t * 1.2 + i) * 8
        d.rounded_rectangle((x, y, x + 52, y + 98), radius=8, fill=(*color_mix(p2, p3, i / 6), 190))
    img.alpha_composite(overlay)
    draw_character(img, 160, 962, 0.92, t, color_mix(p2, p3, 0.3), facing=1, action="write")


def draw_procrastination_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 960)
    shrink = smoothstep(0.0, 0.42, phase)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    block_w = lerp(360, 145, shrink)
    block_h = lerp(260, 96, shrink)
    block_x = lerp(180, 420, shrink)
    block_y = lerp(420, 610, shrink)
    shadowed_rect(overlay, (block_x, block_y, block_x + block_w, block_y + block_h), 28, (*p2, 230), (255, 255, 255, 50), 90)
    d.text((block_x + 32, block_y + 40), "大任务", font=TITLE_FONT, fill=(255, 255, 255, 235))
    for i in range(3):
        x = lerp(-110, 98 + i * 160, smoothstep(0.35 + i * 0.1, 0.72 + i * 0.1, phase))
        y = 785 + i * 22
        d.rounded_rectangle((x, y, x + 110, y + 58), radius=14, fill=(*p3, 210))
        d.text((x + 18, y + 17), ["两分钟", "材料", "第一步"][i], font=TINY_FONT, fill=(25, 28, 40, 245))
    img.alpha_composite(overlay)
    draw_character(img, 300 + 30 * math.sin(t * 1.6), 962, 0.98, t, color_mix(p2, p3, 0.3), facing=1, action="reach" if phase < 0.6 else "walk")
    draw_checklist(img, 416, 322, ("缩到两分钟", "材料放手边", "只做第一步"), smoothstep(0.52, 1.0, phase), p3)


def draw_writing_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 950)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (118, 610, 610, 740), 24, (55, 62, 78, 245), (255, 255, 255, 45), 80)
    page_x, page_y = 250, 360
    shadowed_rect(overlay, (page_x, page_y, page_x + 250, page_y + 330), 20, (246, 245, 235, 245), (255, 255, 255, 100), 75)
    for i in range(7):
        reveal = smoothstep(0.25 + i * 0.06, 0.45 + i * 0.06, phase)
        d.rounded_rectangle((page_x + 30, page_y + 60 + i * 32, page_x + 30 + 175 * reveal, page_y + 72 + i * 32), radius=5, fill=(*p2, 160))
    bulb_r = 40 + 18 * smoothstep(0.45, 0.75, phase) * (0.7 + 0.3 * math.sin(t * 7))
    d.ellipse((508 - bulb_r, 380 - bulb_r, 508 + bulb_r, 380 + bulb_r), fill=(*p3, 115), outline=(*p3, 220), width=4)
    d.rounded_rectangle((488, 422, 528, 446), radius=8, fill=(*p3, 230))
    labels = ("问题", "观点", "例子")
    for i, label in enumerate(labels):
        x = lerp(-150, 82, smoothstep(i * 0.18, i * 0.18 + 0.28, phase))
        y = 360 + i * 92
        d.rounded_rectangle((x, y, x + 118, y + 56), radius=16, fill=(255, 255, 255, 205))
        d.text((x + 32, y + 15), label, font=TINY_FONT, fill=(35, 43, 55, 245))
    img.alpha_composite(overlay)
    draw_character(img, 286, 955, 0.94, t, color_mix(p2, p3, 0.25), facing=1, action="write")
    draw_checklist(img, 420, 780, ("先列问题", "一句观点", "例子跟上"), smoothstep(0.52, 1.0, phase), p3)


def draw_review_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(12):
        x = i * 72 - 25
        h = 120 + (i % 4) * 45
        d.rectangle((x, 735 - h, x + 44, 735), fill=(15, 28, 48, 185))
        for j in range(4):
            d.rectangle((x + 10, 735 - h + 18 + j * 26, x + 18, 735 - h + 26 + j * 26), fill=(*p3, 75))
    img.alpha_composite(overlay)
    draw_floor(img, 935)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shadowed_rect(overlay, (82, 310, 638, 720), 28, (235, 240, 232, 232), (255, 255, 255, 90), 85)
    board_items = ("推进了什么", "卡在哪里", "明天第一步")
    for i, item in enumerate(board_items):
        reveal = smoothstep(i * 0.18, i * 0.18 + 0.32, phase)
        x = 126 + i * 166
        y = 390 + math.sin(t * 1.4 + i) * 6
        d.rounded_rectangle((x, y, x + 132, y + 142), radius=18, fill=(*color_mix(p2, p3, i / 3), int(225 * reveal)))
        d.text((x + 18, y + 48), item[:5], font=TINY_FONT, fill=(19, 29, 43, int(245 * reveal)))
    d.line((184, 610, 358, 610, 528, 610), fill=(*p2, 175), width=5)
    d.polygon([(528, 610), (504, 596), (504, 624)], fill=(*p2, 175))
    img.alpha_composite(overlay)
    draw_character(img, 232, 956, 0.94, t, color_mix(p2, p3, 0.22), facing=1, action="reach")
    draw_checklist(img, 420, 772, ("推进什么", "卡点原因", "明天第一步"), smoothstep(0.52, 1.0, phase), p3)


def draw_habit_scene(img: Image.Image, spec: SampleSpec, t: float, duration: float) -> None:
    p1, p2, p3 = spec.palette
    phase = t / duration
    draw_floor(img, 950)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = WIDTH / 2, 460
    for i in range(7):
        angle = -math.pi / 2 + i * 2 * math.pi / 7 + t * 0.12
        x = cx + math.cos(angle) * 185
        y = cy + math.sin(angle) * 135
        scale = 0.8 + 0.2 * math.sin(t + i)
        d.rounded_rectangle((x - 42 * scale, y - 36 * scale, x + 42 * scale, y + 36 * scale), radius=14, fill=(255, 255, 255, 190))
        d.text((x - 12, y - 14), str(i + 1), font=TINY_FONT, fill=(28, 37, 52, 240))
    progress = smoothstep(0.0, 1.0, phase)
    d.arc((cx - 210, cy - 160, cx + 210, cy + 160), -90, -90 + progress * 360, fill=(*p3, 230), width=10)
    for i in range(3):
        x = lerp(80, 425, smoothstep(0.25 + i * 0.15, 0.45 + i * 0.15, phase))
        y = 748 + i * 58
        d.rounded_rectangle((x, y, x + 160, y + 42), radius=16, fill=(*color_mix(p2, p3, i / 3), 210))
        d.text((x + 22, y + 10), ["固定时间", "最低版本", "每周复盘"][i], font=TINY_FONT, fill=(18, 28, 44, 245))
    img.alpha_composite(overlay)
    draw_character(img, 270 + math.sin(t * 1.2) * 28, 962, 0.96, t, color_mix(p2, p3, 0.18), facing=1, action="walk")
    draw_checklist(img, 420, 318, ("固定时间", "最低版本", "每周复盘"), smoothstep(0.52, 1.0, phase), p3)


SCENE_RENDERERS: dict[str, Callable[[Image.Image, SampleSpec, float, float], None]] = {
    "focus": draw_focus_scene,
    "bedtime": draw_bedtime_scene,
    "breathing": draw_breathing_scene,
    "morning": draw_morning_scene,
    "gallery": draw_gallery_scene,
    "ai_lab": draw_ai_lab_scene,
    "procrastination": draw_procrastination_scene,
    "writing": draw_writing_scene,
    "review": draw_review_scene,
    "habit": draw_habit_scene,
}


def render_frame(spec: SampleSpec, t: float, duration: float, idx: int, total: int) -> bytes:
    img = draw_background(spec, t, duration)
    renderer = SCENE_RENDERERS[spec.scenario]
    renderer(img, spec, t, duration)
    draw_stage_header(img, spec, t, duration, idx, total)
    draw_subtitle(img, spec, t, duration)
    fade_in = smoothstep(0.0, 0.5, t)
    fade_out = 1 - smoothstep(duration - 0.5, duration, t)
    alpha = clamp(fade_in * fade_out)
    if alpha < 0.999:
        fade = Image.new("RGBA", img.size, (0, 0, 0, int(255 * (1 - alpha))))
        img.alpha_composite(fade)
    return img.convert("RGB").tobytes()


def probe_duration(path: Path) -> float:
    cmd = [
        get_ffprobe_exe(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=True)
    return float(result.stdout.strip())


def find_existing_audio(spec: SampleSpec) -> Path | None:
    pattern = f"*{spec.title}*"
    for candidate in sorted(OUTPUT_ROOT.glob(pattern), reverse=True):
        audio = candidate / "frames" / "voice.mp3"
        if audio.exists() and audio.stat().st_size > 0:
            return audio
    return None


async def generate_tts(spec: SampleSpec, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = find_existing_audio(spec)
    if existing:
        shutil.copy2(existing, output_path)
        return

    attempts = [
        (spec.voice, spec.speed),
        ("zh-CN-XiaoxiaoNeural", "+0%"),
        ("zh-CN-YunjianNeural", "+0%"),
    ]
    last_error: Exception | None = None
    for voice, rate in attempts:
        try:
            communicate = edge_tts.Communicate(text=spec.narration, voice=voice, rate=rate)
            await communicate.save(str(output_path))
            return
        except (NoAudioReceived, Exception) as exc:
            last_error = exc
            if output_path.exists():
                output_path.unlink()
            await asyncio.sleep(1)
    raise RuntimeError(f"TTS failed after retries: {last_error}")


def encode_video(spec: SampleSpec, audio_path: Path, video_path: Path, duration: float, idx: int, total: int) -> None:
    video_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(math.ceil(duration * FPS)))
    cmd = [
        get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "pipe:0",
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(video_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame_idx in range(frame_count):
            t = frame_idx / FPS
            proc.stdin.write(render_frame(spec, t, duration, idx, total))
    finally:
        proc.stdin.close()
    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore") or "FFmpeg failed.")


def create_thumbnail(video_path: Path, thumb_path: Path) -> None:
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-y",
            "-ss",
            "00:00:03",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(thumb_path),
        ],
        check=True,
        capture_output=True,
    )


def write_metadata(task_dir: Path, spec: SampleSpec, video_path: Path, audio_path: Path, duration: float) -> None:
    now = datetime.now().isoformat()
    task_id = task_dir.name
    file_size = video_path.stat().st_size
    third = duration / 3
    frames = [
        {
            "index": i,
            "narration": beat,
            "image_prompt": f"Complex 2D animated scene with character and props: {spec.scenario}",
            "audio_path": str(audio_path),
            "media_type": "video",
            "image_path": None,
            "video_path": str(video_path),
            "composed_image_path": None,
            "video_segment_path": str(video_path),
            "duration": third,
            "created_at": now,
        }
        for i, beat in enumerate(spec.beats)
    ]

    metadata = {
        "task_id": task_id,
        "created_at": now,
        "completed_at": now,
        "status": "completed",
        "title": spec.title,
        "input": {
            "mode": "complex_2d_animation",
            "title": spec.title,
            "text": spec.narration,
            "n_scenes": 3,
            "frame_template": "complex_2d_animation",
            "tts_inference_mode": "local",
            "tts_voice": spec.voice,
            "video_fps": FPS,
            "video_size": f"{WIDTH}x{HEIGHT}",
        },
        "result": {
            "video_path": str(video_path),
            "duration": duration,
            "file_size": file_size,
            "n_frames": 3,
        },
        "config": {
            "llm_model": "deepseek-chat",
            "comfyui_url": "http://127.0.0.1:8188",
            "comfyui_used_for_this_batch": False,
            "render_engine": "Pixelle complex 2D animation + Edge TTS + FFmpeg",
        },
    }

    storyboard = {
        "title": spec.title,
        "description": spec.narration,
        "config": {
            "task_id": task_id,
            "video_width": WIDTH,
            "video_height": HEIGHT,
            "fps": FPS,
            "frame_template": "complex_2d_animation",
            "media_workflow": "complex_2d_animation",
        },
        "frames": frames,
        "content_metadata": None,
        "final_video_path": str(video_path),
        "total_duration": duration,
        "created_at": now,
        "completed_at": now,
    }

    (task_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (task_dir / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")


def video_title(video_path: Path) -> str:
    metadata_path = video_path.parent / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            title = metadata.get("title") or metadata.get("input", {}).get("title")
            if title:
                return str(title)
        except json.JSONDecodeError:
            pass
    name = video_path.parent.name
    if name.startswith("complex_"):
        parts = name.split("_")
        if len(parts) >= 5:
            return "_".join(parts[4:])
    return name


def create_preview_grid(videos: list[Path], grid_path: Path) -> None:
    if not videos:
        return
    cols = min(5, len(videos))
    rows = math.ceil(len(videos) / cols)
    thumb_w, thumb_h = 180, 320
    title_h = 68
    gap = 28
    pad = 24
    canvas_w = pad * 2 + cols * thumb_w + (cols - 1) * gap
    canvas_h = pad * 2 + rows * (thumb_h + title_h) + (rows - 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 18, 27))
    d = ImageDraw.Draw(canvas)
    for i, video in enumerate(videos):
        row, col = divmod(i, cols)
        x = pad + col * (thumb_w + gap)
        y = pad + row * (thumb_h + title_h + gap)
        thumb_path = video.parent / "preview_3s.jpg"
        if thumb_path.exists():
            thumb = Image.open(thumb_path).convert("RGB")
        else:
            thumb = Image.new("RGB", (WIDTH, HEIGHT), (30, 36, 52))
        thumb = ImageOps.fit(thumb, (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
        canvas.paste(thumb, (x, y))
        for line_idx, line in enumerate(wrap_text(d, video_title(video), GRID_TITLE_FONT, thumb_w)[:2]):
            line_w, line_h = text_size(d, line, GRID_TITLE_FONT)
            d.text((x + (thumb_w - line_w) / 2, y + thumb_h + 8 + line_idx * (line_h + 2)), line, font=GRID_TITLE_FONT, fill=(248, 250, 252))
    canvas.save(grid_path, quality=92)


async def rebuild_history_index(task_ids: list[str]) -> None:
    from pixelle_video.services.persistence import PersistenceService

    await PersistenceService(str(OUTPUT_ROOT)).rebuild_index()
    print(f"History index rebuilt for {len(task_ids)} complex animation videos.")


async def generate_one(spec: SampleSpec, idx: int, total: int, batch_id: str) -> Path:
    safe_title = "".join(ch for ch in spec.title if ch.isalnum() or ch in "_-")[:20]
    task_id = f"{batch_id}_{idx + 1:02d}_{safe_title}"
    task_dir = OUTPUT_ROOT / task_id
    frames_dir = task_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    audio_path = frames_dir / "voice.mp3"
    video_path = task_dir / "final.mp4"
    thumb_path = task_dir / "preview_3s.jpg"

    print(f"[{idx + 1}/{total}] Audio: {spec.title}")
    await generate_tts(spec, audio_path)
    audio_duration = probe_duration(audio_path)
    duration = max(10.5, min(18.0, audio_duration + 0.8))

    print(f"[{idx + 1}/{total}] Complex animation render: {duration:.1f}s")
    encode_video(spec, audio_path, video_path, duration, idx, total)
    create_thumbnail(video_path, thumb_path)
    write_metadata(task_dir, spec, video_path, audio_path, duration)
    return video_path


async def main_async(count: int) -> None:
    OUTPUT_ROOT.mkdir(exist_ok=True)
    batch_id = "complex_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    selected = list(SAMPLES[:count])
    videos: list[Path] = []
    task_ids: list[str] = []

    for idx, spec in enumerate(selected):
        video = await generate_one(spec, idx, len(selected), batch_id)
        videos.append(video)
        task_ids.append(video.parent.name)

    await rebuild_history_index(task_ids)
    grid_path = OUTPUT_ROOT / f"{batch_id}_preview_grid.jpg"
    create_preview_grid(videos, grid_path)
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "count": len(videos),
        "videos": [str(path) for path in videos],
        "preview_grid": str(grid_path),
    }
    manifest_path = OUTPUT_ROOT / f"{batch_id}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nGenerated complex animation videos:")
    for path in videos:
        print(path)
    print(f"\nManifest: {manifest_path}")
    print(f"Preview grid: {grid_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate complex animated Pixelle MP4 samples.")
    parser.add_argument("--count", type=int, default=10, help="Number of videos to generate, max 10.")
    args = parser.parse_args()
    count = max(1, min(args.count, len(SAMPLES)))
    try:
        asyncio.run(main_async(count))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
