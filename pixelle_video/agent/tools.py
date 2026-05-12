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
            "label": getattr(d, "label", None) or getattr(d, "alias", None) or "",
            "status": getattr(d, "status", "unknown"),
        }
        for d in device_manager.get_all()
    ]
    return {"count": len(devices), "devices": devices}


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
        description="列出当前通过 ADB 连接的安卓设备（含 serial / label / status）。需要选择发布目标设备前先调用。",
        args_schema={"type": "object", "properties": {}, "required": []},
        handler=_list_devices,
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
]


def get_tool(name: str) -> Optional[ToolSpec]:
    return next((t for t in TOOLS if t.name == name), None)


def tools_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest shown to the LLM."""
    return [
        {"name": t.name, "description": t.description, "args_schema": t.args_schema}
        for t in TOOLS
    ]
