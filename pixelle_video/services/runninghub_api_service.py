"""
RunningHub Standard Model API Service (Open API v2)

文档：https://www.runninghub.cn/  (API 中心)

端点：``https://www.runninghub.cn/openapi/v2/<rh_endpoint>``
认证：``Authorization: Bearer <API_KEY>`` （API Key **不要**放入 body）
异步：返回 ``taskId`` → 需轮询 ``POST /openapi/v2/query`` 直到 ``status == SUCCESS``。
上传：``POST /openapi/v2/media/upload/binary``，multipart ``file=@...``，返回 ``data.download_url``。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from pixelle_video.config import config_manager

_BASE_URL = "https://www.runninghub.cn/openapi/v2"


class RunningHubAPIError(Exception):
    """Raised when RunningHub API returns a non-success response."""

    def __init__(self, code, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"RunningHub API error {code}: {msg}")


class RunningHubAPIService:
    """OpenAPI v2 wrapper for RunningHub Standard Model endpoints."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or config_manager.config.comfyui.runninghub_api_key
        if not key:
            raise ValueError(
                "RunningHub API Key not configured. "
                "Set comfyui.runninghub_api_key in config.yaml."
            )
        self._api_key = key
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self._masked_key = f"{key[:8]}...{key[-8:]}" if len(key) > 16 else "***"

    # ==================================================================
    # 公开 API
    # ==================================================================

    async def call_model(self, endpoint: str, params: dict, timeout: int = 600) -> str:
        """通用调用：提交任务并轮询直到完成，返回首个产物 URL。

        Args:
            endpoint: ``/rhart-video-g/text-to-video`` 等 registry endpoint。
            params:   不需要也不要包含 ``apiKey``，鉴权走 Bearer 头。
            timeout:  最长等待秒数。

        Returns:
            ``results[0].url`` 文件直链（链接 24h 内有效）。
        """
        from pixelle_video.services import runninghub_registry as reg

        ep_norm = "/" + endpoint.lstrip("/")
        model = reg.get_model_by_endpoint(ep_norm)
        if not model:
            raise RunningHubAPIError(
                code=-1,
                msg=f"未在 registry 中找到 endpoint={ep_norm}",
            )

        # registry.build_payload 会注入 apiKey，这里剥掉（v2 用 header 鉴权）
        payload = reg.build_payload(model, params, self._api_key)
        payload.pop("apiKey", None)

        submit = await self._submit(ep_norm, payload)
        task_id = submit.get("taskId")
        if not task_id:
            raise RunningHubAPIError(
                code=-1, msg=f"提交响应缺少 taskId: {submit}"
            )
        logger.info(f"[RunningHub] task submitted: {task_id} | endpoint={ep_norm}")
        return await self._wait_for_completion(task_id, timeout)

    async def probe_activation(self, endpoint: str) -> dict:
        """探测 endpoint 是否可用（轻量调用，**不消耗**任务额度）。

        策略：发送空 body。若 API Key 无权访问该模型，会返回 401/403 或带有
        权限错误码的 200 应答；若有权访问但缺参数，会返回 ``errorCode`` 表示
        参数错误（这就视为「可用」）。

        Returns:
            ``{"activated": bool|None, "code": int|str, "msg": str, "endpoint": ep}``
        """
        ep_norm = "/" + endpoint.lstrip("/")
        url = f"{_BASE_URL}{ep_norm}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json={}, headers=self._headers)
            status_code = resp.status_code
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:200]}

            err_code = data.get("errorCode") or data.get("code")
            err_msg = (data.get("errorMessage") or data.get("msg") or "")[:120]

            if status_code in (401, 403):
                return {
                    "activated": False, "code": status_code,
                    "msg": f"HTTP {status_code} {err_msg}", "endpoint": ep_norm,
                }
            auth_codes = {"401", "403", "412", 401, 403, 412}
            if err_code and err_code in auth_codes:
                return {
                    "activated": False, "code": err_code,
                    "msg": err_msg or "未开通", "endpoint": ep_norm,
                }
            return {
                "activated": True, "code": err_code or 0,
                "msg": err_msg or "可用", "endpoint": ep_norm,
            }
        except Exception as e:
            return {"activated": None, "code": -1, "msg": f"网络错误: {e}", "endpoint": ep_norm}

    async def upload_image(self, local_path: str) -> str:
        """上传本地文件，返回 ``download_url``（可直接传给模型的 image/video 参数）。"""
        path = Path(local_path)
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        }.get(path.suffix.lower(), "application/octet-stream")

        upload_url = f"{_BASE_URL}/media/upload/binary"
        logger.info(f"[RunningHub] uploading {path.name} ({mime})")
        async with httpx.AsyncClient(timeout=180) as client:
            with open(local_path, "rb") as f:
                resp = await client.post(
                    upload_url,
                    files={"file": (path.name, f, mime)},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code")
        if code not in (0, 200, None):
            raise RunningHubAPIError(code=code, msg=data.get("message", "Upload failed"))
        download_url = (data.get("data") or {}).get("download_url")
        if not download_url:
            raise RunningHubAPIError(code=-1, msg=f"upload response missing download_url: {data}")
        logger.info(f"[RunningHub] upload OK → {download_url}")
        return download_url

    # ==================================================================
    # 向后兼容：原 image_to_video / text_to_video 入口
    # ==================================================================

    async def image_to_video_and_wait(
        self,
        prompt: str,
        image_urls: list[str],
        aspect_ratio: str = "2:3",
        duration: int = 6,
        resolution: str = "480p",
        timeout: int = 600,
    ) -> str:
        """向后兼容：委托给 call_model。"""
        return await self.call_model(
            "/rhart-video-g/image-to-video",
            {
                "prompt": prompt,
                "imageUrls": image_urls,
                "aspectRatio": aspect_ratio,
                "duration": duration,
                "resolution": resolution,
            },
            timeout=timeout,
        )

    async def text_to_video_and_wait(
        self,
        prompt: str,
        aspect_ratio: str = "9:16",
        duration: int = 8,
        resolution: str = "720p",
        timeout: int = 600,
    ) -> str:
        """向后兼容：委托给 call_model。"""
        return await self.call_model(
            "/rhart-video-v3.1-fast/text-to-video",
            {
                "prompt": prompt,
                "aspectRatio": aspect_ratio,
                "duration": str(duration),
                "resolution": resolution,
            },
            timeout=timeout,
        )

    # ==================================================================
    # 内部
    # ==================================================================

    async def _submit(self, endpoint: str, payload: dict) -> dict:
        url = f"{_BASE_URL}{endpoint}"
        logger.debug(f"[RunningHub] POST {url} | body keys={list(payload.keys())}")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=self._headers)
        if resp.status_code in (401, 403):
            raise RunningHubAPIError(
                code=resp.status_code,
                msg=f"鉴权失败 / 未开通：HTTP {resp.status_code}。请到 "
                    f"https://www.runninghub.cn/call-api/search-api/standard-model "
                    f"点击「立即接入」开通该模型，并核对 API Key。",
            )
        try:
            data = resp.json()
        except Exception:
            raise RunningHubAPIError(code=resp.status_code, msg=f"非 JSON 响应: {resp.text[:200]}")

        err_code = data.get("errorCode")
        err_msg = data.get("errorMessage") or ""
        if err_code not in (None, "", 0, "0"):
            raise RunningHubAPIError(code=err_code, msg=err_msg or "submit failed")
        return data

    async def _query(self, task_id: str) -> dict:
        url = f"{_BASE_URL}/query"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json={"taskId": task_id}, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def _wait_for_completion(self, task_id: str, timeout: int = 600) -> str:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        poll_interval = 5

        while True:
            if loop.time() >= deadline:
                raise RunningHubAPIError(code=-1, msg=f"任务 {task_id} 超过 {timeout}s 未完成")
            await asyncio.sleep(poll_interval)
            data = await self._query(task_id)
            status = (data.get("status") or "").upper()
            elapsed = timeout - (deadline - loop.time())
            logger.info(f"[RunningHub] task={task_id} status={status} ({elapsed:.0f}s)")

            if status == "SUCCESS":
                results = data.get("results") or []
                if not results:
                    raise RunningHubAPIError(code=-1, msg=f"task {task_id} success but empty results")
                url = results[0].get("url")
                if not url:
                    raise RunningHubAPIError(code=-1, msg=f"task {task_id} result missing url: {results[0]}")
                logger.success(f"[RunningHub] task done → {url}")
                return url
            if status in ("FAILED", "CANCELLED"):
                raise RunningHubAPIError(
                    code=-1,
                    msg=f"任务失败 status={status} errorCode={data.get('errorCode')} "
                        f"errorMessage={data.get('errorMessage')}",
                )
