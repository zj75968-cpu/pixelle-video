"""
RunningHub Model API Service

Directly calls RunningHub's REST API endpoints (not ComfyKit workflow mode).
Supports:
  - image_to_video: 全能视频X-图生视频-低价渠道版 (rhart-video-g/image-to-video)
  - text_to_video:  全能视频V3.1-fast-文生视频   (rhart-video-v3.1-fast/text-to-video)
"""

import asyncio
from typing import Optional
import httpx
from loguru import logger

from pixelle_video.config import config_manager

# RunningHub Model API base URL
_BASE_URL = "https://www.runninghub.cn/api/v1"
# Task status/output polling base URL
_TASK_BASE_URL = "https://www.runninghub.cn"


class RunningHubAPIError(Exception):
    """Raised when RunningHub API returns a non-success response."""

    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"RunningHub API error {code}: {msg}")


class RunningHubAPIService:
    """
    Thin wrapper around RunningHub Model API endpoints.

    All methods are async. They raise ``RunningHubAPIError`` on API-level
    failures and let lower-level ``httpx`` exceptions propagate as-is for
    network-level failures.
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or config_manager.config.comfyui.runninghub_api_key
        if not key:
            raise ValueError(
                "RunningHub API Key not configured. "
                "Set comfyui.runninghub_api_key in config.yaml."
            )
        self._api_key = key
        # Authorization header + body apiKey are BOTH required per RunningHub docs
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        # Mask key in logs
        self._masked_key = f"{key[:8]}...{key[-8:]}" if len(key) > 16 else "***"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call_model(
        self,
        endpoint: str,
        params: dict,
        timeout: int = 600,
    ) -> str:
        """
        通用调用：根据 registry 中的 endpoint 直接发请求并轮询直到完成。

        Args:
            endpoint: 形如 ``/rhart-video-g/text-to-video`` 的相对路径（带或不带前导 ``/`` 都可）。
            params:   用户参数（无需包含 ``apiKey``，会自动注入；类型由 registry 校正）。
            timeout:  最大等待秒数。

        Returns:
            视频/图片文件 URL。
        """
        from pixelle_video.services import runninghub_registry as reg

        ep_norm = "/" + endpoint.lstrip("/")
        model = reg.get_model_by_endpoint(ep_norm)
        if not model:
            raise RunningHubAPIError(
                code=-1,
                msg=f"未在 registry 中找到 endpoint={ep_norm}，请检查 runninghub_lowprice_registry.json",
            )

        payload = reg.build_payload(model, params, self._api_key)
        url = f"{_BASE_URL}{ep_norm}"
        logger.info(
            f"[RunningHub] call_model | key={self._masked_key} | "
            f"endpoint={ep_norm} | inputs={list(payload.keys())}"
        )
        resp = await self._post(url, payload)
        return await self._wait_for_completion(resp, timeout)

    async def probe_activation(self, endpoint: str) -> dict:
        """
        探测当前 API Key 是否已开通该 endpoint 对应的标准模型。

        策略：只发送 ``{apiKey}`` 的极简载荷。
            - 服务端先校验 token：未开通 → 返回 code=412 TOKEN_INVALID。
            - 已开通：会因缺少必填参数返回其它 4xx（通常 code != 412）。
            - 因此 412 → False，其它一切（含网络错误）→ True/Unknown。

        Returns:
            ``{"activated": bool, "code": int, "msg": str, "endpoint": str}``
        """
        ep_norm = "/" + endpoint.lstrip("/")
        url = f"{_BASE_URL}{ep_norm}"
        payload = {"apiKey": self._api_key}
        try:
            await self._post(url, payload)
            # code == 0 / 200 表示已开通且任务已创建（极少发生，因为 prompt 等必填缺失）
            return {"activated": True, "code": 0, "msg": "OK", "endpoint": ep_norm}
        except RunningHubAPIError as e:
            if e.code == 412:
                return {"activated": False, "code": 412, "msg": "TOKEN_INVALID（未开通）", "endpoint": ep_norm}
            return {"activated": True, "code": e.code, "msg": f"已开通（缺参数: {e.msg[:60]}）", "endpoint": ep_norm}
        except Exception as e:
            return {"activated": None, "code": -1, "msg": f"网络错误: {e}", "endpoint": ep_norm}

    async def image_to_video(
        self,
        prompt: str,
        image_urls: list[str],
        aspect_ratio: str = "2:3",
        duration: int = 6,
        resolution: str = "480p",
    ) -> dict:
        """
        全能视频X-图生视频-低价渠道版

        Args:
            prompt:       Motion/scene description
            image_urls:   List of reference image URLs (1-7 items)
            aspect_ratio: e.g. "2:3", "16:9", "9:16", "1:1"
            duration:     Video length in seconds
            resolution:   "480p" | "720p" | "1080p"

        Returns:
            Raw JSON dict from RunningHub (contains task_id, status, video_url, …)
        """
        endpoint = f"{_BASE_URL}/rhart-video-g/image-to-video"

        payload = {
            "apiKey": self._api_key,
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "imageUrls": image_urls,
            "duration": duration,
            "resolution": resolution,
        }

        logger.info(
            f"[RunningHub] image_to_video | key={self._masked_key} | "
            f"aspect={aspect_ratio} duration={duration}s resolution={resolution} "
            f"images={len(image_urls)}"
        )
        return await self._post(endpoint, payload)

    async def image_to_video_and_wait(
        self,
        prompt: str,
        image_urls: list[str],
        aspect_ratio: str = "2:3",
        duration: int = 6,
        resolution: str = "480p",
        timeout: int = 600,
    ) -> str:
        """提交图生视频并等待完成，返回视频文件 URL。"""
        resp = await self.image_to_video(prompt, image_urls, aspect_ratio, duration, resolution)
        return await self._wait_for_completion(resp, timeout)

    async def upload_image(self, local_path: str) -> str:
        """
        Upload a local image to RunningHub cloud storage.

        Returns the remote filename (hash-based) which can be used as the
        ``image`` field value in a ComfyKit ``LoadImage`` node.
        """
        from pathlib import Path as _Path

        upload_url = f"{_TASK_BASE_URL}/task/openapi/upload"
        path = _Path(local_path)
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        }.get(path.suffix.lower(), "image/jpeg")

        logger.info(f"[RunningHub] Uploading image to cloud: {path.name}")
        async with httpx.AsyncClient(timeout=60) as client:
            with open(local_path, "rb") as f:
                resp = await client.post(
                    upload_url,
                    files={"file": (path.name, f, mime)},
                    data={"apiKey": self._api_key},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        resp.raise_for_status()
        result = resp.json()

        code = result.get("code")
        if code not in (200, 0, None):
            raise RunningHubAPIError(code=code, msg=result.get("msg", "Upload failed"))

        data = result.get("data") or {}
        filename = data.get("fileName") or data.get("filename") or data.get("name")
        if not filename:
            raise RunningHubAPIError(code=-1, msg=f"Upload response has no fileName: {result}")

        logger.info(f"[RunningHub] Image uploaded → {filename}")
        return filename

    async def text_to_video(
        self,
        prompt: str,
        aspect_ratio: str = "9:16",
        duration: int = 8,
        resolution: str = "720p",
    ) -> dict:
        """
        全能视频V3.1-fast-文生视频-低价渠道版

        Args:
            prompt:       Scene description
            aspect_ratio: e.g. "9:16", "16:9", "1:1"
            duration:     Video length in seconds (4-15)
            resolution:   "720p" | "1080p"

        Returns:
            Raw JSON dict from RunningHub
        """
        endpoint = f"{_BASE_URL}/rhart-video-v3.1-fast/text-to-video"

        payload = {
            "apiKey": self._api_key,
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
        }

        logger.info(
            f"[RunningHub] text_to_video | key={self._masked_key} | "
            f"aspect={aspect_ratio} duration={duration}s resolution={resolution}"
        )
        return await self._post(endpoint, payload)

    async def text_to_video_and_wait(
        self,
        prompt: str,
        aspect_ratio: str = "9:16",
        duration: int = 8,
        resolution: str = "720p",
        timeout: int = 600,
    ) -> str:
        """提交文生视频并等待完成，返回视频文件 URL。"""
        resp = await self.text_to_video(prompt, aspect_ratio, duration, resolution)
        return await self._wait_for_completion(resp, timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _wait_for_completion(self, submit_response: dict, timeout: int = 600) -> str:
        """
        等待任务完成并返回文件 URL。

        支持两种响应格式：
        1. 同步响应：data 直接包含 fileUrl（立即返回）
        2. 异步响应：data 包含 taskId，需轮询 /task/openapi/status
        """
        data = submit_response.get("data")

        # 情况 1：同步响应，data 是列表含 fileUrl
        if isinstance(data, list) and data:
            file_url = data[0].get("fileUrl")
            if file_url:
                logger.info(f"[RunningHub] 同步响应，直接获得视频: {file_url}")
                return file_url

        # 情况 2：同步响应，data 是字典含 fileUrl
        if isinstance(data, dict):
            file_url = data.get("fileUrl") or data.get("videoUrl")
            if file_url:
                logger.info(f"[RunningHub] 同步响应，直接获得视频: {file_url}")
                return file_url

        # 情况 3：异步任务，需要 taskId 轮询
        task_id = data.get("taskId") if isinstance(data, dict) else None
        if task_id is None:
            task_id = submit_response.get("taskId")

        if not task_id:
            raise RunningHubAPIError(
                code=-1,
                msg=f"提交响应中没有 taskId 也没有 fileUrl: {submit_response}",
            )

        logger.info(f"[RunningHub] 任务已提交: {task_id}，开始轮询状态...")

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        poll_interval = 5

        while True:
            if loop.time() >= deadline:
                raise RunningHubAPIError(
                    code=-1,
                    msg=f"任务 {task_id} 超时，已等待 {timeout}s",
                )
            await asyncio.sleep(poll_interval)

            status_resp = await self._post(
                f"{_TASK_BASE_URL}/task/openapi/status",
                {"apiKey": self._api_key, "taskId": task_id},
            )
            status = status_resp.get("data", "")
            elapsed = timeout - (deadline - loop.time())
            logger.info(f"[RunningHub] 任务 {task_id} 状态: {status} ({elapsed:.0f}s)")

            if status == "SUCCESS":
                break
            elif status in ("FAILED", "CANCELLED"):
                raise RunningHubAPIError(
                    code=-1,
                    msg=f"任务 {task_id} 失败: {status}",
                )
            # QUEUED / RUNNING → 继续等待

        # 获取输出
        output_resp = await self._post(
            f"{_TASK_BASE_URL}/task/openapi/outputs",
            {"apiKey": self._api_key, "taskId": task_id},
        )
        outputs = output_resp.get("data", [])
        if not outputs:
            raise RunningHubAPIError(code=-1, msg=f"任务 {task_id} 没有输出")

        file_url = outputs[0].get("fileUrl")
        if not file_url:
            raise RunningHubAPIError(code=-1, msg=f"输出中没有 fileUrl: {outputs}")

        logger.info(f"[RunningHub] 任务 {task_id} 完成: {file_url}")
        return file_url

    async def _post(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        code = data.get("code")
        msg = data.get("msg", "")

        # RunningHub wraps errors in HTTP 200 with a non-zero code
        if code is not None and code != 200 and code != 0:
            # 友好处理：412 TOKEN_INVALID = 当前 API Key 未开通该「标准模型」（Standard Model API）
            if code == 412:
                friendly = (
                    f"RunningHub 返回 412 TOKEN_INVALID。\n"
                    f"原因：你的 API Key 没有开通这个「低价渠道/标准模型」产品。\n"
                    f"解决：访问 https://www.runninghub.cn/call-api/search-api/standard-model "
                    f"找到对应模型，点击「立即接入」开通后再试。\n"
                    f"（注意：RunningHub 的 ComfyUI 工作流 API 和 标准模型 API 是两个独立产品，需要分别激活。）\n"
                    f"调用 URL: {url}"
                )
                logger.error(f"[RunningHub] {friendly}")
                raise RunningHubAPIError(code=code, msg=friendly)
            logger.error(
                f"[RunningHub] API error: code={code} msg={msg} url={url}"
            )
            raise RunningHubAPIError(code=code, msg=msg)

        logger.success(f"[RunningHub] Request succeeded: {data}")
        return data
