# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Generate dynamic MP4 samples for local demos.

This script intentionally avoids heavy AI video models. It uses Pixelle-Video's
local dependencies, Edge TTS, procedural motion graphics, and FFmpeg so a clean
local machine can still produce dynamic vertical short videos.
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
FPS = 18


@dataclass(frozen=True)
class SampleSpec:
    title: str
    beats: tuple[str, str, str]
    style: str
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
        "aurora",
        ((21, 30, 67), (30, 135, 133), (242, 201, 76)),
    ),
    SampleSpec(
        "睡前十分钟整理法",
        ("把明天最重要的一件事写下来", "把桌面只留三样东西", "给手机设置固定停用时间"),
        "paper",
        ((30, 42, 72), (232, 183, 104), (248, 244, 235)),
        voice="zh-CN-XiaoxiaoNeural",
    ),
    SampleSpec(
        "一分钟快速减压",
        ("呼气比吸气多两秒", "把肩膀向后慢慢放下", "只观察一个真实的声音"),
        "ocean",
        ((8, 37, 66), (42, 157, 143), (233, 196, 106)),
        voice="zh-CN-YunxiNeural",
    ),
    SampleSpec(
        "让早晨更顺的三个动作",
        ("起床先喝一杯温水", "打开窗帘让光进来", "把第一件小事立刻完成"),
        "sunrise",
        ((19, 59, 92), (255, 183, 77), (255, 244, 214)),
        voice="zh-CN-YunyangNeural",
    ),
    SampleSpec(
        "低成本提升审美",
        ("每天收集三张喜欢的图", "说清楚喜欢它的原因", "模仿一处构图或配色"),
        "gallery",
        ((20, 24, 45), (125, 92, 255), (255, 222, 89)),
        voice="zh-CN-XiaoyiNeural",
    ),
    SampleSpec(
        "新手学习 AI 工具的顺序",
        ("先学会描述目标", "再固定一个常用模板", "最后建立自己的案例库"),
        "data",
        ((10, 17, 40), (0, 197, 255), (167, 255, 131)),
    ),
    SampleSpec(
        "拖延时先做这三步",
        ("把任务缩小到两分钟", "把材料放到手边", "开始前只承诺做第一步"),
        "clock",
        ((32, 25, 54), (255, 122, 89), (255, 213, 128)),
        voice="zh-CN-YunyeNeural",
    ),
    SampleSpec(
        "写作没灵感怎么办",
        ("先列问题，不急着写答案", "用一句话写出核心观点", "把例子放到观点后面"),
        "ink",
        ((24, 31, 43), (87, 160, 211), (238, 108, 77)),
        voice="zh-CN-liaoning-XiaobeiNeural",
    ),
    SampleSpec(
        "工作复盘的三句话",
        ("今天真正推进了什么", "哪里卡住了，原因是什么", "明天先从哪一步开始"),
        "city",
        ((7, 22, 48), (69, 123, 157), (241, 196, 83)),
        voice="zh-CN-YunjianNeural",
    ),
    SampleSpec(
        "保持长期行动的办法",
        ("把目标变成固定时间", "允许每天只做最低版本", "每周复盘一次节奏"),
        "starfield",
        ((9, 13, 31), (72, 149, 239), (255, 209, 102)),
        voice="zh-CN-XiaoxiaoNeural",
    ),
)


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
TITLE_FONT = ImageFont.truetype(FONT_PATH, 58)
SUBTITLE_FONT = ImageFont.truetype(FONT_PATH, 36)
SMALL_FONT = ImageFont.truetype(FONT_PATH, 26)
GRID_TITLE_FONT = ImageFont.truetype(FONT_PATH, 26)


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


async def generate_tts(spec: SampleSpec, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = [
        (spec.voice, spec.speed),
        ("zh-CN-XiaoxiaoNeural", "+0%"),
        ("zh-CN-YunjianNeural", "+0%"),
    ]
    last_error: Exception | None = None
    for voice, rate in attempts:
        try:
            communicate = edge_tts.Communicate(
                text=spec.narration,
                voice=voice,
                rate=rate,
            )
            await communicate.save(str(output_path))
            return
        except (NoAudioReceived, Exception) as exc:
            last_error = exc
            if output_path.exists():
                output_path.unlink()
            await asyncio.sleep(1)
    raise RuntimeError(f"TTS failed after retries: {last_error}")


def gradient_bg(spec: SampleSpec, t: float, duration: float) -> np.ndarray:
    p1, p2, p3 = [np.array(c, dtype=np.float32) for c in spec.palette]
    y = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, WIDTH, dtype=np.float32)[None, :]
    pulse = 0.5 + 0.5 * np.sin(2 * math.pi * (t / duration))
    mix = (np.sin((x * 3.2 + y * 2.1 + t * 0.16) * math.pi) + 1) / 2
    base = (1 - y)[:, :, None] * p1 + y[:, :, None] * p2
    glow = mix[:, :, None] * p3 * (0.22 + pulse * 0.18)
    arr = np.clip(base + glow, 0, 255)
    return arr.astype(np.uint8)


