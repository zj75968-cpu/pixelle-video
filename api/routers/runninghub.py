"""
RunningHub Model API endpoints

Exposes RunningHub's direct REST API (not ComfyKit workflow mode).
These endpoints call RunningHub cloud servers and require a valid API Key
with appropriate permissions configured in config.yaml.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.schemas.runninghub import (
    RunningHubI2VRequest,
    RunningHubT2VRequest,
    RunningHubVideoResponse,
)
from pixelle_video.services.runninghub_api_service import (
    RunningHubAPIService,
    RunningHubAPIError,
)

router = APIRouter(prefix="/runninghub", tags=["RunningHub Cloud API"])


@router.post(
    "/image-to-video",
    response_model=RunningHubVideoResponse,
    summary="图生视频 (全能视频X-低价渠道版)",
    description=(
        "Call RunningHub **全能视频X-图生视频-低价渠道版** API.\n\n"
        "Provide one or more reference image URLs and a motion description; "
        "RunningHub will generate a video in the cloud.\n\n"
        "Requires a valid `runninghub_api_key` in `config.yaml`."
    ),
)
async def image_to_video(request: RunningHubI2VRequest) -> RunningHubVideoResponse:
    try:
        svc = RunningHubAPIService()
        data = await svc.image_to_video_and_wait(
            prompt=request.prompt,
            image_urls=request.image_urls,
            aspect_ratio=request.aspect_ratio,
            duration=request.duration,
            resolution=request.resolution,
        )
        return RunningHubVideoResponse(
            success=True,
            message="Video generation request submitted successfully.",
            data=data,
        )
    except ValueError as e:
        # API key not configured
        raise HTTPException(status_code=400, detail=str(e))
    except RunningHubAPIError as e:
        detail = str(e)
        if e.code == 412:
            detail = (
                f"RunningHub TOKEN_INVALID (code 412): The configured API Key is invalid "
                f"or lacks permission for video generation endpoints. "
                f"Please verify your key at https://www.runninghub.cn and check "
                f"whether your account requires enterprise-level access."
            )
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        logger.error(f"[RunningHub] image_to_video unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/text-to-video",
    response_model=RunningHubVideoResponse,
    summary="文生视频 (全能视频V3.1-fast-低价渠道版)",
    description=(
        "Call RunningHub **全能视频V3.1-fast-文生视频-低价渠道版** API.\n\n"
        "Provide a scene description; RunningHub will generate a video in the cloud.\n\n"
        "Requires a valid `runninghub_api_key` in `config.yaml`."
    ),
)
async def text_to_video(request: RunningHubT2VRequest) -> RunningHubVideoResponse:
    try:
        svc = RunningHubAPIService()
        data = await svc.text_to_video_and_wait(
            prompt=request.prompt,
            aspect_ratio=request.aspect_ratio,
            duration=request.duration,
            resolution=request.resolution,
        )
        return RunningHubVideoResponse(
            success=True,
            message="Video generation request submitted successfully.",
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RunningHubAPIError as e:
        detail = str(e)
        if e.code == 412:
            detail = (
                f"RunningHub TOKEN_INVALID (code 412): The configured API Key is invalid "
                f"or lacks permission for video generation endpoints. "
                f"Please verify your key at https://www.runninghub.cn and check "
                f"whether your account requires enterprise-level access."
            )
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        logger.error(f"[RunningHub] text_to_video unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
