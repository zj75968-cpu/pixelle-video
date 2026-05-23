"""Agent 工具注册表。

每个工具 = 名称 + 描述 + 入参 schema + async 可调用对象。
LLM 看到名称/描述/参数，决定怎么编排。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class ToolSpec:
    """A single capability exposed to the agent brain."""

    name: str
    description: str
    args_schema: Dict[str, Any]   # JSON-schema-ish dict shown to LLM
    handler: Callable[..., Awaitable[Any]]


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------

async def _list_devices() -> Dict[str, Any]:
    """List Android devices connected via ADB."""
    from pixelle_video.services.device_manager import device_manager

    try:
        device_manager.sync_connected()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sync_connected failed: {e}")

    devices = [
        {
            "serial": d.serial,
            "name": getattr(d, "name", "") or "",
            "theme": getattr(d, "theme", "") or "",
            "notes": getattr(d, "notes", "") or "",
            "status": getattr(d, "status", "unknown"),
        }
        for d in device_manager.get_all()
    ]
    return {"count": len(devices), "devices": devices}


async def _set_device_info(
    serial: str,
    name: str = "",
    theme: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Register or update a device's name / theme / notes."""
    from pixelle_video.services.device_manager import device_manager

    dev = device_manager.add_device(serial=serial, name=name, theme=theme, notes=notes)
    return {
        "serial": dev.serial,
        "name": dev.name,
        "theme": dev.theme,
        "notes": dev.notes,
    }


async def _list_jobs(status_filter: Optional[str] = None) -> Dict[str, Any]:
    """List publish jobs. Optional status_filter: pending/scheduled/running/success/failed/cancelled."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    jobs = publish_scheduler.list_jobs(status_filter=status_filter)
    items = [
        {
            "job_id": j.job_id,
            "serial": j.serial,
            "title": j.title,
            "status": j.status,
            "scheduled_at": j.scheduled_at,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "error": j.error,
        }
        for j in jobs
    ]
    return {"count": len(items), "jobs": items}


async def _cancel_job(job_id: str) -> Dict[str, Any]:
    """Cancel a pending/scheduled/running publish job by its job_id."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    ok = publish_scheduler.cancel_job(job_id)
    return {"job_id": job_id, "cancelled": ok}


async def _list_workflows() -> Dict[str, Any]:
    """List available media (image/video) workflow keys."""
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    workflows = core.media.list_workflows()
    keys = [w["key"] for w in workflows]
    return {"count": len(keys), "workflow_keys": keys}


# --------------------------------------------------------------------------
# Friendly error helper for media-generation pipelines
# --------------------------------------------------------------------------

def _friendly_pipeline_error(exc: BaseException, *, stage: str) -> RuntimeError:
    """Translate a raw pipeline exception into a user/agent-friendly RuntimeError.

    The returned message keeps the original error class/text for debugging,
    and prepends a `[生成失败-<stage>]` tag plus a 修复方向 hint based on
    keyword detection. _classify_error in brain.py will then surface this
    cleanly to the LLM repair loop.
    """
    raw = f"{type(exc).__name__}: {exc}"
    lower = raw.lower()
    hint: str

    if "value_not_in_list" in lower or "value not in list" in lower or "not in (list of" in lower:
        # ComfyUI returns this when a referenced .safetensors/.ckpt is missing
        hint = (
            "ComfyUI workflow 引用了一个 ComfyUI/models/ 下不存在的模型文件，"
            "请检查 node_errors 里报的具体文件名是否已下载"
        )
    elif (
        "connectionrefus" in lower
        or "connect call failed" in lower
        or "connection refused" in lower
        or "connecterror" in lower
        or "no route to host" in lower
    ):
        hint = "依赖服务未启动或端口不通，请确认 ComfyUI / LLM / RunningHub 服务在线"
    elif "timeout" in lower or "timed out" in lower:
        hint = "上游服务响应超时，可重试，或检查 ComfyUI / 网络是否繁忙"
    elif (
        "401" in raw
        or "unauthorized" in lower
        or "invalid api key" in lower
        or "api key" in lower and ("missing" in lower or "not set" in lower)
    ):
        hint = "API key 缺失或无效，检查 config.yaml 里 llm.* / runninghub.* 的 key"
    elif (
        "rate limit" in lower
        or "429" in raw
        or "too many requests" in lower
    ):
        hint = "上游限流，稍后重试或切换 workflow / 模型"
    elif "no such file" in lower or "filenotfounderror" in lower:
        hint = "依赖文件缺失，检查 workflow / 模板路径"
    elif "not initialised" in lower or "not initialized" in lower:
        hint = "依赖服务未初始化，可能 core.initialize() 未完成或 pipeline 没注册"
    elif "llm 未配置" in lower or "llm 未配置" in raw or "llm not configured" in lower:
        hint = "LLM 未配置，请在 config.yaml 填入 llm.api_key / base_url / model"
    else:
        hint = "可重试一次，或换用 workflow / 模型 / 主题再试"

    return RuntimeError(f"[生成失败-{stage}] {raw}（修复方向：{hint}）")


