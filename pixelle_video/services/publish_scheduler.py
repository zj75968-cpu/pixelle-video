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
Publish Scheduler Service

Manages a persistent queue of XHS publish jobs with optional scheduling.
Uses APScheduler for time-based execution.

Queue is persisted to data/publish_queue.json.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
QUEUE_FILE = DATA_DIR / "publish_queue.json"
PUBLISH_TIMEOUT_SECONDS = 30 * 60
ORPHAN_RUNNING_GRACE_MINUTES = 35


# ---- Job Status ---------------------------------------------------------------

class JobStatus:
    PENDING   = "pending"
    SCHEDULED = "scheduled"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# ---- Job Model ----------------------------------------------------------------

class PublishJob:
    """A single publish job in the queue."""

    def __init__(
        self,
        job_id: str,
        serial: str,
        task_id: str,
        title: str,
        body: str,
        hashtags: List[str],
        images: List[str],
        scheduled_at: Optional[str] = None,
        kind: str = "image_text",
        video_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.job_id = job_id
        self.serial = serial
        self.task_id = task_id
        self.title = title
        self.body = body
        self.hashtags = hashtags
        self.images = images
        self.scheduled_at: Optional[str] = scheduled_at  # ISO-8601 or None (immediate)
        self.kind: str = kind  # "image_text" | "video"
        self.video_path: Optional[str] = video_path
        self.dry_run: bool = bool(dry_run)
        self.status: str = JobStatus.PENDING
        self.created_at: str = datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "serial": self.serial,
            "task_id": self.task_id,
            "title": self.title,
            "body": self.body,
            "hashtags": self.hashtags,
            "images": self.images,
            "kind": self.kind,
            "video_path": self.video_path,
            "dry_run": self.dry_run,
            "scheduled_at": self.scheduled_at,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PublishJob":
        job = cls(
            job_id=data["job_id"],
            serial=data["serial"],
            task_id=data["task_id"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            hashtags=data.get("hashtags", []),
            images=data.get("images", []),
            scheduled_at=data.get("scheduled_at"),
            kind=data.get("kind", "image_text"),
            video_path=data.get("video_path"),
            dry_run=bool(data.get("dry_run", False)),
        )
        job.status = data.get("status", JobStatus.PENDING)
        job.created_at = data.get("created_at", datetime.now().isoformat())
        job.started_at = data.get("started_at")
        job.finished_at = data.get("finished_at")
        job.error = data.get("error")
        return job


# ---- Scheduler ----------------------------------------------------------------

class PublishScheduler:
    """
    Manages the publish job queue with optional APScheduler integration.

    Can be used standalone (manual trigger) or with APScheduler for
    time-based scheduling.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, PublishJob] = {}
        self._scheduler = None
        # Per-device locks to prevent concurrent execution on the same device
        self._device_locks: Dict[str, asyncio.Lock] = {}
        self._load()
        self._recover_orphaned_running_jobs()

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _load(self):
        if QUEUE_FILE.exists():
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._jobs = {jid: PublishJob.from_dict(jd) for jid, jd in data.items()}
                logger.info(f"Loaded {len(self._jobs)} publish jobs from queue")
            except Exception as e:
                logger.warning(f"Failed to load publish queue: {e}")

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {jid: j.to_dict() for jid, j in self._jobs.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to save publish queue: {e}")

    def _recover_orphaned_running_jobs(self):
        """Recover stale RUNNING jobs after process restart."""
        changed = False
        now = datetime.now()
        for job in self._jobs.values():
            if job.status != JobStatus.RUNNING:
                continue

            mark_failed = False
            reason = "Recovered orphaned RUNNING job after restart"

            if not job.started_at:
                mark_failed = True
            else:
                try:
                    started = datetime.fromisoformat(job.started_at)
                    if now - started > timedelta(minutes=ORPHAN_RUNNING_GRACE_MINUTES):
                        mark_failed = True
                        reason = (
                            f"Recovered orphaned RUNNING job after restart "
                            f"(started_at={job.started_at})"
                        )
                except Exception:
                    mark_failed = True
                    reason = "Recovered orphaned RUNNING job with invalid started_at"

            if mark_failed:
                job.status = JobStatus.FAILED
                job.error = reason
                job.finished_at = now.isoformat()
                changed = True
                logger.warning(f"Recovered job {job.job_id}: {reason}")

        if changed:
            self._save()

    # -------------------------------------------------------------------------
    # Queue Management
    # -------------------------------------------------------------------------

    def add_job(
        self,
        serial: str,
        task_id: str,
        title: str,
        body: str,
        hashtags: List[str],
        images: List[str],
        scheduled_at: Optional[str] = None,
        kind: str = "image_text",
        video_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> PublishJob:
        """Add a new publish job to the queue."""
        job = PublishJob(
            job_id=str(uuid.uuid4()),
            serial=serial,
            task_id=task_id,
            title=title,
            body=body,
            hashtags=hashtags,
            images=images,
            scheduled_at=scheduled_at,
            kind=kind,
            video_path=video_path,
            dry_run=dry_run,
        )
        self._jobs[job.job_id] = job
        self._save()

        # If APScheduler is running and a schedule time is specified, register it
        if self._scheduler and scheduled_at:
            self._schedule_job(job)
        elif not scheduled_at:
            # Immediate jobs: schedule ASAP (next tick)
            asyncio.ensure_future(self._execute_job(job.job_id))

        logger.info(f"Added publish job {job.job_id} for device {serial}")
        return job

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending, scheduled, or running job."""
        job = self._jobs.get(job_id)
        if job and job.status in (JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELLED
            job.error = job.error or "Cancelled by user"
            job.finished_at = datetime.now().isoformat()
            self._save()
            # Remove from APScheduler if present
            if self._scheduler:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    pass
            logger.info(f"Cancelled job {job_id}")
            return True
        return False

    def get_job(self, job_id: str) -> Optional[PublishJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, status_filter: Optional[str] = None) -> List[PublishJob]:
        jobs = list(self._jobs.values())
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    # -------------------------------------------------------------------------
    # APScheduler Integration
    # -------------------------------------------------------------------------

    def start_scheduler(self):
        """Start the APScheduler background scheduler."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
        except ImportError:
            logger.warning(
                "APScheduler not installed. Scheduled publishing disabled. "
                "Run: pip install apscheduler"
            )
            return

        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._scheduler.start()

        # Re-register any pending scheduled jobs (after server restart)
        for job in self._jobs.values():
            if job.status == JobStatus.SCHEDULED and job.scheduled_at:
                self._schedule_job(job)

        logger.info("Publish scheduler started")

    def stop_scheduler(self):
        """Gracefully stop the APScheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Publish scheduler stopped")

    def _schedule_job(self, job: PublishJob):
        """Register a job in APScheduler at its scheduled time."""
        if not self._scheduler:
            return
        try:
            from apscheduler.triggers.date import DateTrigger  # type: ignore
            run_at = datetime.fromisoformat(job.scheduled_at)
            self._scheduler.add_job(
                self._execute_job,
                trigger=DateTrigger(run_date=run_at),
                args=[job.job_id],
                id=job.job_id,
                replace_existing=True,
            )
            job.status = JobStatus.SCHEDULED
            self._save()
            logger.info(f"Scheduled job {job.job_id} at {job.scheduled_at}")
        except Exception as e:
            logger.error(f"Failed to schedule job {job.job_id}: {e}")

    # -------------------------------------------------------------------------
    # Job Execution
    # -------------------------------------------------------------------------

    async def _execute_job(self, job_id: str):
        """Execute a publish job (serialized per device)."""
        from pixelle_video.services.xhs_publisher import XHSPublisher, XHSPublishError

        job = self._jobs.get(job_id)
        if not job or job.status == JobStatus.CANCELLED:
            return

        # Acquire per-device lock to prevent concurrent execution on same device
        if job.serial not in self._device_locks:
            self._device_locks[job.serial] = asyncio.Lock()
        device_lock = self._device_locks[job.serial]

        async with device_lock:
            # Re-check after acquiring lock (may have been cancelled while waiting)
            if job.status == JobStatus.CANCELLED:
                return

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().isoformat()
            self._save()

            try:
                publisher = XHSPublisher(serial=job.serial)
                if job.kind == "video":
                    if not job.video_path:
                        raise XHSPublishError(
                            "Video job missing video_path"
                        )
                    success = await asyncio.wait_for(
                        publisher.publish_video(
                            video_path=job.video_path,
                            title=job.title,
                            body=job.body,
                            hashtags=job.hashtags,
                            dry_run=job.dry_run,
                        ),
                        timeout=PUBLISH_TIMEOUT_SECONDS,
                    )
                else:
                    success = await asyncio.wait_for(
                        publisher.publish(
                            images=job.images,
                            title=job.title,
                            body=job.body,
                            hashtags=job.hashtags,
                        ),
                        timeout=PUBLISH_TIMEOUT_SECONDS,
                    )
                job.status = JobStatus.SUCCESS if success else JobStatus.FAILED
                if not success:
                    job.error = "Publish did not confirm success"
            except asyncio.TimeoutError:
                job.status = JobStatus.FAILED
                job.error = (
                    f"Publish timed out after {PUBLISH_TIMEOUT_SECONDS // 60} minutes"
                )
                logger.error(f"Job {job_id} timed out")
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                logger.error(f"Job {job_id} failed: {exc}")
            finally:
                job.finished_at = datetime.now().isoformat()
                self._save()

    async def execute_now(self, job_id: str) -> bool:
        """Manually trigger a pending job immediately."""
        job = self._jobs.get(job_id)
        if not job or job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
            return False
        await self._execute_job(job_id)
        return True


# Module-level singleton
publish_scheduler = PublishScheduler()