def draw_glow(draw: ImageDraw.ImageDraw, center: tuple[float, float], radius: float, color: tuple[int, int, int], alpha: int) -> None:
    cx, cy = center
    for i in range(8, 0, -1):
        r = radius * i / 8
        a = int(alpha * (i / 8) ** 2 / 5)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, a))


def add_motion_visuals(img: Image.Image, spec: SampleSpec, t: float, duration: float, seed: int) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    p1, p2, p3 = spec.palette
    phase = t / max(duration, 0.1)

    if spec.style == "aurora":
        for k in range(7):
            y = 180 + k * 95 + 38 * math.sin(t * 0.9 + k)
            points = []
            for i in range(-20, WIDTH + 40, 24):
                yy = y + 60 * math.sin(i * 0.012 + t * 1.4 + k)
                points.append((i, yy))
            draw.line(points, fill=(*p3, 115), width=10)
        for i in range(42):
            x = (i * 97 + t * 42) % (WIDTH + 120) - 60
            y = 120 + ((i * 73) % 740)
            draw.ellipse((x, y, x + 4, y + 4), fill=(255, 255, 255, 145))

    elif spec.style == "ocean":
        for k in range(16):
            y = 460 + k * 42
            points = []
            for x in range(-20, WIDTH + 20, 18):
                yy = y + 18 * math.sin(x * 0.025 + t * 1.8 + k * 0.8)
                points.append((x, yy))
            draw.line(points, fill=(*p3, 90), width=3)
        draw_glow(draw, (560 + 20 * math.sin(t), 230), 92, p3, 190)

    elif spec.style == "sunrise":
        sun_y = 760 - 220 * min(1, phase * 1.5)
        draw_glow(draw, (WIDTH * 0.5, sun_y), 210, p3, 210)
        for layer in range(4):
            pts = [(0, HEIGHT)]
            for x in range(0, WIDTH + 120, 120):
                pts.append((x, 760 + layer * 90 + 65 * math.sin(x * 0.015 + t * 0.4 + layer)))
            pts.append((WIDTH, HEIGHT))
            draw.polygon(pts, fill=(*p1, 120 + layer * 20))

    elif spec.style == "data":
        for k in range(24):
            x = (k * 47 + t * 95) % WIDTH
            draw.line((x, 0, WIDTH - x, HEIGHT), fill=(*p2, 70), width=2)
        for k in range(18):
            y = (k * 82 + t * 110) % HEIGHT
            draw.rounded_rectangle((70, y, WIDTH - 70, y + 28), radius=8, outline=(*p3, 105), width=2)

    elif spec.style == "paper":
        for k in range(9):
            offset = 40 * math.sin(t * 0.7 + k)
            x0 = -90 + k * 100 + offset
            y0 = 210 + k * 75
            draw.rounded_rectangle((x0, y0, x0 + 260, y0 + 150), radius=22, fill=(*p3, 35), outline=(*p2, 70), width=2)

    elif spec.style == "gallery":
        for k in range(7):
            x = 80 + ((k * 120 + t * 30) % 540)
            y = 180 + k * 112
            draw.rounded_rectangle((x - 70, y - 70, x + 120, y + 190), radius=18, fill=(*p2, 42), outline=(*p3, 120), width=3)
            draw.line((x - 45, y + 90, x + 95, y - 35), fill=(*p3, 120), width=3)

    elif spec.style == "clock":
        for k in range(6):
            r = 120 + k * 74 + 16 * math.sin(t + k)
            draw.ellipse((WIDTH / 2 - r, HEIGHT / 2 - r, WIDTH / 2 + r, HEIGHT / 2 + r), outline=(*p3, 80), width=3)
        angle = t * 1.2
        draw.line((WIDTH / 2, HEIGHT / 2, WIDTH / 2 + 210 * math.cos(angle), HEIGHT / 2 + 210 * math.sin(angle)), fill=(*p2, 190), width=8)

    elif spec.style == "ink":
        for k in range(13):
            x = (80 + k * 83 + 46 * math.sin(t * 0.5 + k)) % WIDTH
            y = 170 + ((k * 97 + t * 35) % 820)
            r = 62 + 24 * math.sin(t + k)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(*(p2 if k % 2 else p3), 58))
        overlay = overlay.filter(ImageFilter.GaussianBlur(9))
        draw = ImageDraw.Draw(overlay)

    elif spec.style == "city":
        for k in range(18):
            w = 30 + (k * 17 % 44)
            h = 170 + (k * 53 % 380)
            x = k * 48 - 20
            y = HEIGHT - 210 - h
            draw.rectangle((x, y, x + w, HEIGHT), fill=(*p1, 150))
            for row in range(5, h - 20, 42):
                if (k + row + int(t * 3)) % 3 == 0:
                    draw.rectangle((x + 8, y + row, x + 16, y + row + 12), fill=(*p3, 155))
        for k in range(10):
            x = (k * 95 + t * 85) % (WIDTH + 100) - 50
            y = 190 + k * 48
            draw.line((x, y, x + 130, y - 26), fill=(*p2, 115), width=4)

    else:  # starfield
        for k in range(120):
            z = ((k * 37) % 100) / 100
            speed = 70 + z * 220
            x = (k * 61 + t * speed) % (WIDTH + 80) - 40
            y = (k * 113 + t * speed * 0.24) % (HEIGHT + 80) - 40
            s = 1 + int(z * 4)
            draw.ellipse((x, y, x + s, y + s), fill=(255, 255, 255, 100 + int(z * 120)))
        draw_glow(draw, (WIDTH * 0.62 + 40 * math.sin(t * 0.3), HEIGHT * 0.42), 180, p2, 140)

    img.alpha_composite(overlay)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        test = current + ch
        if text_size(draw, test, font)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    max_width: int,
    line_gap: int = 10,
) -> int:
    lines = wrap_text(draw, text, font, max_width)
    for line in lines:
        w, h = text_size(draw, line, font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=fill)
        y += h + line_gap
    return y


