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

    job = publish_scheduler.add_job(
        serial=serial,
        task_id=f"agent-{uuid.uuid4().hex[:8]}",
        title=title,
        body=body,
        hashtags=list(hashtags or []),
        images=[video_path],
        scheduled_at=scheduled_at,
    )
    return {
        "job_id": job.job_id,
        "serial": job.serial,
        "status": job.status,
        "scheduled_at": job.scheduled_at,
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
            "若未指定 device_serial，自动选取第一台已连接设备。"
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
            },
            "required": ["video_path", "title"],
        },
        handler=_enqueue_publish,
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
]


def get_tool(name: str) -> Optional[ToolSpec]:
    return next((t for t in TOOLS if t.name == name), None)


def tools_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest shown to the LLM."""
    return [
        {"name": t.name, "description": t.description, "args_schema": t.args_schema}
        for t in TOOLS
    ]
