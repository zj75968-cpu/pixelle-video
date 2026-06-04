from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from content_factory.core.config import load_settings
from content_factory.domain.automation.ch9329.controller import CH9329Controller
from content_factory.domain.automation.ch9329.executor import CH9329Executor, StepResult
from content_factory.domain.devices.service import DeviceService
from content_factory.domain.errors.service import ErrorRecordService
from content_factory.domain.publish.models import (
    PublishJob,
    PublishJobLog,
    PublishPackage,
)

# Default simulated Xiaohongshu image-text draft flow. It mirrors the design's
# 11-step first-version upload path while remaining safe in dry-run mode.
DEFAULT_FLOW_STEPS = [
    {"type": "checkpoint", "note": "confirm phone is unlocked"},
    {"type": "open_app", "app": "xiaohongshu", "note": "open Xiaohongshu app"},
    {"type": "wait_for_element", "template": "xhs/home_publish_btn", "timeout": 10, "note": "wait for home loaded"},
    {"type": "tap", "x": 540, "y": 2250, "note": "enter publish entry"},
    {"type": "verify_screen", "template": "xhs/album_tab", "note": "confirm media picker"},
    {"type": "select_media", "source": "publish_package.media", "note": "select images/videos"},
    {"type": "input_text", "field": "title", "source": "publish_package.title", "note": "input title"},
    {"type": "input_text", "field": "body", "source": "publish_package.body", "note": "input body"},
    {"type": "input_text", "field": "tags", "source": "publish_package.hashtags", "note": "input tags"},
    {"type": "set_cover", "source": "publish_package.cover", "note": "set cover if needed"},
    {"type": "preview", "note": "check preview"},
    {"type": "verify_screen", "template": "xhs/publish_ready", "note": "confirm ready to save"},
    {"type": "tap", "x": 540, "y": 2300, "note": "save draft"},
    {"type": "checkpoint", "note": "record result"},
]


class PublishWorker:
    """Drive a publish package through the CH9329 executor and record a job."""

    def __init__(
        self,
        session: Session,
        executor: CH9329Executor | None = None,
        simulate: bool = True,
    ):
        self.session = session
        self.simulate = simulate
        self.executor = executor
        self.device_service = DeviceService(session)
        self.runtime_dir = load_settings().runtime_dir

    def run_job(
        self,
        publish_package_id: str,
        device_id: str | None = None,
        *,
        start_step: int = 0,
        end_step: int | None = None,
        existing_job: PublishJob | None = None,
    ) -> PublishJob:
        package = (
            self.session.query(PublishPackage)
            .filter(PublishPackage.id == publish_package_id)
            .first()
        )
        if package is None:
            raise ValueError("package_not_found")

        job = existing_job or PublishJob(
            publish_package_id=package.id,
            platform=package.platform,
            account_id=package.account_id,
            device_id=device_id,
            created_at=datetime.utcnow(),
        )
        if existing_job is None:
            self.session.add(job)
        job.status = "running"
        job.device_id = device_id
        job.started_at = datetime.utcnow()
        job.finished_at = None
        job.error_message = None
        job.resume_from_step = start_step if start_step else job.resume_from_step
        self.session.flush()

        steps = self._resolve_steps(device_id)
        context = {"publish_package": self._package_context(package)}
        executor = self._resolve_executor(device_id)
        results = executor.execute_flow(
            steps,
            context,
            start_step=start_step,
            end_step=end_step,
            stop_on_failure=True,
        )

        failed_result: StepResult | None = None
        for result in results:
            screenshot_path = self._write_step_snapshot(job, result)
            log = PublishJobLog(
                job_id=job.id,
                device_id=device_id,
                step_index=result.step_index,
                step_name=result.step_name,
                action_type=result.action_type,
                status=result.status,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                screenshot_path=screenshot_path,
                error_message=result.error_message,
            )
            self.session.add(log)
            if result.status == "failed" and failed_result is None:
                failed_result = result

        job.finished_at = datetime.utcnow()
        if failed_result is None:
            job.status = "succeeded"
            package.status = "draft_uploaded"
        else:
            job.status = "paused"
            job.resume_from_step = failed_result.step_index
            job.error_message = failed_result.error_message or "publish_step_failed"
            package.status = "publishing_paused"
            ErrorRecordService(self.session).record(
                topic_task_id=package.topic_task_id,
                related_id=job.id,
                stage="publish_execution",
                error_code="publish_step_failed",
                error_message=job.error_message,
                retryable=True,
                suggested_action=f"resume from step {failed_result.step_index} after manual check",
            )
        self.session.flush()
        return job

    def _resolve_steps(self, device_id: str | None) -> list[dict]:
        if device_id:
            profile = self.device_service.get_device_flow(device_id)
            if profile is not None and profile.get_steps():
                return profile.get_steps()
        return DEFAULT_FLOW_STEPS

    def _resolve_executor(self, device_id: str | None) -> CH9329Executor:
        if self.executor is not None:
            return self.executor

        from content_factory.domain.automation.vision.screen_vision import ScreenVision

        controller_kwargs: dict = {"simulate": self.simulate}
        vision: ScreenVision | None = None
        if device_id:
            device = self.device_service.get_device(device_id)
            if device is not None:
                controller_kwargs["port"] = device.ch9329_port
                controller_kwargs["phone_ip"] = getattr(device, "phone_ip", None)
                if device.screen_width:
                    controller_kwargs["screen_width"] = device.screen_width
                if device.screen_height:
                    controller_kwargs["screen_height"] = device.screen_height
                if device.camera_index is not None:
                    vision = ScreenVision(
                        camera_index=device.camera_index,
                        platform=device.platform,
                        simulate=self.simulate,
                    )

        controller = CH9329Controller(**controller_kwargs)
        return CH9329Executor(
            controller=controller,
            simulate=controller.simulate,
            phone_ip=controller.phone_ip,
            vision=vision,
        )

    def _package_context(self, package: PublishPackage) -> dict:
        hashtags = package.get_json("hashtags")
        return {
            "title": package.title or "",
            "body": package.body or "",
            "hashtags": " ".join(hashtags),
            "media": package.get_json("media_asset_ids"),
            "cover": package.cover_asset_id,
            "runtime_path": package.runtime_path,
        }

    def _write_step_snapshot(self, job: PublishJob, result: StepResult) -> str:
        path = self.runtime_dir / "screenshots" / f"{job.id}_step_{result.step_index:03d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            (
                f"job_id={job.id}\n"
                f"step_index={result.step_index}\n"
                f"step_name={result.step_name}\n"
                f"action_type={result.action_type}\n"
                f"status={result.status}\n"
                f"error={result.error_message or ''}\n"
            ),
            encoding="utf-8",
        )
        return str(path)