def add_text_overlay(img: Image.Image, spec: SampleSpec, t: float, duration: float, idx: int, total: int) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    p1, p2, p3 = spec.palette

    draw.rounded_rectangle((48, 70, WIDTH - 48, 260), radius=28, fill=(8, 10, 18, 138), outline=(*p3, 125), width=2)
    draw_centered_text(draw, spec.title, 108, TITLE_FONT, (255, 255, 255, 245), WIDTH - 130, line_gap=4)

    beat_idx = min(2, int(t / max(duration, 0.1) * 3))
    beat = spec.beats[beat_idx]
    draw.rounded_rectangle((60, 880, WIDTH - 60, 1095), radius=30, fill=(8, 10, 18, 170), outline=(*p2, 135), width=2)
    draw.text((92, 914), f"0{beat_idx + 1}", font=SMALL_FONT, fill=(*p3, 255))
    draw_centered_text(draw, beat, 958, SUBTITLE_FONT, (255, 255, 255, 245), WIDTH - 170, line_gap=8)

    progress = t / max(duration, 0.1)
    bar_w = int((WIDTH - 160) * progress)
    draw.rounded_rectangle((80, 1182, WIDTH - 80, 1196), radius=8, fill=(255, 255, 255, 55))
    draw.rounded_rectangle((80, 1182, 80 + bar_w, 1196), radius=8, fill=(*p3, 220))
    draw.text((80, 1218), f"Pixelle 动态样片 {idx + 1}/{total}", font=SMALL_FONT, fill=(255, 255, 255, 170))

    img.alpha_composite(overlay)


def render_frame(spec: SampleSpec, t: float, duration: float, idx: int, total: int) -> bytes:
    arr = gradient_bg(spec, t, duration)
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    add_motion_visuals(img, spec, t, duration, seed=idx)
    add_text_overlay(img, spec, t, duration, idx, total)
    return img.convert("RGB").tobytes()


