# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Generate a 20-second complex animation and combine it through ComfyUI.

This script uses local drawing code for the frame-by-frame scene animation, then
hands the PNG sequence and narration audio to ComfyUI VideoHelperSuite:

VHS_LoadImagesPath -> VHS_LoadAudio -> VHS_VideoCombine

It is intended for the current machine where ComfyUI is installed and running,
but large T2V model weights are not present yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from generate_complex_animation_samples import (
    FPS,
    HEIGHT,
    OUTPUT_ROOT,
    WIDTH,
    SampleSpec,
    create_preview_grid,
    create_thumbnail,
    draw_ai_lab_scene,
    draw_background,
    draw_focus_scene,
    draw_habit_scene,
    draw_review_scene,
    draw_stage_header,
    draw_subtitle,
    generate_tts,
    rebuild_history_index,
)

COMFY_URL = "http://127.0.0.1:8188"
COMFY_OUTPUT_ROOT = Path("C:/ComfyUI/output")

JOURNEY_SPEC = SampleSpec(
    title="20秒复杂动画：从分心到完成",
    beats=(
        "先关掉手机提醒，只保留当前这一件事",
        "把目标拆成三张任务卡，从最容易的一张开始",
        "完成后用三句话复盘，再把明天第一步放进日历",
    ),
    scenario="journey",
    palette=((12, 26, 48), (38, 151, 172), (255, 211, 101)),
    voice="zh-CN-YunjianNeural",
    speed="+2%",
)


def no_proxy_opener() -> urllib.request.OpenerDirector:
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    opener = no_proxy_opener()
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{COMFY_URL}{path}", data=data, headers=headers, method=method)
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_comfy_ready() -> None:
    stats = request_json("GET", "/system_stats", timeout=10)
    devices = stats.get("devices", [])
    if not devices:
        raise RuntimeError("ComfyUI is reachable but no device was reported.")

    object_info = request_json("GET", "/object_info", timeout=30)
    required = {"VHS_LoadImagesPath", "VHS_LoadAudio", "VHS_VideoCombine"}
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing required VHS nodes: {missing}")


def render_scene(scene: str, spec: SampleSpec, local_t: float, local_duration: float) -> Image.Image:
    img = draw_background(spec, local_t, local_duration)
    if scene == "focus":
        draw_focus_scene(img, spec, local_t, local_duration)
    elif scene == "ai_lab":
        draw_ai_lab_scene(img, spec, local_t, local_duration)
    elif scene == "review":
        draw_review_scene(img, spec, local_t, local_duration)
    elif scene == "habit":
        draw_habit_scene(img, spec, local_t, local_duration)
    else:
        raise ValueError(f"Unknown scene: {scene}")
    return img


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 1.0 if x >= edge1 else 0.0
    x = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return x * x * (3 - 2 * x)


def render_journey_frame(spec: SampleSpec, t: float, duration: float, idx: int, total: int) -> Image.Image:
    scenes = ("focus", "ai_lab", "review", "habit")
    segment = duration / len(scenes)
    raw_index = min(len(scenes) - 1, int(t / segment))
    local_t = t - raw_index * segment
    img = render_scene(scenes[raw_index], spec, local_t, segment)

    transition = 0.65
    if raw_index < len(scenes) - 1 and local_t > segment - transition:
        blend = smoothstep(segment - transition, segment, local_t)
        next_img = render_scene(scenes[raw_index + 1], spec, 0.0, segment)
        img = Image.blend(img, next_img, blend)

    draw_stage_header(img, spec, t, duration, idx, total)
    draw_subtitle(img, spec, t, duration)

    fade_in = smoothstep(0.0, 0.7, t)
    fade_out = 1 - smoothstep(duration - 0.7, duration, t)
    alpha = max(0.0, min(1.0, fade_in * fade_out))
    if alpha < 0.999:
        img.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, int(255 * (1 - alpha)))))
    return img.convert("RGB")


def write_frame_sequence(task_dir: Path, spec: SampleSpec, duration: float) -> Path:
    frames_dir = task_dir / "frames" / "comfy_sequence"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_count = int(math.ceil(duration * FPS))
    for frame_idx in range(frame_count):
        t = frame_idx / FPS
        frame = render_journey_frame(spec, t, duration, 0, 1)
        frame.save(frames_dir / f"frame_{frame_idx:05d}.png", optimize=True)
        if (frame_idx + 1) % 30 == 0:
            print(f"frames {frame_idx + 1}/{frame_count}", flush=True)
    return frames_dir


