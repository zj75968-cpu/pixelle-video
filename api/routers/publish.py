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
Publish queue management endpoints.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from loguru import logger
import os
import shutil
import zipfile
import io
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from api.schemas.publish import (
    PublishJobRequest,
    PublishJobResponse,
    PublishJobListResponse,
    PublishBatchCreateResponse,
)
from pixelle_video.services.publish_scheduler import publish_scheduler, JobStatus

router = APIRouter(prefix="/publish", tags=["Publish Queue"])


# In-memory dictionary tracking active agents
# Format: {agent_id: {"ip": str, "serials": list[str], "last_seen": str}}
ACTIVE_AGENTS: Dict[str, Dict[str, Any]] = {}


def to_relative_path(p: str) -> str:
    """Helper to convert absolute path to relative path from project root."""
    if not p:
        return p
    try:
        path_obj = Path(p)
        if path_obj.is_absolute():
            cwd = Path.cwd()
            if path_obj.is_relative_to(cwd):
                return str(path_obj.relative_to(cwd)).replace("\\", "/")
        return str(path_obj).replace("\\", "/")
    except Exception:
        return p


def _job_to_response(job) -> PublishJobResponse:
    return PublishJobResponse(
        job_id=job.job_id,
        serial=job.serial,
        task_id=job.task_id,
        title=job.title,
        status=job.status,
        scheduled_at=job.scheduled_at,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        delete_after_hours=getattr(job, "delete_after_hours", None),
        auto_comment_text=getattr(job, "auto_comment_text", None),
    )


@router.get("/jobs", response_model=PublishJobListResponse)
async def list_jobs(status: str = None):
    """List publish jobs, optionally filtered by status."""
    jobs = publish_scheduler.list_jobs(status_filter=status)
    return PublishJobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=len(jobs),
    )


@router.post("/jobs", response_model=PublishBatchCreateResponse, status_code=201)
async def create_job(body: PublishJobRequest):
    """
    Queue a post for publishing to a device.

    Set `scheduled_at` to an ISO-8601 datetime for scheduled publishing,
    or leave it null to publish immediately.
    """
    target_serials = []
    if body.serials:
        target_serials.extend([s for s in body.serials if s])
    if body.serial:
        target_serials.append(body.serial)

    # Keep order while removing duplicates.
    target_serials = list(dict.fromkeys(target_serials))
    if not target_serials:
        raise HTTPException(status_code=400, detail="serial or serials must be provided")

    created = []
    failed = []
    for serial in target_serials:
        try:
            job = publish_scheduler.add_job(
                serial=serial,
                task_id=body.task_id,
                title=body.title,
                body=body.body,
                hashtags=body.hashtags,
                images=body.images,
                scheduled_at=body.scheduled_at,
                delete_after_hours=body.delete_after_hours,
                auto_comment_text=body.auto_comment_text,
            )
            created.append(_job_to_response(job))
        except Exception as e:
            failed.append(f"{serial}: {e}")
            logger.error(f"Failed creating publish job for {serial}: {e}")

    return PublishBatchCreateResponse(
        created=created,
        created_count=len(created),
        failed=failed,
    )


@router.get("/jobs/{job_id}", response_model=PublishJobResponse)
async def get_job(job_id: str):
    """Get status and details of a specific publish job."""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_to_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=PublishJobResponse)
async def cancel_job(job_id: str):
    """Cancel a pending, scheduled, or running publish job."""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    cancelled = publish_scheduler.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} cannot be cancelled (status: {job.status})",
        )
    return _job_to_response(publish_scheduler.get_job(job_id))


