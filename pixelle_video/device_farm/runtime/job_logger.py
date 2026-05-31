"""Job execution logger for device farm automation.

Tracks job execution with detailed step logging, screenshots, and error capture.
Logs are stored as YAML files for human readability and easy debugging.
"""

import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepResult(str, Enum):
    """Step execution result."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY = "retry"


@dataclass
class StepLog:
    """Log entry for a single execution step."""
    step_id: str
    timestamp: str
    result: StepResult
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['result'] = self.result.value
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'StepLog':
        """Create from dictionary."""
        data = data.copy()
        if 'result' in data:
            data['result'] = StepResult(data['result'])
        return cls(**data)


@dataclass
class JobLog:
    """Complete job execution log."""
    job_id: str
    phone_id: str
    flow_id: str
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_step: Optional[str] = None
    error: Optional[str] = None
    screenshots: List[str] = field(default_factory=list)
    action_log: List[StepLog] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for YAML serialization."""
        data = asdict(self)
        data['status'] = self.status.value
        data['action_log'] = [step.to_dict() for step in self.action_log]
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'JobLog':
        """Create from dictionary loaded from YAML."""
        data = data.copy()
        if 'status' in data:
            data['status'] = JobStatus(data['status'])
        if 'action_log' in data:
            data['action_log'] = [StepLog.from_dict(step) for step in data['action_log']]
        return cls(**data)


