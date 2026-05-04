# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Post generation endpoints.
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from loguru import logger

from api.dependencies import PixelleVideoDep
from api.schemas.post import PostGenerateRequest, PostGenerateAsyncResponse, PostTaskResponse
from api.tasks import task_manager, TaskType
from api.tasks.models import TaskStatus
from pixelle_video.pipelines.image_text_post import ImageTextPostPipeline

router = APIRouter(prefix="/post", tags=["Post Generation"])


def path_to_url(request: Request, file_path: str) -> str:
    """Convert output file path to API files URL."""
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")

    if "output" in parts:
        output_idx = parts.index("output")
        rel = "/".join(parts[output_idx + 1:])
    else:
        rel = Path(normalized).name

    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api/files/{rel}"


@router.post("/generate", response_model=PostGenerateAsyncResponse)
async def generate_post_async(
    request_body: PostGenerateRequest,
    pixelle_video: PixelleVideoDep,
    request: Request,
):
    """Create async image-text post generation task."""
    try:
        task = task_manager.create_task(
            task_type=TaskType.POST_GENERATION,
            request_params=request_body.model_dump(),
        )

        async def execute_post_generation():
            pipeline = ImageTextPostPipeline(pixelle_video)
            result = await pipeline(
                topic=request_body.topic,
                image_count=request_body.image_count,
                style=request_body.style or "",
                template_size=request_body.template_size,
                post_tone=request_body.post_tone,
                hashtag_count=request_body.hashtag_count,
            )

            preview_path = str(result.output_dir / "post_preview.html")
            post_json_path = str(result.output_dir / "post.json")

            return {
                "task_id": result.task_id,
                "title": result.content.title,
                "output_dir": str(result.output_dir),
                "image_count": len(result.content.frames),
                "post_json_path": post_json_path,
                "preview_path": preview_path,
                "preview_url": path_to_url(request, preview_path),
            }

        await task_manager.execute_task(
            task_id=task.task_id,
            coro_func=execute_post_generation,
        )

        return PostGenerateAsyncResponse(task_id=task.task_id)
    except Exception as e:
        logger.error(f"Post generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=PostTaskResponse)
async def get_post_task(task_id: str, request: Request):
    """Get post generation task details."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    result = task.result
    if isinstance(result, dict) and result.get("preview_path"):
        result["preview_url"] = path_to_url(request, result["preview_path"])

    return PostTaskResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress.model_dump() if task.progress else None,
        error=task.error,
        result=result,
    )


@router.get("/{task_id}/preview")
async def get_post_preview(task_id: str):
    """Return generated post preview HTML."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Task {task_id} is not completed")

    if not isinstance(task.result, dict) or not task.result.get("preview_path"):
        raise HTTPException(status_code=404, detail="Preview file not found")

    preview_path = Path(task.result["preview_path"])
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Preview file missing on disk")

    return FileResponse(str(preview_path), media_type="text/html")
