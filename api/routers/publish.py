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

import asyncio
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
                kind=body.kind,
                video_path=body.video_path,
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

    DEPRECATED: Use /agent/wait for event-driven job assignment (no polling).
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

    # Search the queue for a PENDING or RUNNING job matching these serials
    token = request.headers.get("X-Token", "")
    from pixelle_video.utils.user_context import find_username_by_token, set_current_user
    username = find_username_by_token(token)

    with set_current_user(username):
        pending_jobs = publish_scheduler.list_jobs(status_filter=JobStatus.PENDING)
        running_jobs = publish_scheduler.list_jobs(status_filter=JobStatus.RUNNING)

    # Prioritize PENDING jobs first, then RUNNING
    for job in pending_jobs + running_jobs:
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


@router.get("/agent/wait")
async def wait_for_job_event_driven(serials: str, request: Request, agent_id: str = None, timeout: int = 600):
    """
    Event-driven job waiting for agents. Replaces polling with instant notification.

    This endpoint blocks until a job matching the agent's serials becomes available,
    or until the timeout is reached. This eliminates the need for frequent polling.

    Args:
        serials: Comma-separated list of device serials this agent can handle
        agent_id: Optional unique agent identifier (defaults to client IP)
        timeout: Maximum wait time in seconds (default 600 = 10 minutes)

    Returns:
        Job details if available, or {"status": "timeout"} if no job within timeout
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

    # First check if there's already a pending job
    token = request.headers.get("X-Token", "")
    from pixelle_video.utils.user_context import find_username_by_token, set_current_user
    username = find_username_by_token(token)

    with set_current_user(username):
        pending_jobs = publish_scheduler.list_jobs(status_filter=JobStatus.PENDING)

    # Check for immediate match
    for job in pending_jobs:
        if job.serial in serial_list:
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
                    "auto_comment_text": job.auto_comment_text,
                }
            }

    # No immediate job, wait for one to become available
    # Use a simple polling with longer interval since we don't have per-serial queues yet
    # TODO: Implement per-serial event queues for true zero-latency notification
    start_time = datetime.now()
    check_interval = 5  # Check every 5 seconds instead of 3

    while (datetime.now() - start_time).total_seconds() < timeout:
        await asyncio.sleep(check_interval)

        # Update last seen
        ACTIVE_AGENTS[agent_id]["last_seen"] = datetime.now().isoformat()

        # Check for new jobs
        with set_current_user(username):
            pending_jobs = publish_scheduler.list_jobs(status_filter=JobStatus.PENDING)

        for job in pending_jobs:
            if job.serial in serial_list:
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
                        "auto_comment_text": job.auto_comment_text,
                    }
                }

    # Timeout reached
    return {"status": "timeout"}


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


from fastapi.responses import HTMLResponse, FileResponse

@router.get("/task-image", response_class=FileResponse)
async def get_task_image(job_id: str, idx: int):
    """直接读取任务对应的本地图片并返回"""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not job.images or idx >= len(job.images):
        raise HTTPException(status_code=404, detail="Image index out of range")
        
    img_path = job.images[idx]
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image file not found")
        
    return FileResponse(img_path)

@router.get("/task-video", response_class=FileResponse)
async def get_task_video(job_id: str):
    """直接读取任务对应的本地视频并返回"""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    video_path = job.video_path
    if not video_path:
        raise HTTPException(status_code=404, detail="Video path not set on job")
        
    path_obj = Path(video_path)
    if not path_obj.is_absolute():
        path_obj = Path.cwd() / path_obj
        
    if not path_obj.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found: {path_obj}")
        
    return FileResponse(path_obj)

@router.get("/task-gateway", response_class=HTMLResponse)
async def get_task_gateway(job_id: str):
    """手机端网关任务页面：支持免图床局域网图片/视频加载与JS自动剪贴板复制"""
    job = publish_scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # 拼接标题、正文和标签作为全文本，物理键盘Ctrl+V一次粘贴搞定所有内容
    full_body = ""
    if job.title:
        full_body += job.title + "\n\n"
    full_body += job.body or ""
    if job.hashtags:
        full_body += "\n" + " ".join([f"#{t}" for t in job.hashtags])
        
    import json
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        pc_ip = s.getsockname()[0]
    except Exception:
        pc_ip = '127.0.0.1'
    finally:
        s.close()
        
    is_video = job.kind == "video"
    media_url = ""
    img_urls = []
    
    if is_video:
        media_url = f"http://{pc_ip}:8000/publish/task-video?job_id={job_id}"
    else:
        img_urls = [
            f"http://{pc_ip}:8000/publish/task-image?job_id={job_id}&idx={i}"
            for i in range(len(job.images))
        ]
        
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Task Gateway</title>
<style>
  body {{
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    background-color: #000;
    font-family: sans-serif;
    color: #fff;
    overflow: hidden;
  }}
  #media-container {{
    width: 90vw;
    height: 60vh;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 2px dashed #444;
    border-radius: 8px;
    background-color: #111;
  }}
  img, video {{
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }}
  #btn-next {{
    margin-top: 30px;
    width: 80vw;
    height: 60px;
    background-color: #ff2442;
    color: white;
    font-size: 20px;
    font-weight: bold;
    border: none;
    border-radius: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 10px rgba(255, 36, 66, 0.3);
  }}
  #status-txt {{
    margin-top: 15px;
    font-size: 14px;
    color: #888;
    text-align: center;
    padding: 0 10px;
  }}
  #hidden-text {{
    position: absolute;
    left: -9999px;
  }}
</style>
</head>
<body>
  <div id="media-container">
    {f'<video id="task-media" controls autoplay muted loop src="{media_url}"></video>' if is_video else '<img id="task-media" src="" alt="Loading...">'}
  </div>
  <button id="btn-next">点击此处：自动复制文案并加载媒体</button>
  <div id="status-txt">准备就绪，请先点击下方大红按钮</div>
  <textarea id="hidden-text"></textarea>

  <script>
    const isVideo = {json.dumps(is_video)};
    const images = {json.dumps(img_urls)};
    let currentIdx = 0;
    const mediaEl = document.getElementById("task-media");
    const btnEl = document.getElementById("btn-next");
    const statusEl = document.getElementById("status-txt");
    const textEl = document.getElementById("hidden-text");
    const textToCopy = {json.dumps(full_body)};

    function showImage(idx) {{
      if (idx < images.length) {{
        mediaEl.src = images[idx];
        btnEl.innerText = `长按上方图保存 (当前第 ${idx+1}/${images.length} 张)`;
        statusEl.innerText = "长按上方图片并点击“保存”，完成后点本按钮切换下一张";
      }} else {{
        mediaEl.style.display = "none";
        btnEl.style.backgroundColor = "#222";
        btnEl.innerText = "全部图片下载完毕";
        statusEl.innerText = "请在手机上执行下一步：返回桌面，打开小红书发帖！";
      }}
    }}

    function copyToClipboard() {{
      textEl.value = textToCopy;
      textEl.select();
      try {{
        document.execCommand("copy");
        statusEl.innerText = "【完整发布内容已写入系统剪贴板！】";
      }} catch (err) {{
        navigator.clipboard.writeText(textToCopy).then(() => {{
          statusEl.innerText = "【完整发布内容已写入系统剪贴板！】";
        }}).catch(e => {{
          statusEl.innerText = "剪贴板写入失败，请重试";
        }});
      }}
    }}

    if (isVideo) {{
      btnEl.innerText = "长按上方视频保存 (复制内容)";
      statusEl.innerText = "长按上方视频并选择“保存视频”，完成后返回桌面发帖！";
    }} else {{
      showImage(0);
    }}

    btnEl.addEventListener("click", (e) => {{
      e.stopPropagation();
      copyToClipboard();
      
      if (!isVideo) {{
        setTimeout(() => {{
          if (mediaEl.src && mediaEl.style.display !== "none") {{
            currentIdx++;
            showImage(currentIdx);
          }}
        }}, 500);
      }}
    }});
    
    document.body.addEventListener("click", () => {{
      copyToClipboard();
    }});
  </script>
</body>
</html>
"""
    return html_content