def build_comfy_prompt(frames_dir: Path, audio_path: Path, task_id: str, duration: float) -> dict[str, Any]:
    return {
        "1": {
            "class_type": "VHS_LoadImagesPath",
            "inputs": {
                "directory": str(frames_dir),
                "image_load_cap": 0,
                "skip_first_images": 0,
                "select_every_nth": 1,
            },
        },
        "2": {
            "class_type": "VHS_LoadAudio",
            "inputs": {
                "audio_file": str(audio_path),
                "seek_seconds": 0,
                "duration": duration,
            },
        },
        "3": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["1", 0],
                "audio": ["2", 0],
                "frame_rate": FPS,
                "loop_count": 0,
                "filename_prefix": f"pixelle_comfy_20s/{task_id}",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 18,
                "save_metadata": False,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def queue_and_wait(prompt: dict[str, Any], timeout: int = 900) -> Path:
    payload = {"prompt": prompt, "client_id": str(uuid.uuid4())}
    result = request_json("POST", "/prompt", payload, timeout=60)
    prompt_id = result["prompt_id"]
    print(f"comfy prompt_id={prompt_id}", flush=True)

    started = time.time()
    while time.time() - started < timeout:
        history = request_json("GET", f"/history/{prompt_id}", timeout=60)
        if prompt_id in history:
            item = history[prompt_id]
            status = item.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False, indent=2))
            outputs = item.get("outputs", {})
            for output in outputs.values():
                gifs = output.get("gifs") or []
                for gif in gifs:
                    fullpath = gif.get("fullpath")
                    if fullpath and Path(fullpath).exists():
                        return Path(fullpath)
                    filename = gif.get("filename")
                    subfolder = gif.get("subfolder", "")
                    if filename:
                        candidate = COMFY_OUTPUT_ROOT / subfolder / filename
                        if candidate.exists():
                            return candidate
        print("waiting for ComfyUI...", flush=True)
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def write_metadata(task_dir: Path, spec: SampleSpec, video_path: Path, audio_path: Path, duration: float) -> None:
    now = datetime.now().isoformat()
    task_id = task_dir.name
    third = duration / 3
    frames = [
        {
            "index": i,
            "narration": beat,
            "image_prompt": "20-second multi-scene complex 2D animation, combined by ComfyUI VideoHelperSuite",
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
            "mode": "comfy_complex_20s",
            "title": spec.title,
            "text": spec.narration,
            "n_scenes": 4,
            "frame_template": "comfy_complex_20s",
            "tts_inference_mode": "local",
            "tts_voice": spec.voice,
            "video_fps": FPS,
            "video_size": f"{WIDTH}x{HEIGHT}",
        },
        "result": {
            "video_path": str(video_path),
            "duration": duration,
            "file_size": video_path.stat().st_size,
            "n_frames": 4,
        },
        "config": {
            "llm_model": "deepseek-chat",
            "comfyui_url": COMFY_URL,
            "comfyui_used_for_this_batch": True,
            "render_engine": "Pixelle frame animation + ComfyUI VHS_LoadImagesPath/VHS_LoadAudio/VHS_VideoCombine",
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
            "frame_template": "comfy_complex_20s",
            "media_workflow": "comfyui_vhs_video_combine",
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


async def generate(duration: float) -> Path:
    assert_comfy_ready()
    batch_id = "comfy_complex_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    task_id = f"{batch_id}_01_journey_20s"
    task_dir = OUTPUT_ROOT / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    audio_path = task_dir / "frames" / "voice.mp3"
    final_path = task_dir / "final.mp4"

    print("generate narration audio", flush=True)
    await generate_tts(JOURNEY_SPEC, audio_path)

    print("render PNG frame sequence", flush=True)
    frames_dir = write_frame_sequence(task_dir, JOURNEY_SPEC, duration)

    print("queue ComfyUI video combine", flush=True)
    prompt = build_comfy_prompt(frames_dir, audio_path, task_id, duration)
    (task_dir / "comfy_prompt.json").write_text(json.dumps(prompt, ensure_ascii=False, indent=2), encoding="utf-8")
    comfy_video = queue_and_wait(prompt)
    shutil.copy2(comfy_video, final_path)

    print("write metadata and thumbnails", flush=True)
    create_thumbnail(final_path, task_dir / "preview_3s.jpg")
    write_metadata(task_dir, JOURNEY_SPEC, final_path, audio_path, duration)
    await rebuild_history_index([task_id])

    grid_path = OUTPUT_ROOT / f"{batch_id}_preview_grid.jpg"
    create_preview_grid([final_path], grid_path)
    manifest_path = OUTPUT_ROOT / f"{batch_id}_manifest.json"
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "count": 1,
        "duration": duration,
        "videos": [str(final_path)],
        "preview_grid": str(grid_path),
        "comfy_output": str(comfy_video),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"final: {final_path}", flush=True)
    print(f"manifest: {manifest_path}", flush=True)
    print(f"preview_grid: {grid_path}", flush=True)
    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a ComfyUI-combined 20s complex animation MP4.")
    parser.add_argument("--duration", type=float, default=20.0, help="Target video duration in seconds.")
    args = parser.parse_args()
    asyncio.run(generate(args.duration))


if __name__ == "__main__":
    main()