@router.post("/jobs/{job_id}/run-now", response_model=PublishJobResponse)
async def run_job_now(job_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a pending job to run immediately."""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not in a runnable state (status: {job.status})",
        )
    background_tasks.add_task(publish_scheduler.execute_now, job_id)
    job.status = JobStatus.RUNNING
    return _job_to_response(job)


@router.get("/agent/pending")
async def get_pending_job_for_agent(serials: str, request: Request, agent_id: str = None):
    """
    Poll for pending/running jobs matching client connected device serials.
    Also registers or updates the client agent's online status.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not agent_id:
        agent_id = client_ip
    
    serial_list = [s.strip() for s in serials.split(",") if s.strip()]
    
    # Update active agent registration
    ACTIVE_AGENTS[agent_id] = {
        "ip": client_ip,
        "serials": serial_list,
        "last_seen": datetime.now().isoformat()
    }
    
    # Clean up old agents (older than 30s) while we are here
    now = datetime.now()
    stale_keys = [k for k, v in ACTIVE_AGENTS.items() if (now - datetime.fromisoformat(v["last_seen"])).total_seconds() > 30]
    for k in stale_keys:
        ACTIVE_AGENTS.pop(k, None)
        
    # Search the queue for a RUNNING job matching these serials
    token = request.headers.get("X-Token", "")
    from pixelle_video.utils.user_context import find_username_by_token, set_current_user
    username = find_username_by_token(token)
    
    with set_current_user(username):
        running_jobs = publish_scheduler.list_jobs(status_filter=JobStatus.RUNNING)
    for job in running_jobs:
        if job.serial in serial_list:
            # We found a job for this agent!
            # Format and return job details
            return {
                "job": {
                    "job_id": job.job_id,
                    "serial": job.serial,
                    "kind": job.kind,
                    "title": job.title,
                    "body": job.body,
                    "hashtags": job.hashtags,
                    "images": [to_relative_path(img) for img in job.images],
                    "video_path": to_relative_path(job.video_path) if job.video_path else None,
                    "dry_run": job.dry_run,
                }
            }
            
    return {"job": None}


@router.get("/agent/list")
async def list_active_agents():
    """List currently online agents."""
    now = datetime.now()
    stale_keys = [k for k, v in ACTIVE_AGENTS.items() if (now - datetime.fromisoformat(v["last_seen"])).total_seconds() > 30]
    for k in stale_keys:
        ACTIVE_AGENTS.pop(k, None)
    return {"agents": list(ACTIVE_AGENTS.values())}


@router.get("/agent/download-client")
async def download_client_agent():
    """Package and download the minimal client agent files as a ZIP."""
    memory_file = io.BytesIO()
    try:
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            files_to_zip = [
                ("scripts/local_agent.py", "scripts/local_agent.py"),
                ("pixelle_video/__init__.py", "pixelle_video/__init__.py"),
                ("pixelle_video/config/schema.py", "pixelle_video/config/schema.py"),
                ("pixelle_video/services/__init__.py", "pixelle_video/services/__init__.py"),
                ("pixelle_video/services/xhs_publisher.py", "pixelle_video/services/xhs_publisher.py"),
                ("config/xhs_ui_selectors.yaml", "config/xhs_ui_selectors.yaml"),
                ("packaging/windows/platform-tools/adb.exe", "packaging/windows/platform-tools/adb.exe"),
                ("packaging/windows/platform-tools/AdbWinApi.dll", "packaging/windows/platform-tools/AdbWinApi.dll"),
                ("packaging/windows/platform-tools/AdbWinUsbApi.dll", "packaging/windows/platform-tools/AdbWinUsbApi.dll"),
            ]
            for src, arcname in files_to_zip:
                if arcname == "pixelle_video/__init__.py":
                    # Avoid importing server modules like comfykit on the client agent side
                    zipf.writestr(arcname, "__version__ = '0.1.0'\n__all__ = []\n")
                elif os.path.exists(src):
                    zipf.write(src, arcname)
                else:
                    logger.warning(f"Zip packager: source file {src} not found")
        memory_file.seek(0)
        return StreamingResponse(
            memory_file,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=pixelle_agent.zip"}
        )
    except Exception as e:
        logger.error(f"Failed to generate client agent zip: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate agent zip: {e}")


@router.post("/agent/jobs/{job_id}/progress")
async def update_agent_job_progress(job_id: str, payload: dict):
    """Post progress update from client agent."""
    job = publish_scheduler._jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    from pixelle_video.utils.user_context import set_current_user
    with set_current_user(getattr(job, "username", "default")):
        log_msg = payload.get("log", "")
        if log_msg:
            ts = datetime.now().strftime("%H:%M:%S")
            job.progress_log.append(f"[{ts}] {log_msg}")
            publish_scheduler._save()
            logger.info(f"[Agent][{job_id}] {log_msg}")
            
        return {"status": "ok"}


@router.post("/agent/jobs/{job_id}/result")
async def submit_agent_job_result(
    job_id: str,
    status: str = Form(...),
    error: str = Form(None),
    screenshot: UploadFile = File(None)
):
    """Submit execution result (success/failure) from client agent, with optional screenshot."""
    job = publish_scheduler._jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    from pixelle_video.utils.user_context import set_current_user
    with set_current_user(getattr(job, "username", "default")):
        logger.info(f"Received agent result for job {job_id}: status={status}, error={error}")
        
        # Save uploaded screenshot if present
        if screenshot:
            try:
                dest_dir = Path("runtime/mobile_results") / job.serial / job_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                
                ext = Path(screenshot.filename).suffix.lower() if screenshot.filename else ".png"
                if ext not in (".png", ".jpg", ".jpeg"):
                    ext = ".png"
                dest_path = dest_dir / f"screenshot{ext}"
                
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(screenshot.file, f)
                    
                job.screenshots = [str(dest_path).replace("\\", "/")]
                logger.info(f"Saved agent screenshot to {dest_path}")
            except Exception as e:
                logger.error(f"Failed to save agent screenshot: {e}")
                
        # Update job state
        if status == "success":
            if job.kind == "delete":
                job.status = "deleted"
            elif job.kind == "comment":
                job.status = "comment_success"
            else:
                job.status = JobStatus.SUCCESS
            job.error = None
        else:
            job.status = JobStatus.FAILED
            job.error = error or "Agent reported execution failure"
            
        job.finished_at = datetime.now().isoformat()
        publish_scheduler._save()
        
        return {"status": "ok"}
