# Copyright (C) 2025 AIDC-AI
"""
RunningHub openapi/v2 client.

Implements the second-generation RunningHub API:
  - POST {base}/openapi/v2/run/workflow/{workflow_id}
  - POST {base}/openapi/v2/query           (poll task status & results)
  - POST {base}/openapi/v2/media/upload/binary  (upload local files, returns 24h URL or filename)

Differences from v1 (handled by comfykit.RunningHubClient):
  - Auth: HTTP header "Authorization: Bearer <key>" (vs. body "apiKey" in v1).
  - Endpoints under /openapi/v2/ (vs. /task/openapi/*).
  - Optional webhookUrl support — caller may pass it through.

This module is intentionally minimal and standalone (no comfykit dependency)
to keep the v1 path untouched. See web/pipelines/digital_human.py for the
caller wiring (v2 + consumer key tried first, fallback to v1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import aiohttp
from loguru import logger


DEFAULT_BASE_URL = "https://www.runninghub.cn"
RUN_PATH = "/openapi/v2/run/workflow/{workflow_id}"
QUERY_PATH = "/openapi/v2/query"
UPLOAD_PATH = "/openapi/v2/media/upload/binary"


class RunningHubV2Client:
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        if not api_key:
            raise ValueError("RunningHubV2Client requires non-empty api_key")
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def upload_file(self, file_path: str | Path) -> dict[str, Any]:
        """Upload a local file. Returns the `data` block of the response, which
        typically contains `download_url`, `fileName`, `type`, `size`.

        Note: download_url is valid for ~24h.
        """
        url = f"{self.base_url}{UPLOAD_PATH}"
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Upload source not found: {file_path}")
        timeout = aiohttp.ClientTimeout(total=self.timeout * 5)  # uploads can be slow
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(file_path, "rb") as fh:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    fh,
                    filename=file_path.name,
                    content_type="application/octet-stream",
                )
                headers = {"Authorization": f"Bearer {self.api_key}"}
                async with session.post(url, data=form, headers=headers) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
        if payload.get("code") not in (0, "0"):
            raise RuntimeError(f"RunningHub v2 upload failed: {payload}")
        return payload.get("data") or {}

    async def run_workflow(
        self,
        workflow_id: str,
        *,
        node_info_list: Optional[list[dict[str, Any]]] = None,
        add_metadata: bool = True,
        random_seed: Optional[bool] = None,
        instance_type: str = "default",
        use_personal_queue: bool = False,
        retain_seconds: Optional[int] = None,
        webhook_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Start a workflow execution. Returns parsed JSON of the response.

        On success the response includes `taskId` (and `status` usually = RUNNING).
        """
        url = f"{self.base_url}{RUN_PATH.format(workflow_id=workflow_id)}"
        body: dict[str, Any] = {
            "addMetadata": bool(add_metadata),
            "nodeInfoList": node_info_list or [],
            "instanceType": instance_type or "default",
            "usePersonalQueue": "true" if use_personal_queue else "false",
        }
        if random_seed is not None:
            body["randomSeed"] = bool(random_seed)
        if retain_seconds is not None:
            body["retainSeconds"] = int(retain_seconds)
        if webhook_url:
            body["webhookUrl"] = webhook_url

        logger.info(
            f"[rh-v2] POST {url} nodeInfo={len(body['nodeInfoList'])} "
            f"instance={body['instanceType']}"
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body, headers=self._auth_headers) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def query_task(self, task_id: str) -> dict[str, Any]:
        url = f"{self.base_url}{QUERY_PATH}"
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json={"taskId": task_id}, headers=self._auth_headers
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = 3.0,
        max_wait_seconds: int = 1800,
    ) -> dict[str, Any]:
        """Poll /openapi/v2/query until SUCCESS/FAILED or timeout.

        Returns the full final response JSON (including `results`).
        Raises TimeoutError if it doesn't reach a terminal state in time.
        """
        deadline = asyncio.get_event_loop().time() + max_wait_seconds
        consecutive_errors = 0
        while True:
            try:
                payload = await self.query_task(task_id)
                consecutive_errors = 0
            except Exception as e:
                # RunningHub 偶发 5xx（502/503/504/525 SSL handshake failed）等 Cloudflare 抖动，
                # 不要因为单次查询失败就让整个任务死掉，短暂重试。
                consecutive_errors += 1
                if consecutive_errors >= 6:
                    raise
                logger.warning(
                    f"[rh-v2] query_task {task_id} 失败 ({consecutive_errors}/6): {e!r}，"
                    f"{poll_interval}s 后重试"
                )
                if asyncio.get_event_loop().time() >= deadline:
                    raise
                await asyncio.sleep(poll_interval)
                continue
            status = (payload.get("status") or "").upper()
            if status in ("SUCCESS", "FAILED"):
                return payload
            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(
                    f"RunningHub v2 task {task_id} did not finish in {max_wait_seconds}s "
                    f"(last status={status or 'UNKNOWN'})"
                )
            await asyncio.sleep(poll_interval)

    async def wait_via_webhook(
        self,
        task_id: str,
        *,
        max_wait_seconds: int = 1800,
        fallback_poll: bool = True,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Wait for a task to finish by listening to the webhook callback.

        Requires the FastAPI app to be running and reachable from RunningHub at
        `<public_base_url>/webhooks/runninghub`, AND that `run_workflow(...)`
        was called with `webhook_url=` pointing at that endpoint.

        Behaviour:
          - Registers an asyncio.Future via webhook_registry.
          - Awaits the future with a timeout of `max_wait_seconds`.
          - On timeout: if fallback_poll, falls back to `wait_for_task`; else raises TimeoutError.
        """
        from pixelle_video.services import webhook_registry

        fut = await webhook_registry.register(task_id)
        try:
            payload = await asyncio.wait_for(fut, timeout=max_wait_seconds)
            # Webhook payloads may not include `results`; if not, fetch once via query.
            if "results" not in payload:
                queried = await self.query_task(task_id)
                merged = {**payload, **queried}
                return merged
            return payload
        except asyncio.TimeoutError:
            await webhook_registry.unregister(task_id)
            if fallback_poll:
                return await self.wait_for_task(
                    task_id, poll_interval=poll_interval, max_wait_seconds=30
                )
            raise TimeoutError(
                f"RunningHub v2 task {task_id} webhook did not arrive in {max_wait_seconds}s"
            )