async def _generate_video(
    topic: str,
    n_scenes: int = 3,
    media_workflow: Optional[str] = None,
    pipeline: str = "standard",
    target_duration_s: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate a video from a natural-language topic."""
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    kwargs: Dict[str, Any] = {"mode": "generate"}

    # If caller specified a target duration, auto-derive n_scenes and word-count limits
    # so the TTS/narration total length hits the requested duration.
    # Heuristic: Chinese TTS ~3.5 chars/s; aim for ~7 s per scene.
    if target_duration_s is not None and target_duration_s > 0:
        computed_scenes = max(3, round(target_duration_s / 7))
        chars_per_scene = max(15, round(target_duration_s * 3.5 / computed_scenes))
        kwargs["n_scenes"] = computed_scenes
        kwargs["min_narration_words"] = max(10, chars_per_scene - 8)
        kwargs["max_narration_words"] = chars_per_scene
        logger.info(
            f"[agent] target_duration_s={target_duration_s} → "
            f"n_scenes={computed_scenes}, max_words={chars_per_scene}"
        )
    else:
        kwargs["n_scenes"] = int(n_scenes)

    if media_workflow:
        kwargs["media_workflow"] = media_workflow

    logger.info(f"[agent] generate_video topic={topic!r} kwargs={kwargs}")
    try:
        result = await core.generate_video(text=topic, pipeline=pipeline, **kwargs)
    except RuntimeError:
        raise  # already wrapped (e.g. from a nested tool)
    except Exception as exc:  # noqa: BLE001
        raise _friendly_pipeline_error(exc, stage="generate_video") from exc

    video_path = (
        getattr(result, "video_path", None)
        or getattr(result, "final_video_path", None)
        or getattr(result, "path", None)
    )
    task_id = getattr(result, "task_id", None)
    return {
        "task_id": task_id,
        "video_path": str(video_path) if video_path else None,
        "duration": getattr(result, "duration", None),
    }


async def _enqueue_publish(
    video_path: str,
    title: str,
    body: str = "",
    hashtags: Optional[List[str]] = None,
    device_serial: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    use_schedule: bool = False,
    kind: str = "video",
    dry_run: bool = False,
    post_type: str = "content",
    delete_after_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Enqueue a Xiaohongshu publish job for the given video."""
    from pixelle_video.services.device_manager import device_manager
    from pixelle_video.services.publish_scheduler import publish_scheduler

    # Defensive unwrap: LLM sometimes passes generate_video's whole result dict
    # instead of just the path string.
    if isinstance(video_path, dict):
        unwrapped = (
            video_path.get("video_path")
            or video_path.get("final_video_path")
            or video_path.get("path")
        )
        if not unwrapped:
            raise ValueError(
                f"enqueue_publish.video_path is a dict but no path field found: {list(video_path.keys())}"
            )
        logger.warning(
            f"[agent] enqueue_publish received dict for video_path; "
            f"unwrapped -> {unwrapped}"
        )
        video_path = unwrapped
    video_path = str(video_path)

    # Resolve device serial: explicit -> first connected -> error
    serial = device_serial
    if not serial:
        try:
            device_manager.sync_connected()
        except Exception:  # noqa: BLE001
            pass
        connected = device_manager.list_connected_serials()
        if not connected:
            raise RuntimeError("No Android device connected; cannot enqueue publish.")
        serial = connected[0]

    # 图文模式：自动从 frames/*_composed.png 取场景合成图，或从 images/*.png 等获取图片
    from pathlib import Path as _Path
    images_for_job: list = [video_path]
    if kind == "image_text":
        p = _Path(video_path)
        # Determine the directory containing files
        target_dir = p.parent if p.is_file() else p
        
        # If target_dir is named 'frames' or 'images', the other might be next to it
        task_dir = target_dir
        if target_dir.name in ("frames", "images"):
            task_dir = target_dir.parent
            
        frames_dir = task_dir / "frames"
        images_dir = task_dir / "images"
        
        composed = sorted(frames_dir.glob("*_composed.png")) if frames_dir.exists() else []
        if composed:
            images_for_job = [str(x) for x in composed]
            logger.info(f"[agent] image_text: {len(images_for_job)} composed scene images found in {frames_dir}")
        else:
            raw_imgs = []
            if images_dir.exists():
                for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    raw_imgs.extend(sorted(images_dir.glob(ext)))
            if raw_imgs:
                images_for_job = [str(x) for x in raw_imgs]
                logger.info(f"[agent] image_text: {len(images_for_job)} raw images found in {images_dir}")
            else:
                logger.warning(f"[agent] image_text: no composed or raw images found, falling back to video path")

    # 按每日计划自动安排：若 use_schedule=True 且未手动指定 scheduled_at，
    # 则从 daily_schedule_times 中取该设备下一个未被占用的时间槽。
    if use_schedule and not scheduled_at:
        next_slot = publish_scheduler.next_available_slot(serial)
        if next_slot:
            scheduled_at = next_slot.isoformat()
            logger.info(f"[agent] use_schedule: assigned slot {scheduled_at} for {serial}")
        else:
            logger.warning(f"[agent] use_schedule: no available slot found for {serial}; queuing immediately")

    job = publish_scheduler.add_job(
        serial=serial,
        task_id=f"agent-{uuid.uuid4().hex[:8]}",
        title=title,
        body=body,
        hashtags=list(hashtags or []),
        images=images_for_job,
        scheduled_at=scheduled_at,
        kind=kind,
        video_path=video_path,
        dry_run=bool(dry_run),
        post_type=post_type if post_type in ("content", "traffic") else "content",
        delete_after_hours=(
            float(delete_after_hours)
            if (delete_after_hours is not None and float(delete_after_hours) > 0)
            else None
        ),
    )
    return {
        "job_id": job.job_id,
        "serial": job.serial,
        "status": job.status,
        "scheduled_at": job.scheduled_at,
        "dry_run": job.dry_run,
        "post_type": job.post_type,
        "delete_after_hours": job.delete_after_hours,
    }


async def _phone_publish(
    title: str,
    media_path: str = "",
    body: str = "",
    hashtags: Optional[List[str]] = None,
    wait: bool = True,
    platform: str = "xhs",
) -> Dict[str, Any]:
    """通过手机 HTTP Agent 发布内容（手机本地 uiautomator2 自控，无需 ADB/USB）。"""
    import asyncio
    from pixelle_video.config import config_manager
    from pixelle_video.services.phone_agent_client import publish_http, wait_for_publish

    cfg = config_manager.config
    agent_url = cfg.phone_agent.url.strip()
    agent_token = cfg.phone_agent.token.strip()

    if not agent_url:
        raise RuntimeError(
            "未配置 phone_agent.url，请在设置页面填写手机 HTTP Agent 地址（如 http://192.168.x.x:7777）"
        )

    result = publish_http(
        title=title,
        agent_url=agent_url,
        token=agent_token,
        body=body,
        hashtags=list(hashtags or []),
        media_path=media_path,
        platform=platform,
    )
    if not result.get("ok"):
        raise RuntimeError(f"phone_publish 提交失败: {result.get('error')}")

    task_id = result["task_id"]
    logger.info(f"[agent] phone_publish: task_id={task_id}")

    if wait:
        final = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: wait_for_publish(task_id, agent_url=agent_url, token=agent_token, max_wait=300),
        )
        return {"task_id": task_id, **final}

    return {"task_id": task_id, "status": "queued", "message": "任务已提交（未等待）"}


