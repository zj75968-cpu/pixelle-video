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


async def _generate_video(
    topic: str,
    n_scenes: int = 3,
    media_workflow: Optional[str] = None,
    pipeline: str = "standard",
) -> Dict[str, Any]:
    """Generate a video from a natural-language topic."""
    from pixelle_video.service import pixelle_video as core

    if not getattr(core, "_initialized", False):
        await core.initialize()

    kwargs: Dict[str, Any] = {"n_scenes": int(n_scenes), "mode": "generate"}
    if media_workflow:
        kwargs["media_workflow"] = media_workflow

    logger.info(f"[agent] generate_video topic={topic!r} kwargs={kwargs}")
    result = await core.generate_video(text=topic, pipeline=pipeline, **kwargs)

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

    # 图文模式：自动从 frames/*_composed.png 取场景合成图
    from pathlib import Path as _Path
    images_for_job: list = [video_path]
    if kind == "image_text":
        frames_dir = _Path(video_path).parent / "frames"
        composed = sorted(frames_dir.glob("*_composed.png"))
        if composed:
            images_for_job = [str(p) for p in composed]
            logger.info(f"[agent] image_text: {len(images_for_job)} scene images found")
        else:
            logger.warning(f"[agent] image_text: no composed images in {frames_dir}, falling back to video path")

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
    )
    return {
        "job_id": job.job_id,
        "serial": job.serial,
        "status": job.status,
        "scheduled_at": job.scheduled_at,
        "dry_run": job.dry_run,
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
        status = getattr(d, "status", "unknown") or "unknown"
        if only_connected and status != "connected":
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
            "topic 必填；n_scenes 默认 3；media_workflow 可选，用于指定图像/视频生成 workflow。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "视频选题/主题"},
                "n_scenes": {"type": "integer", "description": "镜头数量", "default": 3},
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
]


def get_tool(name: str) -> Optional[ToolSpec]:
    return next((t for t in TOOLS if t.name == name), None)


def tools_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest shown to the LLM."""
    return [
        {"name": t.name, "description": t.description, "args_schema": t.args_schema}
        for t in TOOLS
    ]
