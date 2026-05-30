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
MAX_JOB_RETRIES = 2  # total attempts = MAX_JOB_RETRIES + 1
RETRY_DELAY_SECONDS = 15  # wait between retries
SCHEDULE_POLL_INTERVAL_SECONDS = 60


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
        post_type: str = "content",          # "content" | "traffic"
        delete_after_hours: Optional[float] = None,  # auto-delete TTL (traffic posts)
        kind_backup: Optional[str] = None,
        body_backup: Optional[str] = None,
        username: str = "default",
        auto_comment_text: Optional[str] = None,
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
        self.post_type: str = post_type  # "content" | "traffic"
        self.delete_after_hours: Optional[float] = delete_after_hours
        self.kind_backup: Optional[str] = kind_backup
        self.body_backup: Optional[str] = body_backup
        self.username = username
        self.auto_comment_text: Optional[str] = auto_comment_text
        self.status: str = JobStatus.PENDING
        self.created_at: str = datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None
        self.retry_count: int = 0
        self.screenshots: List[str] = []
        self.progress_log: List[str] = []

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
            "post_type": self.post_type,
            "delete_after_hours": self.delete_after_hours,
            "auto_comment_text": self.auto_comment_text,
            "kind_backup": self.kind_backup,
            "body_backup": self.body_backup,
            "username": self.username,
            "scheduled_at": self.scheduled_at,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "retry_count": self.retry_count,
            "screenshots": self.screenshots,
            "progress_log": self.progress_log,
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
            post_type=data.get("post_type", "content"),
            delete_after_hours=data.get("delete_after_hours"),
            kind_backup=data.get("kind_backup"),
            body_backup=data.get("body_backup"),
            username=data.get("username", "default"),
            auto_comment_text=data.get("auto_comment_text"),
        )
        job.status = data.get("status", JobStatus.PENDING)
        job.created_at = data.get("created_at", datetime.now().isoformat())
        job.started_at = data.get("started_at")
        job.finished_at = data.get("finished_at")
        job.error = data.get("error")
        job.retry_count = int(data.get("retry_count", 0))
        job.screenshots = data.get("screenshots") or []
        job.progress_log = data.get("progress_log") or []
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
        # Background TTL watcher (used when APScheduler is not running, e.g. Streamlit)
        self._ttl_thread = None
        self._ttl_stop_event = None
        self._ttl_interval_minutes: float = 15.0
        # Background scheduled-job polling thread (fires due scheduled jobs when APScheduler
        # is not running, e.g. in Streamlit)
        self._sched_poll_thread = None
        self._sched_poll_stop_event = None
        self._background_polling_started = False
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

    def reload_from_disk(self):
        """Re-read the queue file to pick up jobs added by external processes."""
        self._load()

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

    def _start_schedule_poll(self) -> bool:
        """Start a background thread that fires SCHEDULED jobs when their time arrives.

        Used when APScheduler is not running (e.g. Streamlit context).
        Checks every 60 seconds; safe to call multiple times.

        Returns True only when a polling thread is running.
        """
        import threading as _threading

        if self._sched_poll_thread and self._sched_poll_thread.is_alive():
            return not (
                self._sched_poll_stop_event is not None
                and self._sched_poll_stop_event.is_set()
            )

        stop_event = _threading.Event()
        self._sched_poll_stop_event = stop_event

        def _poll():
            while not stop_event.is_set():
                try:
                    now = datetime.now()
                    for job in list(self._jobs.values()):
                        if job.status != JobStatus.SCHEDULED:
                            continue
                        if not job.scheduled_at:
                            continue
                        try:
                            run_at = datetime.fromisoformat(job.scheduled_at)
                        except Exception:
                            continue
                        if now >= run_at:
                            logger.info(
                                f"[SchedulePoll] Firing due job {job.job_id} "
                                f"(scheduled_at={job.scheduled_at})"
                            )
                            _threading.Thread(
                                target=lambda jid=job.job_id: asyncio.run(
                                    self._execute_job(jid)
                                ),
                                daemon=True,
                            ).start()
                except Exception as _exc:
                    logger.warning(f"[SchedulePoll] error: {_exc}")
                stop_event.wait(SCHEDULE_POLL_INTERVAL_SECONDS)

        self._sched_poll_thread = _threading.Thread(target=_poll, daemon=True, name="sched-poll")
        self._sched_poll_thread.start()
        logger.debug("[SchedulePoll] background polling thread started")
        return self._sched_poll_thread.is_alive()

    def start_background_polling(self):
        """Start the scheduled-job polling thread once."""
        thread = self._sched_poll_thread
        if self._background_polling_started and thread is not None and thread.is_alive():
            return
        self._background_polling_started = bool(self._start_schedule_poll())

    def stop_background_polling(self):
        """Stop the scheduled-job polling thread safely."""
        thread = self._sched_poll_thread
        if not self._background_polling_started and thread is None:
            return

        if self._sched_poll_stop_event is not None:
            self._sched_poll_stop_event.set()

        if thread is not None:
            try:
                import threading as _threading
                if thread is not _threading.current_thread():
                    thread.join(timeout=0.2)
            except RuntimeError:
                pass

            if not thread.is_alive():
                self._sched_poll_thread = None
                self._sched_poll_stop_event = None

        self._background_polling_started = False

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
        post_type: str = "content",
        delete_after_hours: Optional[float] = None,
        auto_comment_text: Optional[str] = None,
    ) -> PublishJob:
        """Add a new publish job to the queue."""
        # 过滤小红书违禁词（标题 / 正文 / 标签）
        try:
            from pixelle_video.utils.banned_keywords import filter_post
            title, body, hashtags, _hits = filter_post(
                title=title, body=body, hashtags=hashtags
            )
            if _hits:
                logger.info(
                    f"[banned_keywords] scrubbed {len(_hits)} term(s) from job "
                    f"task_id={task_id}: {_hits}"
                )
        except Exception as _exc:  # noqa: BLE001
            logger.warning(f"[banned_keywords] filter skipped: {_exc}")

        from pixelle_video.utils.user_context import get_current_username
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
            post_type=post_type,
            delete_after_hours=delete_after_hours,
            auto_comment_text=auto_comment_text,
            username=get_current_username(),
        )
        self._jobs[job.job_id] = job
        self._save()

        # 写违禁词命中审计日志
        if _hits:
            try:
                from pixelle_video.utils.banned_keywords import append_audit as _append_audit
                _append_audit(task_id=task_id, serial=serial, job_id=job.job_id, hits=_hits)
            except Exception as _aex:
                logger.warning(f"[banned_keywords] audit write failed: {_aex}")

        # If APScheduler is running and a schedule time is specified, register it.
        # Otherwise preserve standalone compatibility by enabling fallback polling.
        if self._scheduler and getattr(self._scheduler, "running", False) and scheduled_at:
            self._schedule_job(job)
        elif scheduled_at:
            job.status = JobStatus.SCHEDULED
            self._save()
            logger.info(f"Job {job.job_id} marked SCHEDULED at {scheduled_at} (polling mode)")
            self.start_background_polling()
        else:
            # Immediate jobs: schedule ASAP (next tick).
            # asyncio.get_running_loop() raises RuntimeError when there is no running
            # loop (e.g. Streamlit sync thread, plain scripts). Use that to branch:
            # - inside async context  → ensure_future (non-blocking)
            # - Streamlit / sync thread → daemon thread + asyncio.run
            import threading as _threading

            try:
                _loop = asyncio.get_running_loop()  # raises if no loop running
                _loop.create_task(self._execute_job(job.job_id))
            except RuntimeError:
                _threading.Thread(
                    target=lambda jid=job.job_id: asyncio.run(self._execute_job(jid)),
                    daemon=True,
                ).start()

        logger.info(f"Added publish job {job.job_id} for device {serial}")
        return job

    def next_available_slot(self, serial: str) -> Optional[datetime]:
        """返回该设备下一个未被占用的每日计划时间槽。

        从 config.xhs_publish.daily_schedule_times 读取时间段列表，
        在未来 7 天内搜索第一个没有已有任务的时间槽。
        """
        try:
            from pixelle_video.config import config_manager  # local import to avoid circular
            times_str: List[str] = config_manager.config.xhs_publish.daily_schedule_times
        except Exception:
            times_str = []

        if not times_str:
            return None

        # Parse "HH:MM" → (hour, minute) tuples
        slots: List[tuple] = []
        for t in times_str:
            try:
                h, m = map(int, t.strip().split(":"))
                slots.append((h, m))
            except Exception:
                continue

        if not slots:
            return None

        # Collect all occupied (year, month, day, hour, minute) keys for this device
        occupied: set = set()
        for job in self._jobs.values():
            if job.serial != serial:
                continue
            if job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING):
                continue
            if not job.scheduled_at:
                continue
            try:
                dt = datetime.fromisoformat(job.scheduled_at)
                occupied.add((dt.year, dt.month, dt.day, dt.hour, dt.minute))
            except Exception:
                continue

        now = datetime.now()
        for day_offset in range(8):  # search up to 7 days ahead
            base = now.replace(second=0, microsecond=0) + timedelta(days=day_offset)
            for h, m in sorted(slots):
                candidate = base.replace(hour=h, minute=m)
                if candidate <= now:
                    continue
                key = (candidate.year, candidate.month, candidate.day, candidate.hour, candidate.minute)
                if key not in occupied:
                    return candidate

        return None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending, scheduled, or running job."""
        from pixelle_video.utils.user_context import get_current_username
        current_user = get_current_username()
        job = self._jobs.get(job_id)
        if job and getattr(job, "username", "default") == current_user and job.status in (JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING):
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

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a finished/failed/cancelled job from the queue entirely.
        Active jobs (pending/scheduled/running) cannot be removed — cancel first.
        Returns True if the job was removed.
        """
        from pixelle_video.utils.user_context import get_current_username
        current_user = get_current_username()
        job = self._jobs.get(job_id)
        if not job or getattr(job, "username", "default") != current_user:
            return False
        if job.status in (JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING):
            return False
        del self._jobs[job_id]
        if self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._save()
        logger.info(f"Removed job {job_id} from queue")
        return True

    def bulk_remove(self, statuses: List[str]) -> int:
        """Remove all jobs whose status is in `statuses`. Returns count removed."""
        from pixelle_video.utils.user_context import get_current_username
        current_user = get_current_username()
        active = {JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING}
        targets = [
            jid for jid, j in self._jobs.items()
            if j.status in statuses and j.status not in active and getattr(j, "username", "default") == current_user
        ]
        for jid in targets:
            del self._jobs[jid]
            if self._scheduler:
                try:
                    self._scheduler.remove_job(jid)
                except Exception:
                    pass
        if targets:
            self._save()
            logger.info(f"Bulk-removed {len(targets)} job(s) with status in {statuses}")
        return len(targets)

    def bulk_cancel_pending(self) -> int:
        """Cancel all pending/scheduled jobs. Returns count cancelled."""
        from pixelle_video.utils.user_context import get_current_username
        current_user = get_current_username()
        targets = [
            jid for jid, j in self._jobs.items()
            if j.status in (JobStatus.PENDING, JobStatus.SCHEDULED) and getattr(j, "username", "default") == current_user
        ]
        for jid in targets:
            self.cancel_job(jid)
        return len(targets)

    def get_job(self, job_id: str) -> Optional[PublishJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, status_filter: Optional[str] = None) -> List[PublishJob]:
        from pixelle_video.utils.user_context import get_current_username
        current_user = get_current_username()
        jobs = [j for j in self._jobs.values() if getattr(j, "username", "default") == current_user]
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    # -------------------------------------------------------------------------
    # APScheduler Integration
    # -------------------------------------------------------------------------

    def start_scheduler(self):
        """Start the APScheduler background scheduler."""
        if self._scheduler and self._scheduler.running:
            return
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

        # Periodic auto-delete check (every 15 minutes)
        self._scheduler.add_job(
            self.check_and_delete_expired,
            "interval",
            minutes=15,
            id="auto_delete_check",
            replace_existing=True,
        )

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
        """Execute a publish job (serialized per device) with automatic retry."""
        job = self._jobs.get(job_id)
        if not job or job.status == JobStatus.CANCELLED:
            return

        from pixelle_video.utils.user_context import set_current_user
        with set_current_user(getattr(job, "username", "default")):
            await self._execute_job_impl(job)

    async def _execute_job_impl(self, job: PublishJob):
        from pixelle_video.services.xhs_publisher import XHSPublisher

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

            from pixelle_video.services.android_device_dispatcher import DistributionAdapter
            adapter = DistributionAdapter()
            last_error: Optional[str] = None

            def _progress(msg: str):
                """Append a timestamped progress entry to the job and persist."""
                ts = datetime.now().strftime("%H:%M:%S")
                job.progress_log.append(f"[{ts}] {msg}")
                self._save()

            for attempt in range(MAX_JOB_RETRIES + 1):
                if attempt > 0:
                    logger.warning(
                        f"Job {job.job_id}: retry {attempt}/{MAX_JOB_RETRIES} "
                        f"after failure: {last_error}"
                    )
                    job.retry_count = attempt
                    self._save()
                    # Force-stop XHS to get a clean state before retry (only if legacy mode)
                    if DistributionAdapter.get_mode() == "legacy":
                        try:
                            import subprocess as _sp
                            _sp.run(
                                [
                                    XHSPublisher._resolve_adb(), "-s", job.serial,
                                    "shell", "am", "force-stop", "com.xingin.xhs",
                                ],
                                capture_output=True, timeout=10,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

                try:
                    success = await asyncio.wait_for(
                        adapter.execute_job(
                            job=job,
                            progress_callback=_progress,
                        ),
                        timeout=PUBLISH_TIMEOUT_SECONDS,
                    )

                    if success:
                        job.status = JobStatus.SUCCESS
                        if job.auto_comment_text:
                            _progress(f"触发自动评论: {job.auto_comment_text}")
                            comment_success = await self._comment_post_now_impl(job, job.auto_comment_text)
                            if comment_success:
                                _progress("自动评论成功")
                            else:
                                _progress("自动评论失败")
                        break  # done, exit retry loop
                    else:
                        last_error = job.error or "Publish did not confirm success"
                        if attempt < MAX_JOB_RETRIES:
                            continue
                        job.status = JobStatus.FAILED
                        job.error = last_error

                except asyncio.TimeoutError:
                    job.status = JobStatus.FAILED
                    job.error = (
                        f"Publish timed out after {PUBLISH_TIMEOUT_SECONDS // 60} minutes"
                    )
                    logger.error(f"Job {job.job_id} timed out")
                    break  # don't retry timeouts

                except Exception as exc:
                    last_error = str(exc)
                    # 不要重试由代码 bug 引发的失败：例如 AttributeError/TypeError/NameError/ImportError
                    _cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None) or exc
                    _is_code_bug = isinstance(
                        _cause,
                        (AttributeError, TypeError, NameError, ImportError, SyntaxError),
                    )
                    if attempt < MAX_JOB_RETRIES and not _is_code_bug:
                        continue  # retry transient UI errors
                    job.status = JobStatus.FAILED
                    job.error = last_error
                    if _is_code_bug:
                        logger.error(
                            f"Job {job.job_id} failed due to code bug ({type(_cause).__name__}); "
                            f"skipping remaining retries: {exc}"
                        )
                    else:
                        logger.error(
                            f"Job {job.job_id} failed after {attempt + 1} attempt(s): {exc}"
                        )
                    break

            job.finished_at = datetime.now().isoformat()
            self._save()

            # 自动分析失败任务并写入知识库（后台异步，不阻塞主流程）
            if job.status == JobStatus.FAILED and job.error:
                try:
                    from pixelle_video.agent.publish_knowledge import analyze_and_record_failure
                    asyncio.create_task(
                        analyze_and_record_failure(
                            job_id=job.job_id,
                            job_kind=job.kind or "",
                            error=job.error,
                            progress_log=list(job.progress_log or []),
                        )
                    )
                except Exception:
                    pass  # knowledge analysis is optional, never crash the scheduler

    async def execute_now(self, job_id: str) -> bool:
        """Manually trigger a pending job immediately."""
        job = self._jobs.get(job_id)
        if not job or job.status not in (JobStatus.PENDING, JobStatus.SCHEDULED):
            return False
        await self._execute_job(job_id)
        return True

    # -------------------------------------------------------------------------
    # Auto-Delete (TTL) Logic
    # -------------------------------------------------------------------------

    async def delete_post_now(self, job_id: str) -> bool:
        """Manually trigger deletion of a completed job's post."""
        job = self._jobs.get(job_id)
        if not job or job.status not in (JobStatus.SUCCESS, "done", "deleted"):
            logger.warning(f"delete_post_now: job {job_id} not in a completed state (status={getattr(job, 'status', None)})")
            return False
        return await self._do_delete_job(job)

    async def _do_delete_job(self, job: "PublishJob") -> bool:
        """Call XHSPublisher.delete_post for a finished job."""
        from pixelle_video.utils.user_context import set_current_user
        with set_current_user(getattr(job, "username", "default")):
            return await self._do_delete_job_impl(job)

    async def _do_delete_job_impl(self, job: "PublishJob") -> bool:
        from pixelle_video.services.android_device_dispatcher import DistributionAdapter
        mode = DistributionAdapter.get_mode()
        
        if mode == "agent_pull":
            # Backup original kind and body
            if not job.kind_backup:
                job.kind_backup = job.kind
            if not job.body_backup:
                job.body_backup = job.body
                
            job.kind = "delete"
            job.status = JobStatus.RUNNING
            self._save()
            
            # Wait for client agent to complete
            import time
            wait_timeout = 300
            try:
                from pixelle_video.config import config_manager
                glb = config_manager.config
                if hasattr(glb, "distribution") and glb.distribution and glb.distribution.result_wait_seconds:
                    wait_timeout = glb.distribution.result_wait_seconds
            except Exception:
                pass
                
            start_time = time.time()
            while time.time() - start_time < wait_timeout:
                if job.status == "deleted":
                    # Keep deleted status, restore metadata
                    job.kind = job.kind_backup or job.kind
                    job.body = job.body_backup or job.body
                    self._save()
                    return True
                elif job.status == JobStatus.FAILED:
                    logger.error(f"Agent failed delete post for job {job.job_id}: {job.error}")
                    # Restore original status
                    job.status = JobStatus.SUCCESS
                    job.kind = job.kind_backup or job.kind
                    job.body = job.body_backup or job.body
                    self._save()
                    return False
                await asyncio.sleep(2)
                
            # Timeout
            logger.error(f"Timeout waiting for agent to delete post for job {job.job_id}")
            job.status = JobStatus.SUCCESS
            job.kind = job.kind_backup or job.kind
            job.body = job.body_backup or job.body
            self._save()
            return False
            
        elif mode == "phone_agent":
            from pixelle_video.config import config_manager
            from pixelle_video.services.phone_agent_client import (
                delete_http,
                resolve_agent_url,
                wait_for_status,
            )
            
            cfg = config_manager.config
            agent_url = resolve_agent_url(getattr(job, "serial", ""))
            token = cfg.phone_agent.token.strip()
            
            if not agent_url:
                logger.error("phone_agent.url not configured, cannot delete post")
                return False
                
            res = delete_http(title=job.title, agent_url=agent_url, token=token)
            if not res.get("ok"):
                logger.error(f"Failed to trigger delete via HTTP agent: {res.get('error')}")
                return False
                
            task_id = res["task_id"]
            loop = asyncio.get_event_loop()
            wait_res = await loop.run_in_executor(
                None,
                lambda: wait_for_status(
                    task_id=task_id,
                    agent_url=agent_url,
                    token=token,
                    success_states=("deleted",),
                )
            )
            
            if wait_res.get("status") == "deleted":
                job.status = "deleted"
                self._save()
                logger.info(f"Auto-deleted post via HTTP agent for job {job.job_id} ('{job.title}')")
                return True
            else:
                logger.error(f"HTTP Agent failed to delete post: {wait_res.get('message')}")
                return False
                
        else:
            # Fall back to legacy ADB XHSPublisher execution
            from pixelle_video.services.xhs_publisher import XHSPublisher
            publisher = XHSPublisher(serial=job.serial, strict_mode=False)
            try:
                success = await publisher.delete_post(post_title=job.title)
                if success:
                    job.status = "deleted"
                    self._save()
                    logger.info(f"Auto-deleted post for job {job.job_id} ('{job.title}')")
                return success
            except Exception as exc:
                logger.error(f"Auto-delete failed for job {job.job_id}: {exc}")
                return False

    async def comment_post_now(self, job_id: str, comment_text: str) -> bool:
        """Manually trigger comment on a completed job's post."""
        job = self._jobs.get(job_id)
        if not job or job.status not in (JobStatus.SUCCESS, "done"):
            logger.warning(f"comment_post_now: job {job_id} not in a completed state (status={getattr(job, 'status', None)})")
            return False

        from pixelle_video.utils.user_context import set_current_user
        with set_current_user(getattr(job, "username", "default")):
            return await self._comment_post_now_impl(job, comment_text)

    async def _comment_post_now_impl(self, job: "PublishJob", comment_text: str) -> bool:
        from pixelle_video.services.android_device_dispatcher import DistributionAdapter
        mode = DistributionAdapter.get_mode()
        
        if mode == "agent_pull":
            # Backup original kind and body
            if not job.kind_backup:
                job.kind_backup = job.kind
            if not job.body_backup:
                job.body_backup = job.body
                
            job.kind = "comment"
            job.body = comment_text
            job.status = JobStatus.RUNNING
            self._save()
            
            # Wait for client agent to complete
            import time
            wait_timeout = 300
            try:
                from pixelle_video.config import config_manager
                glb = config_manager.config
                if hasattr(glb, "distribution") and glb.distribution and glb.distribution.result_wait_seconds:
                    wait_timeout = glb.distribution.result_wait_seconds
            except Exception:
                pass
                
            start_time = time.time()
            while time.time() - start_time < wait_timeout:
                if job.status == "comment_success":
                    # Restore status to SUCCESS, restore metadata
                    job.status = JobStatus.SUCCESS
                    job.kind = job.kind_backup or job.kind
                    job.body = job.body_backup or job.body
                    self._save()
                    return True
                elif job.status == JobStatus.FAILED:
                    logger.error(f"Agent failed to comment on post for job {job.job_id}: {job.error}")
                    # Restore original status
                    job.status = JobStatus.SUCCESS
                    job.kind = job.kind_backup or job.kind
                    job.body = job.body_backup or job.body
                    self._save()
                    return False
                await asyncio.sleep(2)
                
            # Timeout
            logger.error(f"Timeout waiting for agent to comment on post for job {job.job_id}")
            job.status = JobStatus.SUCCESS
            job.kind = job.kind_backup or job.kind
            job.body = job.body_backup or job.body
            self._save()
            return False
            
        elif mode == "phone_agent":
            from pixelle_video.config import config_manager
            from pixelle_video.services.phone_agent_client import (
                comment_http,
                resolve_agent_url,
                wait_for_status,
            )
            
            cfg = config_manager.config
            agent_url = resolve_agent_url(getattr(job, "serial", ""))
            token = cfg.phone_agent.token.strip()
            
            if not agent_url:
                logger.error("phone_agent.url not configured, cannot comment post")
                return False
                
            res = comment_http(title=job.title, comment_text=comment_text, agent_url=agent_url, token=token)
            if not res.get("ok"):
                logger.error(f"Failed to trigger comment via HTTP agent: {res.get('error')}")
                return False
                
            task_id = res["task_id"]
            loop = asyncio.get_event_loop()
            wait_res = await loop.run_in_executor(
                None,
                lambda: wait_for_status(
                    task_id=task_id,
                    agent_url=agent_url,
                    token=token,
                    success_states=("comment_success", "success"),
                )
            )
            
            if wait_res.get("status") in ("comment_success", "success"):
                logger.info(f"Auto-commented post via HTTP agent for job {job.job_id} ('{job.title}')")
                return True
            else:
                logger.error(f"Failed waiting for comment via HTTP agent: {wait_res.get('message')}")
                return False
        else:
            # Fall back to legacy ADB XHSPublisher execution
            from pixelle_video.services.xhs_publisher import XHSPublisher
            publisher = XHSPublisher(serial=job.serial, strict_mode=False)
            try:
                success = await publisher.comment_on_post(post_title=job.title, comment_text=comment_text)
                return success
            except Exception as exc:
                logger.error(f"Comment failed for job {job.job_id}: {exc}")
                return False

    async def check_and_delete_expired(self):
        """
        Check all completed jobs for expired TTL and delete them.
        Called by the scheduler every 15 minutes.
        """
        now = datetime.now()
        for job in list(self._jobs.values()):
            if job.status != JobStatus.SUCCESS:
                continue
            if not job.delete_after_hours or not job.finished_at:
                continue
            try:
                finished = datetime.fromisoformat(job.finished_at)
                expire_at = finished + timedelta(hours=job.delete_after_hours)
                if now >= expire_at:
                    logger.info(
                        f"Job {job.job_id} ('{job.title}') expired "
                        f"(TTL={job.delete_after_hours}h), deleting..."
                    )
                    await self._do_delete_job(job)
            except Exception as exc:
                logger.warning(f"check_and_delete_expired error for {job.job_id}: {exc}")

    # -------------------------------------------------------------------------
    # Background TTL watcher (thread-based; works without APScheduler/event loop)
    # -------------------------------------------------------------------------

    def start_ttl_watcher(self, interval_minutes: float = 15.0) -> bool:
        """
        Start a background daemon thread that periodically scans success jobs
        for expired TTL and auto-deletes them. Safe to call from environments
        without a persistent asyncio event loop (e.g. Streamlit).

        Idempotent: subsequent calls are no-ops while the watcher is alive.
        Returns True if a new watcher was started, False if one is already running.
        """
        import threading

        if self._ttl_thread is not None and self._ttl_thread.is_alive():
            return False

        try:
            interval_minutes = max(0.5, float(interval_minutes))
        except (TypeError, ValueError):
            interval_minutes = 15.0
        self._ttl_interval_minutes = interval_minutes
        self._ttl_stop_event = threading.Event()

        def _runner(stop_event: threading.Event, interval_min: float) -> None:
            logger.info(
                f"TTL watcher started (interval={interval_min}min, "
                f"thread={threading.current_thread().name})"
            )
            # Tiny initial delay so we don't double-fire with APScheduler at startup
            if stop_event.wait(timeout=5.0):
                return
            while not stop_event.is_set():
                try:
                    asyncio.run(self.check_and_delete_expired())
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"TTL watcher iteration failed: {exc}")
                # Sleep in small steps so stop_event can wake us promptly.
                stop_event.wait(timeout=interval_min * 60.0)
            logger.info("TTL watcher stopped")

        self._ttl_thread = threading.Thread(
            target=_runner,
            args=(self._ttl_stop_event, interval_minutes),
            name="publish-ttl-watcher",
            daemon=True,
        )
        self._ttl_thread.start()
        return True

    def stop_ttl_watcher(self) -> None:
        """Signal the TTL watcher thread to stop (if running)."""
        if self._ttl_stop_event is not None:
            self._ttl_stop_event.set()
        self._ttl_thread = None

    def ttl_watcher_status(self) -> Dict[str, object]:
        """Inspect the background TTL watcher."""
        alive = bool(self._ttl_thread is not None and self._ttl_thread.is_alive())
        return {
            "running": alive,
            "interval_minutes": self._ttl_interval_minutes if alive else None,
            "thread_name": (self._ttl_thread.name if alive else None),
        }


# Module-level singleton
publish_scheduler = PublishScheduler()