async def _list_tasks(
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List historical video-generation tasks (from output/<task_id>/metadata.json)."""
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    persistence = core.persistence
    if persistence is None:
        raise RuntimeError("PersistenceService not initialized")

    raw = await persistence.list_tasks(status=status, limit=max(1, int(limit)))
    tasks = []
    for m in raw:
        tasks.append({
            "task_id": m.get("task_id"),
            "status": m.get("status"),
            "title": (m.get("input") or {}).get("text") or m.get("title"),
            "created_at": m.get("created_at"),
            "completed_at": m.get("completed_at"),
            "duration": (m.get("result") or {}).get("duration"),
            "video_path": (m.get("result") or {}).get("video_path")
                or (m.get("result") or {}).get("final_video_path"),
        })
    return {"count": len(tasks), "tasks": tasks}


async def _delete_task(task_id: str) -> Dict[str, Any]:
    """Delete a historical generation task directory by task_id."""
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    persistence = core.persistence
    if persistence is None:
        raise RuntimeError("PersistenceService not initialized")

    existed = await persistence.task_exists(task_id)
    if not existed:
        return {"task_id": task_id, "deleted": False, "reason": "not_found"}
    await persistence.delete_task(task_id)
    return {"task_id": task_id, "deleted": True}


async def _cleanup_outputs(
    days: int = 7,
    keep_latest: int = 5,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Clean up old task output directories.

    Strategy:
    - Sort all task dirs by mtime (newest first).
    - Always keep the `keep_latest` newest dirs.
    - Among the rest, mark as candidates any dir whose mtime is older than `days` days ago.
    - If dry_run is True (default), only report; otherwise delete via persistence.delete_task.
    """
    import time
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    persistence = core.persistence
    if persistence is None:
        raise RuntimeError("PersistenceService not initialized")

    output_dir = persistence.output_dir
    days = max(0, int(days))
    keep_latest = max(0, int(keep_latest))
    cutoff_ts = time.time() - days * 86400

    entries: List[Dict[str, Any]] = []
    for task_dir in output_dir.iterdir():
        if not task_dir.is_dir():
            continue
        # Only consider entries that look like task directories
        # (must have a metadata.json or final.mp4 to be safe).
        if not ((task_dir / "metadata.json").exists() or (task_dir / "final.mp4").exists()):
            continue
        try:
            mtime = task_dir.stat().st_mtime
        except OSError:
            continue
        # Compute size
        size = 0
        for p in task_dir.rglob("*"):
            try:
                if p.is_file():
                    size += p.stat().st_size
            except OSError:
                continue
        entries.append({
            "task_id": task_dir.name,
            "mtime": mtime,
            "size_bytes": size,
        })

    # Sort newest first
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    kept_latest_ids = {e["task_id"] for e in entries[:keep_latest]}

    items: List[Dict[str, Any]] = []
    deleted_count = 0
    bytes_freed = 0
    for e in entries:
        is_protected = e["task_id"] in kept_latest_ids
        is_old = e["mtime"] < cutoff_ts
        is_candidate = (not is_protected) and is_old
        will_delete = is_candidate and (not dry_run)

        if will_delete:
            try:
                await persistence.delete_task(e["task_id"])
                deleted_count += 1
                bytes_freed += e["size_bytes"]
                status = "deleted"
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"cleanup_outputs: failed to delete {e['task_id']}: {exc}")
                status = f"error:{exc}"
        elif is_candidate:
            status = "candidate"
        elif is_protected:
            status = "kept_latest"
        else:
            status = "kept_recent"

        items.append({
            "task_id": e["task_id"],
            "size_mb": round(e["size_bytes"] / (1024 * 1024), 2),
            "age_days": round((time.time() - e["mtime"]) / 86400, 2),
            "status": status,
        })

    candidate_count = sum(1 for it in items if it["status"] == "candidate")
    return {
        "dry_run": dry_run,
        "days": days,
        "keep_latest": keep_latest,
        "scanned": len(entries),
        "candidates": candidate_count if dry_run else 0,
        "deleted": deleted_count,
        "bytes_freed": bytes_freed,
        "mb_freed": round(bytes_freed / (1024 * 1024), 2),
        "items": items[:50],  # truncate long listings for LLM
    }

async def _recommend_models(
    user_prompt: str,
    task_kind: str = "text-to-video",
    top_n: int = 3,
) -> Dict[str, Any]:
    """Recommend RunningHub low-price models for a generation goal.

    Wraps `runninghub_recommender.recommend`. task_kind must be one of:
    text-to-image / image-to-image / text-to-video / image-to-video /
    start-end-to-video / video-tools.
    """
    from pixelle_video.service import pixelle_video as core
    from pixelle_video.services.runninghub_recommender import recommend

    if not getattr(core, "_initialized", False):
        await core.initialize()
    if core.llm is None:
        raise RuntimeError("LLM service not configured")

    allowed = {
        "text-to-image", "image-to-image", "text-to-video",
        "image-to-video", "start-end-to-video", "video-tools",
    }
    if task_kind not in allowed:
        raise ValueError(f"task_kind must be one of {sorted(allowed)}, got {task_kind!r}")

    rec = await recommend(
        llm=core.llm,
        user_prompt=user_prompt,
        task_kind=task_kind,  # type: ignore[arg-type]
        top_n=max(1, int(top_n)),
    )
    return {
        "task_kind": task_kind,
        "notes": rec.notes,
        "picks": [
            {
                "workflow_key": p.workflow_key,
                "score": p.score,
                "reason": p.reason,
                "suggested_params": p.suggested_params,
            }
            for p in rec.picks
        ],
    }