class JobLogger:
    """Logger for tracking job execution with screenshots and detailed step logs."""

    def __init__(self, logs_dir: Optional[str] = None):
        """Initialize job logger.

        Args:
            logs_dir: Directory for storing job logs. Defaults to logs/jobs/
        """
        if logs_dir is None:
            # Default to logs/jobs/ relative to project root
            project_root = Path(__file__).parent.parent.parent.parent
            logs_dir = project_root / "logs" / "jobs"

        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._active_jobs: Dict[str, JobLog] = {}

    def create_job_log(
        self,
        job_id: str,
        phone_id: str,
        flow_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> JobLog:
        """Create a new job log.

        Args:
            job_id: Unique job identifier
            phone_id: Device phone ID
            flow_id: Automation flow identifier
            metadata: Optional additional metadata

        Returns:
            JobLog: Created job log instance

        Raises:
            ValueError: If job_id already exists
        """
        if job_id in self._active_jobs:
            raise ValueError(f"Job {job_id} already exists")

        job_log = JobLog(
            job_id=job_id,
            phone_id=phone_id,
            flow_id=flow_id,
            status=JobStatus.PENDING,
            created_at=datetime.now().isoformat(),
            metadata=metadata or {}
        )

        self._active_jobs[job_id] = job_log
        self._save_log(job_log)
        return job_log

    def start_job(self, job_id: str) -> None:
        """Mark job as started.

        Args:
            job_id: Job identifier

        Raises:
            ValueError: If job not found
        """
        job_log = self._get_job(job_id)
        job_log.status = JobStatus.RUNNING
        job_log.started_at = datetime.now().isoformat()
        self._save_log(job_log)

    def log_step(
        self,
        job_id: str,
        step_id: str,
        result: StepResult,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        screenshot_before: Optional[str] = None,
        screenshot_after: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a step execution.

        Args:
            job_id: Job identifier
            step_id: Step identifier
            result: Step execution result
            duration_ms: Step duration in milliseconds
            error: Error message if step failed
            screenshot_before: Path to screenshot taken before step
            screenshot_after: Path to screenshot taken after step
            metadata: Optional additional metadata

        Raises:
            ValueError: If job not found
        """
        job_log = self._get_job(job_id)

        step_log = StepLog(
            step_id=step_id,
            timestamp=datetime.now().isoformat(),
            result=result,
            duration_ms=duration_ms,
            error=error,
            screenshot_before=screenshot_before,
            screenshot_after=screenshot_after,
            metadata=metadata or {}
        )

        job_log.action_log.append(step_log)

        # Track screenshots
        if screenshot_before:
            job_log.screenshots.append(screenshot_before)
        if screenshot_after:
            job_log.screenshots.append(screenshot_after)

        self._save_log(job_log)

    def save_failure(
        self,
        job_id: str,
        error: str,
        failed_step: Optional[str] = None,
        screenshot: Optional[str] = None
    ) -> None:
        """Mark job as failed and save failure details.

        Args:
            job_id: Job identifier
            error: Error message
            failed_step: Step ID where failure occurred
            screenshot: Path to failure screenshot

        Raises:
            ValueError: If job not found
        """
        job_log = self._get_job(job_id)
        job_log.status = JobStatus.FAILED
        job_log.error = error
        job_log.failed_step = failed_step
        job_log.completed_at = datetime.now().isoformat()

        if screenshot:
            job_log.screenshots.append(screenshot)

        self._save_log(job_log)

    def complete_job(self, job_id: str) -> None:
        """Mark job as completed successfully.

        Args:
            job_id: Job identifier

        Raises:
            ValueError: If job not found
        """
        job_log = self._get_job(job_id)
        job_log.status = JobStatus.COMPLETED
        job_log.completed_at = datetime.now().isoformat()
        self._save_log(job_log)

    def cancel_job(self, job_id: str, reason: Optional[str] = None) -> None:
        """Mark job as cancelled.

        Args:
            job_id: Job identifier
            reason: Optional cancellation reason

        Raises:
            ValueError: If job not found
        """
        job_log = self._get_job(job_id)
        job_log.status = JobStatus.CANCELLED
        job_log.completed_at = datetime.now().isoformat()
        if reason:
            job_log.error = f"Cancelled: {reason}"
        self._save_log(job_log)

    def get_job_log(self, job_id: str) -> Optional[JobLog]:
        """Get job log by ID.

        Args:
            job_id: Job identifier

        Returns:
            JobLog if found, None otherwise
        """
        # Check active jobs first
        if job_id in self._active_jobs:
            return self._active_jobs[job_id]

        # Try loading from disk
        log_path = self._get_log_path(job_id)
        if log_path.exists():
            return self._load_log(job_id)

        return None

    def list_job_logs(
        self,
        phone_id: Optional[str] = None,
        flow_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100
    ) -> List[JobLog]:
        """List job logs with optional filters.

        Args:
            phone_id: Filter by phone ID
            flow_id: Filter by flow ID
            status: Filter by status
            limit: Maximum number of logs to return

        Returns:
            List of job logs matching criteria
        """
        logs = []

        # Get all log files sorted by modification time (newest first)
        log_files = sorted(
            self.logs_dir.glob("*.yaml"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for log_file in log_files[:limit * 2]:  # Load more than limit to account for filtering
            try:
                job_id = log_file.stem
                job_log = self.get_job_log(job_id)

                if job_log is None:
                    continue

                # Apply filters
                if phone_id and job_log.phone_id != phone_id:
                    continue
                if flow_id and job_log.flow_id != flow_id:
                    continue
                if status and job_log.status != status:
                    continue

                logs.append(job_log)

                if len(logs) >= limit:
                    break

            except Exception:
                # Skip corrupted log files
                continue

        return logs

    def _get_job(self, job_id: str) -> JobLog:
        """Get job log or raise error.

        Args:
            job_id: Job identifier

        Returns:
            JobLog instance

        Raises:
            ValueError: If job not found
        """
        job_log = self.get_job_log(job_id)
        if job_log is None:
            raise ValueError(f"Job {job_id} not found")
        return job_log

    def _get_log_path(self, job_id: str) -> Path:
        """Get log file path for job.

        Args:
            job_id: Job identifier

        Returns:
            Path to log file
        """
        return self.logs_dir / f"{job_id}.yaml"

    def _save_log(self, job_log: JobLog) -> None:
        """Save job log to disk.

        Args:
            job_log: Job log to save
        """
        log_path = self._get_log_path(job_log.job_id)

        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(
                    job_log.to_dict(),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )
        except Exception as e:
            raise RuntimeError(f"Failed to save job log {job_log.job_id}: {e}")

    def _load_log(self, job_id: str) -> JobLog:
        """Load job log from disk.

        Args:
            job_id: Job identifier

        Returns:
            JobLog instance

        Raises:
            RuntimeError: If loading fails
        """
        log_path = self._get_log_path(job_id)

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            job_log = JobLog.from_dict(data)
            self._active_jobs[job_id] = job_log
            return job_log
        except Exception as e:
            raise RuntimeError(f"Failed to load job log {job_id}: {e}")