def encode_video(spec: SampleSpec, audio_path: Path, video_path: Path, duration: float, idx: int, total: int) -> None:
    video_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(math.ceil(duration * FPS)))
    cmd = [
        get_ffmpeg_exe(),
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
        "-",
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
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
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame_idx in range(frame_count):
            t = frame_idx / FPS
            proc.stdin.write(render_frame(spec, t, duration, idx, total))
    finally:
        proc.stdin.close()
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore"))


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
    if name.startswith("dynamic_"):
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
    canvas = Image.new("RGB", (canvas_w, canvas_h), (16, 19, 29))
    draw = ImageDraw.Draw(canvas)

    for i, video in enumerate(videos):
        row, col = divmod(i, cols)
        x = pad + col * (thumb_w + gap)
        y = pad + row * (thumb_h + title_h + gap)
        thumb_path = video.parent / "preview_3s.jpg"
        if thumb_path.exists():
            thumb = Image.open(thumb_path).convert("RGB")
        else:
            thumb = Image.new("RGB", (WIDTH, HEIGHT), (35, 41, 58))
        thumb = ImageOps.fit(thumb, (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
        canvas.paste(thumb, (x, y))

        title = video_title(video)
        lines = wrap_text(draw, title, GRID_TITLE_FONT, thumb_w)
        for line_idx, line in enumerate(lines[:2]):
            line_w, line_h = text_size(draw, line, GRID_TITLE_FONT)
            draw.text(
                (x + (thumb_w - line_w) / 2, y + thumb_h + 8 + line_idx * (line_h + 2)),
                line,
                font=GRID_TITLE_FONT,
                fill=(248, 250, 252),
            )

    canvas.save(grid_path, quality=92)


def write_metadata(task_dir: Path, spec: SampleSpec, video_path: Path, audio_path: Path, duration: float) -> None:
    now = datetime.now().isoformat()
    task_id = task_dir.name
    file_size = video_path.stat().st_size
    frames = []
    third = duration / 3
    for i, beat in enumerate(spec.beats):
        frames.append(
            {
                "index": i,
                "narration": beat,
                "image_prompt": f"Procedural dynamic motion scene: {spec.style}",
                "audio_path": str(audio_path),
                "media_type": "video",
                "image_path": None,
                "video_path": str(video_path),
                "composed_image_path": None,
                "video_segment_path": str(video_path),
                "duration": third,
                "created_at": now,
            }
        )

    metadata = {
        "task_id": task_id,
        "created_at": now,
        "completed_at": now,
        "status": "completed",
        "input": {
            "mode": "dynamic_procedural",
            "title": spec.title,
            "text": spec.narration,
            "n_scenes": 3,
            "frame_template": "procedural_dynamic",
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
            "render_engine": "Pixelle dynamic procedural + Edge TTS + FFmpeg",
        },
    }

    storyboard = {
        "title": spec.title,
        "config": {
            "task_id": task_id,
            "n_storyboard": 3,
            "min_narration_words": 5,
            "max_narration_words": 20,
            "min_image_prompt_words": 0,
            "max_image_prompt_words": 0,
            "video_fps": FPS,
            "tts_inference_mode": "local",
            "voice_id": spec.voice,
            "tts_workflow": None,
            "tts_speed": None,
            "ref_audio": None,
            "media_width": WIDTH,
            "media_height": HEIGHT,
            "media_workflow": "procedural_dynamic",
            "frame_template": "procedural_dynamic",
            "template_params": {"style": spec.style},
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


async def update_index(task_ids: list[str]) -> None:
    from pixelle_video.services.persistence import PersistenceService

    await PersistenceService(str(OUTPUT_ROOT)).rebuild_index()
    print(f"History index rebuilt for {len(task_ids)} new dynamic videos.")


async def generate_one(spec: SampleSpec, idx: int, total: int, batch_id: str) -> Path:
    safe_title = "".join(ch for ch in spec.title if ch.isalnum() or ch in "_-")[:20]
    task_id = f"{batch_id}_{idx + 1:02d}_{safe_title}"
    task_dir = OUTPUT_ROOT / task_id
    frames_dir = task_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    audio_path = frames_dir / "voice.mp3"
    video_path = task_dir / "final.mp4"
    thumb_path = task_dir / "preview_3s.jpg"

    print(f"[{idx + 1}/{total}] TTS: {spec.title}")
    await generate_tts(spec, audio_path)
    audio_duration = probe_duration(audio_path)
    duration = max(9.0, min(22.0, audio_duration + 0.6))

    print(f"[{idx + 1}/{total}] Render dynamic MP4: {duration:.1f}s")
    encode_video(spec, audio_path, video_path, duration, idx, total)
    create_thumbnail(video_path, thumb_path)
    write_metadata(task_dir, spec, video_path, audio_path, duration)
    return video_path


async def main_async(count: int) -> None:
    OUTPUT_ROOT.mkdir(exist_ok=True)
    batch_id = "dynamic_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    selected = list(SAMPLES[:count])
    videos: list[Path] = []
    task_ids: list[str] = []

    for idx, spec in enumerate(selected):
        video = await generate_one(spec, idx, len(selected), batch_id)
        videos.append(video)
        task_ids.append(video.parent.name)

    await update_index(task_ids)

    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "count": len(videos),
        "videos": [str(path) for path in videos],
    }
    manifest_path = OUTPUT_ROOT / f"{batch_id}_manifest.json"
    grid_path = OUTPUT_ROOT / f"{batch_id}_preview_grid.jpg"
    create_preview_grid(videos, grid_path)
    manifest["preview_grid"] = str(grid_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nGenerated videos:")
    for path in videos:
        print(path)
    print(f"\nManifest: {manifest_path}")
    print(f"Preview grid: {grid_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dynamic Pixelle sample MP4 videos.")
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