async def _recommend_device(
    topic: str,
    top_n: int = 3,
    only_connected: bool = True,
) -> Dict[str, Any]:
    """Recommend Android devices for a publishing topic based on their `theme`.

    Strategy:
      1. Fetch all registered devices via device_manager.
      2. If LLM is available, ask it to pick the best matches given each
         device's `name / theme / notes / status` and the user's topic.
      3. Otherwise, fall back to a deterministic keyword-overlap scorer
         over (theme + name + notes).
    """
    from pixelle_video.service import pixelle_video as core
    from pixelle_video.services.device_manager import device_manager

    try:
        device_manager.sync_connected()
    except Exception:  # noqa: BLE001
        pass

    devices = device_manager.get_all()
    candidates = []
    for d in devices:
        # DeviceInfo uses `connected: bool`; derive a status string for display
        is_connected = getattr(d, "connected", False)
        status = "connected" if is_connected else "disconnected"
        if only_connected and not is_connected:
            continue
        candidates.append({
            "serial": d.serial,
            "name": getattr(d, "name", "") or "",
            "theme": getattr(d, "theme", "") or "",
            "notes": getattr(d, "notes", "") or "",
            "status": status,
        })

    if not candidates:
        return {
            "topic": topic,
            "method": "none",
            "picks": [],
            "notes": "没有满足条件的设备（only_connected="
                     f"{only_connected}）。",
        }

    top_n = max(1, min(int(top_n), len(candidates)))

    if not getattr(core, "_initialized", False):
        try:
            await core.initialize()
        except Exception:  # noqa: BLE001
            pass

    # ---- Path A: LLM-based ranking ---------------------------------------
    llm = getattr(core, "llm", None)
    if llm is not None:
        try:
            from pydantic import BaseModel, Field

            class _Pick(BaseModel):
                serial: str = Field(description="device serial")
                score: int = Field(description="0-100 match score")
                reason: str = Field(description="简短中文理由")

            class _Result(BaseModel):
                picks: List[_Pick] = Field(description="按 score 降序的设备推荐")

            prompt = (
                "你是发布调度助手。下面给出可用安卓设备清单（每台带主题 / 名称 / "
                "备注），请根据用户的发布主题，挑出最匹配的设备并打分。"
                "评分要点：theme 与主题语义匹配优先；name/notes 含相关词次之；"
                "若没有相关设备，所有 score 给 50 以下。\n\n"
                f"用户主题: {topic}\n\n"
                f"候选设备: {candidates}\n\n"
                f"请输出 Top-{top_n}，按 score 降序。"
            )
            res: _Result = await llm(
                prompt=prompt,
                response_type=_Result,
                temperature=0.2,
                max_tokens=600,
            )
            picks = [
                {"serial": p.serial, "score": int(p.score), "reason": p.reason}
                for p in res.picks[:top_n]
            ]
            return {
                "topic": topic,
                "method": "llm",
                "picks": picks,
                "candidates": candidates,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[recommend_device] LLM path failed, fallback: {exc}")

    # ---- Path B: keyword fallback ----------------------------------------
    topic_norm = (topic or "").strip().lower()
    tokens = [t for t in topic_norm.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if t]
    if not tokens:
        tokens = [topic_norm] if topic_norm else []

    scored = []
    for c in candidates:
        hay = " ".join([c["theme"], c["name"], c["notes"]]).lower()
        hits = sum(1 for tok in tokens if tok and tok in hay)
        score = 50 + min(50, hits * 25) if hits else (40 if c["theme"] else 30)
        reason = (
            f"theme/name/notes 命中 {hits} 个关键词"
            if hits else
            ("有 theme 但未直接命中关键词" if c["theme"] else "无 theme，仅作兜底")
        )
        scored.append({"serial": c["serial"], "score": score, "reason": reason})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "topic": topic,
        "method": "fallback_keyword",
        "picks": scored[:top_n],
        "candidates": candidates,
    }


# --------------------------------------------------------------------------
# Image-text post pipeline & queue-management tools (added so the agent brain
# can drive the same set of operations available in the web UI).
# --------------------------------------------------------------------------

