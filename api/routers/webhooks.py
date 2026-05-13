# Copyright (C) 2025 AIDC-AI
"""
Webhook endpoints used by external callbacks (e.g. RunningHub openapi/v2 webhookUrl).

The `/webhooks/runninghub` endpoint is invoked by RunningHub when a task finishes.
RunningHub posts a JSON body containing at minimum `taskId` and `status` (SUCCESS/FAILED).
We forward the payload to `webhook_registry.resolve(task_id, payload)` which
unblocks the caller that registered to wait for that task.
"""

from fastapi import APIRouter, Request
from loguru import logger

from pixelle_video.services import webhook_registry

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/runninghub",
    summary="RunningHub openapi/v2 task-completion webhook",
)
async def runninghub_webhook(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning(f"[webhook] invalid JSON body: {exc}")
        return {"ok": False, "error": "invalid json"}
    task_id = payload.get("taskId") or (payload.get("data") or {}).get("taskId")
    if not task_id:
        logger.warning(f"[webhook] payload missing taskId: keys={list(payload.keys())}")
        return {"ok": False, "error": "missing taskId"}
    delivered = await webhook_registry.resolve(str(task_id), payload)
    logger.info(
        f"[webhook] runninghub task={task_id} status={payload.get('status')} "
        f"delivered={'yes' if delivered else 'no-waiter'}"
    )
    return {"ok": True, "delivered": delivered}
