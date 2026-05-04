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

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from api.schemas.publish import (
    PublishJobRequest,
    PublishJobResponse,
    PublishJobListResponse,
    PublishBatchCreateResponse,
)
from pixelle_video.services.publish_scheduler import publish_scheduler, JobStatus

router = APIRouter(prefix="/publish", tags=["Publish Queue"])


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