async def _generate_image_text_post(
    topic: str,
    image_count: int = 6,
    post_tone: str = "种草",
    hashtag_count: int = 5,
    template_size: str = "1080x1080",
    style: str = "",
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    post_type: str = "content",
    traffic_ttl_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Run the image-text post pipeline.

    Returns task_id / output_dir / title / body / hashtags / images / post_type /
    traffic_ttl_hours. The traffic_ttl_hours is also persisted into
    output/<task_id>/post_params.json so the publish form can auto-fill
    delete_after_hours later.
    """
    import json
    from datetime import datetime
    from pathlib import Path as _Path

    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    pipeline = (core.pipelines or {}).get("image_text_post")
    if pipeline is None:
        raise RuntimeError("image_text_post pipeline not initialised")

    pt = post_type if post_type in ("content", "traffic") else "content"
    try:
        result = await pipeline(
            topic=topic,
            image_count=int(image_count),
            post_tone=post_tone,
            hashtag_count=int(hashtag_count),
            template_size=template_size,
            style=style,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            post_type=pt,
        )
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _friendly_pipeline_error(exc, stage="generate_image_text_post") from exc

    # Persist post_params.json mirroring the web layer so publish UI prefills.
    try:
        ttl_val = float(traffic_ttl_hours) if traffic_ttl_hours is not None else 0.0
    except (TypeError, ValueError):
        ttl_val = 0.0
    history = {
        "topic": topic,
        "image_count": int(image_count),
        "post_tone": post_tone,
        "template_size": template_size,
        "style": style,
        "hashtag_count": int(hashtag_count),
        "aspect_ratio": aspect_ratio,
        "image_size": image_size,
        "post_type": pt,
        "traffic_ttl_hours": ttl_val if pt == "traffic" else 0.0,
        "saved_at": datetime.now().isoformat(),
        "source": "agent",
    }
    try:
        (_Path(result.output_dir) / "post_params.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[agent] failed to write post_params.json: {exc}")

    return {
        "task_id": _Path(result.output_dir).name,
        "output_dir": str(result.output_dir),
        "title": result.content.title,
        "body": result.content.body,
        "hashtags": list(result.content.hashtags or []),
        "images": (
            [str(p) for p in sorted((result.output_dir / "frames").glob("*_composed.png"))]
            if (result.output_dir / "frames").exists() and list((result.output_dir / "frames").glob("*_composed.png"))
            else [str(p) for p in sorted((result.output_dir / "images").glob("*.png"))]
        ),
        "post_type": pt,
        "traffic_ttl_hours": ttl_val if pt == "traffic" else 0.0,
    }


async def _delete_published_post(job_id: str) -> Dict[str, Any]:
    """Delete a successfully published XHS post by job_id (uses uiautomator2)."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    ok = await publish_scheduler.delete_post_now(job_id)
    return {"job_id": job_id, "deleted": bool(ok)}


async def _remove_job(job_id: str) -> Dict[str, Any]:
    """Remove a single job from the publish queue regardless of status."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    ok = publish_scheduler.remove_job(job_id)
    return {"job_id": job_id, "removed": bool(ok)}


async def _bulk_remove_jobs(statuses: List[str]) -> Dict[str, Any]:
    """Bulk-remove queue entries whose status matches one of the given statuses."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    count = publish_scheduler.bulk_remove(list(statuses or []))
    return {"statuses": list(statuses or []), "removed_count": int(count)}


async def _bulk_cancel_pending_jobs() -> Dict[str, Any]:
    """Cancel every pending/scheduled job currently in the queue."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    count = publish_scheduler.bulk_cancel_pending()
    return {"cancelled_count": int(count)}


async def _execute_job_now(job_id: str) -> Dict[str, Any]:
    """Force a pending/scheduled job to run immediately (jumps the queue)."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    ok = await publish_scheduler.execute_now(job_id)
    return {"job_id": job_id, "triggered": bool(ok)}


async def _get_job(job_id: str) -> Dict[str, Any]:
    """Fetch a publish job's full record (status, scheduled_at, error, etc.)."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    job = publish_scheduler.get_job(job_id)
    if job is None:
        return {"found": False, "job_id": job_id}
    return {"found": True, "job": job.to_dict()}


async def _polish_text(raw: str, kind: str = "body") -> Dict[str, Any]:
    """LLM polish a piece of title / body / topic text. Returns polished + rationale."""
    from pixelle_video.service import pixelle_video as core

    if kind not in {"title", "body", "topic"}:
        raise ValueError(f"kind must be one of title/body/topic, got {kind!r}")

    if not getattr(core, "_initialized", False):
        await core.initialize()
    if core.llm is None:
        raise RuntimeError("LLM 未配置（请在 config.yaml 配置 llm.*）")

    # Reuse the same prompt builder as the web polish component.
    from web.components.polish import _build_prompt, _PolishResult  # type: ignore

    prompt = _build_prompt(raw, kind)  # type: ignore[arg-type]
    result = await core.llm(
        prompt=prompt,
        response_type=_PolishResult,
        temperature=0.4,
        max_tokens=600,
    )
    return {
        "kind": kind,
        "original": raw,
        "polished": result.polished,
        "rationale": result.rationale,
    }


async def _read_post_params(task_id: str) -> Dict[str, Any]:
    """Read output/<task_id>/post_params.json so the agent can inspect generated content."""
    import json
    from pathlib import Path
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()
    persistence = core.persistence
    if persistence is None:
        raise RuntimeError("PersistenceService not initialized")

    output_root = Path(persistence.output_dir)
    pp = output_root / task_id / "post_params.json"
    if not pp.exists():
        return {"found": False, "task_id": task_id, "path": str(pp)}
    try:
        data = json.loads(pp.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"found": False, "task_id": task_id, "path": str(pp), "error": str(e)}

    frames_dir = output_root / task_id / "frames"
    composed = sorted(frames_dir.glob("*_composed.png")) if frames_dir.exists() else []
    if not composed:
        images_dir = output_root / task_id / "images"
        if images_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                composed.extend(sorted(images_dir.glob(ext)))
    return {
        "found": True,
        "task_id": task_id,
        "path": str(pp),
        "post_params": data,
        "composed_image_count": len(composed),
        "composed_images": [str(p) for p in composed],
    }


async def _force_check_expired_ttl() -> Dict[str, Any]:
    """Manually trigger a TTL sweep right now (instead of waiting 15 min)."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    before = sum(1 for j in publish_scheduler.list_jobs() if j.status == "deleted")
    await publish_scheduler.check_and_delete_expired()
    after = sum(1 for j in publish_scheduler.list_jobs() if j.status == "deleted")
    return {"newly_deleted": max(0, after - before), "deleted_total": after}


async def _ttl_watcher_status() -> Dict[str, Any]:
    """Check whether the background TTL watcher thread is running and its interval."""
    from pixelle_video.services.publish_scheduler import publish_scheduler

    return publish_scheduler.ttl_watcher_status()


# ---- banned-keywords tools ----

async def _list_banned_keywords() -> Dict[str, Any]:
    """List current XHS banned keywords + filter mode."""
    from pixelle_video.utils import banned_keywords as bk

    state = bk.get_state()
    return {
        "count": len(state["keywords"]),
        "mode": state["mode"],
        "mask": state["mask"],
        "updated_at": state.get("updated_at"),
        "keywords": state["keywords"],
    }


async def _add_banned_keywords(
    keywords: List[str],
    mode: str = "append",
) -> Dict[str, Any]:
    """Add (or replace) banned keywords. mode='append' (default) or 'replace'."""
    from pixelle_video.utils import banned_keywords as bk

    if not isinstance(keywords, list) or not keywords:
        raise ValueError("keywords 必须是非空字符串数组")
    if mode not in ("append", "replace"):
        raise ValueError("mode 必须是 'append' 或 'replace'")
    if mode == "replace":
        new_list = bk.replace_all(keywords)
    else:
        new_list = bk.add_keywords(keywords)
    return {"count": len(new_list), "mode": mode, "keywords": new_list}


async def _preview_banned_filter(text: str) -> Dict[str, Any]:
    """Run the banned-keywords filter on a sample text without persisting anything."""
    from pixelle_video.utils import banned_keywords as bk

    if not isinstance(text, str):
        raise ValueError("text 必须是字符串")
    cleaned, hits = bk.filter_text(text)
    return {
        "original": text,
        "cleaned": cleaned,
        "hits": hits,
        "hit_count": len(hits),
    }


# ---- publish knowledge tools ----

async def _query_publish_knowledge(query: str, top_k: int = 3) -> Dict[str, Any]:
    """Search the XHS publish failure knowledge base for known problems and solutions."""
    from pixelle_video.agent.publish_knowledge import publish_knowledge

    hits = publish_knowledge.search(query, top_k=int(top_k))
    return {
        "count": len(hits),
        "entries": [
            {
                "id": e.id,
                "problem": e.problem,
                "root_cause": e.root_cause,
                "solution": e.solution,
                "resolution_steps": e.resolution_steps,
                "resolved": e.resolved,
                "times_seen": e.times_seen,
                "job_kind": e.job_kind,
            }
            for e in hits
        ],
    }


async def _record_publish_finding(
    problem: str,
    root_cause: str,
    solution: str,
    resolution_steps: Optional[List[str]] = None,
    job_kind: str = "",
    error_pattern: str = "",
    resolved: bool = True,
) -> Dict[str, Any]:
    """Manually record a publish problem + solution into the knowledge base."""
    from pixelle_video.agent.publish_knowledge import publish_knowledge, KnowledgeEntry

    entry = KnowledgeEntry(
        job_kind=job_kind,
        problem=problem,
        error_pattern=error_pattern or problem[:40],
        root_cause=root_cause,
        solution=solution,
        resolution_steps=resolution_steps or [],
        resolved=resolved,
    )
    saved = publish_knowledge.add_or_update(entry)
    return {
        "id": saved.id,
        "problem": saved.problem,
        "resolved": saved.resolved,
        "times_seen": saved.times_seen,
    }


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

TOOLS: List[ToolSpec] = [
    ToolSpec(
        name="list_devices",
        description="列出所有已登记/连接的安卓设备（含 serial / name / theme / status）。需要选择发布目标设备前先调用。",
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_list_devices,
    ),
    ToolSpec(
        name="set_device_info",
        description="为某台设备登记或更新名称/主题/备注。常用于给新连接的设备取一个易记的名字。",
        args_schema={
            "type": "object",
            "properties": {
                "serial": {"type": "string", "description": "ADB serial"},
                "name": {"type": "string", "description": "设备友好名称"},
                "theme": {"type": "string", "description": "主题/账号定位（如 美食 / 旅行）"},
                "notes": {"type": "string", "description": "其他备注"},
            },
            "required": ["serial"],
        },
        handler=_set_device_info,
    ),
    ToolSpec(
        name="list_workflows",
        description="列出所有可用的图像/视频生成 workflow key（如 'runninghub/image_qwen.json'）。",
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_list_workflows,
    ),
    ToolSpec(
        name="generate_video",
        description=(
            "根据主题文字生成一个视频，返回最终视频文件路径。"
            "topic 必填；"
            "target_duration_s 为目标时长（秒），系统自动根据时长推算分镜数和台词字数；"
            "n_scenes 默认 3（与 target_duration_s 互斥，指定 target_duration_s 时自动计算）；"
            "media_workflow 可选，用于指定图像/视频生成 workflow。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "视频选题/主题"},
                "target_duration_s": {
                    "type": "integer",
                    "description": (
                        "目标视频时长（秒）。填写后系统自动估算分镜数和台词长度。"
                        "示例：30 表示约30秒视频。"
                    ),
                },
                "n_scenes": {
                    "type": "integer",
                    "description": "镜头数量（指定 target_duration_s 时无需填写）",
                    "default": 3,
                },
                "media_workflow": {
                    "type": "string",
                    "description": "可选 workflow key，未填则使用配置默认值",
                },
            },
            "required": ["topic"],
        },
        handler=_generate_video,
    ),
    ToolSpec(
        name="enqueue_publish",
        description=(
            "把已生成的视频加入小红书发布队列。video_path 必填，可由 generate_video 的返回值给出。"
            "kind 可选 video（视频笔记，默认）或 image_text（图文笔记，自动取场景合成图）。"
            "若未指定 device_serial，自动选取第一台已连接设备。"
            "若希望按每日计划自动分配时间，设置 use_schedule=true；"
            "或手动指定 scheduled_at（ISO-8601）；两者都不填则立即发布。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "本地视频文件绝对路径"},
                "title": {"type": "string", "description": "笔记标题"},
                "body": {"type": "string", "description": "笔记正文", "default": ""},
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "话题标签数组",
                },
                "device_serial": {
                    "type": "string",
                    "description": "目标安卓设备 serial，留空则使用第一台已连接设备",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": "可选 ISO-8601 计划发布时间，留空表示立即发布",
                },
                "use_schedule": {
                    "type": "boolean",
                    "description": (
                        "true 表示按每日计划自动安排：从配置的时间段中取该设备下一个未被占用的时间槽。"
                        "与 scheduled_at 互斥；scheduled_at 有值时忽略本参数。"
                    ),
                    "default": False,
                },
                "kind": {
                    "type": "string",
                    "enum": ["video", "image_text"],
                    "description": (
                        "发布类型。video=视频笔记（上传.mp4，默认）；"
                        "image_text=图文笔记（自动取 frames/*_composed.png 场景合成图上传）。"
                    ),
                    "default": "video",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "true 表示干跑测试：不点最终发布按钮，仅验证推送/选图/填文链路，避免误发。默认 false。",
                    "default": False,
                },
                "post_type": {
                    "type": "string",
                    "enum": ["content", "traffic"],
                    "description": "帖子类型。content=干货帖（长期保留）；traffic=引流帖（可自动删除）。",
                    "default": "content",
                },
                "delete_after_hours": {
                    "type": "number",
                    "description": "仅 traffic 帖子有意义：发布成功后经过指定小时数自动删除（>0 启用，留空/0 不删除）。",
                },
            },
            "required": ["video_path", "title"],
        },
        handler=_enqueue_publish,
    ),
    ToolSpec(
        name="phone_publish",
        description=(
            "通过手机 HTTP Agent 在手机本地发布小红书内容（无需 USB/ADB）。"
            "手机端运行 phone_agent.py，使用本机 uiautomator2 自动操作 XHS 界面。"
            "需在设置页面配置 phone_agent.url 和 token。"
            "media_path 为手机本地媒体文件路径（先用 push_file 推送，或留空仅发纯文字笔记）。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题（必填，最多20字）"},
                "media_path": {
                    "type": "string",
                    "description": "手机端媒体文件路径，如 /sdcard/DCIM/PixelleVideo/xxx.mp4",
                    "default": "",
                },
                "body": {"type": "string", "description": "笔记正文", "default": ""},
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "话题标签，如 [\"健康\", \"养生\"]",
                },
                "wait": {
                    "type": "boolean",
                    "description": "true（默认）= 等待发布完成再返回；false = 立即返回 task_id 异步查询",
                    "default": True,
                },
                "platform": {
                    "type": "string",
                    "enum": ["xhs"],
                    "description": "目标平台，目前仅支持 xhs（小红书）",
                    "default": "xhs",
                },
            },
            "required": ["title"],
        },
        handler=_phone_publish,
    ),
    ToolSpec(
        name="list_jobs",
        description=(
            "查看发布队列里的任务。可选 status_filter：pending/scheduled/running/success/failed/cancelled。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "可选状态过滤",
                    "enum": ["pending", "scheduled", "running", "success", "failed", "cancelled"],
                },
            },
            "required": [],
        },
        handler=_list_jobs,
    ),
    ToolSpec(
        name="cancel_job",
        description="按 job_id 取消一个尚未完成的发布任务。",
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "发布任务 ID"},
            },
            "required": ["job_id"],
        },
        handler=_cancel_job,
    ),
    ToolSpec(
        name="list_tasks",
        description=(
            "列出历史视频生成任务（output/<task_id> 下的 metadata.json）。"
            "可选 status 过滤（pending/running/completed/failed/cancelled），limit 默认 20，按创建时间倒序。"
            "返回每条 task 的 task_id / status / title / created_at / completed_at / duration / video_path。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "可选状态过滤",
                    "enum": ["pending", "running", "completed", "failed", "cancelled"],
                },
                "limit": {"type": "integer", "description": "最多返回条数", "default": 20},
            },
            "required": [],
        },
        handler=_list_tasks,
    ),
    ToolSpec(
        name="delete_task",
        description="按 task_id 删除一个历史生成任务（连同 output/<task_id> 目录一起移除）。不可恢复，请谨慎使用。",
        args_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "历史任务 ID，如 20260512_162614_cdf3"},
            },
            "required": ["task_id"],
        },
        handler=_delete_task,
    ),
    ToolSpec(
        name="cleanup_outputs",
        description=(
            "清理 output/ 下的历史任务目录，释放磁盘空间。"
            "默认 dry_run=True 只列出候选不删除；确认后再用 dry_run=False 实际删除。"
            "days：保留最近 N 天内的任务（默认 7）；keep_latest：无论年龄都保留的最新 N 条（默认 5）。"
            "返回 scanned / candidates / deleted / mb_freed / items[]。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "保留最近 N 天内的任务", "default": 7},
                "keep_latest": {"type": "integer", "description": "始终保留的最新条数", "default": 5},
                "dry_run": {"type": "boolean", "description": "True=仅模拟", "default": True},
            },
            "required": [],
        },
        handler=_cleanup_outputs,
    ),
    ToolSpec(
        name="recommend_models",
        description=(
            "根据用户生成需求，从 RunningHub 低价渠道模型清单里挑出最适合的 Top-N 个 workflow，"
            "并给出评分、理由、建议参数。task_kind 必填，取值："
            "text-to-image / image-to-image / text-to-video / image-to-video / start-end-to-video / video-tools。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "user_prompt": {
                    "type": "string",
                    "description": "用户的生成需求/提示词（自然语言）",
                },
                "task_kind": {
                    "type": "string",
                    "description": "任务类型",
                    "enum": [
                        "text-to-image", "image-to-image", "text-to-video",
                        "image-to-video", "start-end-to-video", "video-tools",
                    ],
                    "default": "text-to-video",
                },
                "top_n": {"type": "integer", "description": "返回条数 1-5", "default": 3},
            },
            "required": ["user_prompt"],
        },
        handler=_recommend_models,
    ),
    ToolSpec(
        name="recommend_device",
        description=(
            "根据待发布的主题/选题，从已登记的安卓设备里挑出最匹配的 Top-N 台。"
            "优先使用每台设备的 `theme`（在『发布管理』里登记的账号定位/主题）做语义匹配，"
            "找不到完全匹配时回退到 name/notes 的关键词命中。"
            "返回的 picks[0].serial 可以直接作为 enqueue_publish.device_serial。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "本次要发布的主题/选题（如『职场效率』『萌宠日常』）",
                },
                "top_n": {"type": "integer", "description": "返回条数 1-5", "default": 3},
                "only_connected": {
                    "type": "boolean",
                    "description": "True=只在已连接设备中推荐；False=也考虑离线设备",
                    "default": True,
                },
            },
            "required": ["topic"],
        },
        handler=_recommend_device,
    ),
    ToolSpec(
        name="generate_image_text_post",
        description=(
            "运行图文帖子生成流水线（生成标题/正文/话题/分镜图）。topic 必填。"
            "**必须根据用户语义选择 post_type**："
            "用户说「干货 / 教程 / 方法 / 技巧 / 清单 / 攻略 / 避坑 / 科普 / 新手必看」"
            "→ post_type='content'（📚 干货帖，结构化分点、不带强引导话术）；"
            "用户说「引流 / 钩子 / 转化 / 私信 / 评论扣 1 / 主页有完整版 / 营销 / 拉新 / 悬念」"
            "→ post_type='traffic'（📢 引流帖，制造钩子 + 必带 CTA）。"
            "post_type='traffic' + traffic_ttl_hours=24 表示：生成一个引流帖，"
            "在发布到小红书后 24 小时内自动删除（TTL 会写入 post_params.json，"
            "之后调用 enqueue_publish 时配合 delete_after_hours 使用）。"
            "返回 task_id / output_dir / title / body / hashtags / images / post_type。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "创作主题"},
                "image_count": {"type": "integer", "description": "图片数量 3-9", "default": 6},
                "post_tone": {
                    "type": "string",
                    "enum": ["种草", "干货", "日常", "搞笑", "情感"],
                    "default": "种草",
                },
                "hashtag_count": {"type": "integer", "description": "话题标签数 3-10", "default": 5},
                "template_size": {"type": "string", "description": "图片分辨率", "default": "1080x1080"},
                "style": {"type": "string", "description": "图片风格（可选）", "default": ""},
                "aspect_ratio": {"type": "string", "description": "aspectRatio（如 1:1 / 3:4 / 9:16），留空不指定"},
                "image_size": {"type": "string", "description": "imageSize（仅部分 Gemini 模型支持），留空不指定"},
                "post_type": {
                    "type": "string",
                    "enum": ["content", "traffic"],
                    "description": "content=干货帖；traffic=引流帖",
                    "default": "content",
                },
                "traffic_ttl_hours": {
                    "type": "number",
                    "description": "引流帖自动删除 TTL（小时）。仅 post_type='traffic' 有效；0/留空表示不自动删除。",
                },
            },
            "required": ["topic"],
        },
        handler=_generate_image_text_post,
    ),
    ToolSpec(
        name="delete_published_post",
        description=(
            "通过 uiautomator2 删除一个 *已成功发布* 的小红书帖子（按 job_id 查找标题并在 App 内执行删除）。"
            "用于配合 traffic 帖子 TTL 到期后清理，或人工误发后撤回。不可恢复。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "publish_scheduler 中的 job_id（必须是 success/已发布的 job）"},
            },
            "required": ["job_id"],
        },
        handler=_delete_published_post,
    ),
    ToolSpec(
        name="remove_job",
        description=(
            "把单个发布任务从队列中移除（仅清记录，不会撤回已发出的帖子）。"
            "适合清理 success / failed / cancelled 等终态条目。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "publish_scheduler 中的 job_id"},
            },
            "required": ["job_id"],
        },
        handler=_remove_job,
    ),
    ToolSpec(
        name="bulk_remove_jobs",
        description=(
            "按状态批量清理队列条目（仅删记录，不撤回帖子）。常见用法：清理已完成 = "
            "statuses=['success','done','deleted']；清理失败/取消 = statuses=['failed','cancelled']。"
            "返回 removed_count。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "statuses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["pending", "scheduled", "running", "success", "done", "deleted", "failed", "cancelled"],
                    },
                    "description": "要清理的状态列表",
                },
            },
            "required": ["statuses"],
        },
        handler=_bulk_remove_jobs,
    ),
    ToolSpec(
        name="bulk_cancel_pending_jobs",
        description="取消队列中所有 pending/scheduled 状态的任务（一键停掉所有未发布的）。返回 cancelled_count。",
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_bulk_cancel_pending_jobs,
    ),
    ToolSpec(
        name="execute_job_now",
        description=(
            "强制立即执行一个 pending/scheduled 的发布任务（跳过队列等待）。"
            "返回 triggered=true 表示已触发。任务实际状态请用 list_jobs 复查。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "publish_scheduler 中的 job_id"},
            },
            "required": ["job_id"],
        },
        handler=_execute_job_now,
    ),
    ToolSpec(
        name="get_job",
        description=(
            "按 job_id 读取单条发布任务的完整字段（含 status / scheduled_at / error / retry_count / "
            "post_type / delete_after_hours / screenshots 等）。"
            "用于在 list_jobs 看到大致信息后，进一步排查某条任务为什么失败或还没发。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "publish_scheduler 中的 job_id"},
            },
            "required": ["job_id"],
        },
        handler=_get_job,
    ),
    ToolSpec(
        name="polish_text",
        description=(
            "用 LLM 一键润色一段文本（标题 / 正文 / 选题）。"
            "kind='title' 限 20 汉字、'topic' 限 80 汉字、'body' 控制在原长 1.4 倍以内。"
            "返回 polished（润色后）+ rationale（一句话改动思路）。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "raw": {"type": "string", "description": "原始文本"},
                "kind": {
                    "type": "string",
                    "enum": ["title", "body", "topic"],
                    "description": "润色目标：title=标题；body=正文；topic=选题/主题",
                    "default": "body",
                },
            },
            "required": ["raw"],
        },
        handler=_polish_text,
    ),
    ToolSpec(
        name="read_post_params",
        description=(
            "读取 output/<task_id>/post_params.json，查看某次图文帖生成结果的完整参数"
            "（title / body / hashtags / images / post_type / traffic_ttl_hours）。"
            "用于在 generate_image_text_post 之后、enqueue_publish 之前，让 agent 检查内容是否合适、"
            "或回看历史生成结果。也会返回 frames/*_composed.png 的张数与路径。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "output/ 下的 task_id 子目录名"},
            },
            "required": ["task_id"],
        },
        handler=_read_post_params,
    ),
    ToolSpec(
        name="force_check_expired_ttl",
        description=(
            "立即触发一次 TTL 到期清理（无需等待后台 15 分钟轮询）。"
            "扫描所有 status=success 且 delete_after_hours 已过期的引流帖，"
            "通过 uiautomator2 自动删除并把状态置为 'deleted'。"
            "返回 newly_deleted（本次新删除数）与 deleted_total（队列里 deleted 总数）。"
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_force_check_expired_ttl,
    ),
    ToolSpec(
        name="ttl_watcher_status",
        description=(
            "查看后台 TTL 自动清理线程是否在运行，以及它的轮询间隔（分钟）。"
            "如果 running=false，可能 web/app.py 还没启动，或在 FastAPI 进程里 TTL 是由 APScheduler 负责。"
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_ttl_watcher_status,
    ),
    ToolSpec(
        name="list_banned_keywords",
        description=(
            "读取当前小红书违禁词列表与过滤模式（mask/remove）。"
            "返回 count / mode / mask / updated_at / keywords。"
            "用户提到「敏感词」「违禁词」「不要出现 XX」时优先调用此工具确认现状。"
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_list_banned_keywords,
    ),
    ToolSpec(
        name="add_banned_keywords",
        description=(
            "向小红书违禁词列表里追加或整体替换关键词。"
            "mode='append'（默认）将与现有列表合并去重；mode='replace' 用本次提交的列表整体覆盖。"
            "对所有后续 LLM 生成（标题/正文/旁白）和发布入队（add_job）都立即生效。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要加入的关键词列表，建议直接给中文词，大小写不敏感",
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "replace"],
                    "default": "append",
                    "description": "append=合并去重；replace=整体替换",
                },
            },
            "required": ["keywords"],
        },
        handler=_add_banned_keywords,
    ),
    ToolSpec(
        name="preview_banned_filter",
        description=(
            "用当前违禁词列表预演一段文本会被怎么清洗。"
            "返回 original / cleaned / hits / hit_count。"
            "不修改任何数据。常用于回答「我这段会被屏蔽吗」「会命中哪些词」。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待预演的文本（标题+正文均可）"},
            },
            "required": ["text"],
        },
        handler=_preview_banned_filter,
    ),
    ToolSpec(
        name="query_publish_knowledge",
        description=(
            "在小红书发布问题知识库里搜索已知故障和解决方案。"
            "当发布任务失败或遇到错误时，**优先调用此工具**，看是否有已知解法可直接参考。"
            "query 填入错误关键词或问题描述，返回匹配的问题条目（含根因和解决步骤）。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "错误信息或问题描述关键词，如 'AttributeError _select_image_text_mode'",
                },
                "top_k": {"type": "integer", "description": "最多返回条数", "default": 3},
            },
            "required": ["query"],
        },
        handler=_query_publish_knowledge,
    ),
    ToolSpec(
        name="record_publish_finding",
        description=(
            "向知识库手动新增或更新一条发布问题记录（含根因和解决方案）。"
            "适合 Agent 在调试成功后把修复经验固化进去，方便以后自动检索。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "problem": {"type": "string", "description": "一句话描述问题（≤30字）"},
                "root_cause": {"type": "string", "description": "根本原因（2-3句）"},
                "solution": {"type": "string", "description": "解决方案（1-2句）"},
                "resolution_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "具体修复步骤列表",
                },
                "job_kind": {
                    "type": "string",
                    "enum": ["video", "image_text", ""],
                    "description": "适用的发布类型",
                    "default": "",
                },
                "error_pattern": {
                    "type": "string",
                    "description": "逗号分隔的匹配关键词，用于未来检索",
                },
                "resolved": {
                    "type": "boolean",
                    "description": "true=解决方案已验证可用",
                    "default": True,
                },
            },
            "required": ["problem", "root_cause", "solution"],
        },
        handler=_record_publish_finding,
    ),
]


def get_tool(name: str) -> Optional[ToolSpec]:
    return next((t for t in TOOLS if t.name == name), None)


def tools_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest shown to the LLM."""
    return [
        {"name": t.name, "description": t.description, "args_schema": t.args_schema}
        for t in TOOLS
    ]
