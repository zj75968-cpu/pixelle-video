"""Example usage of JobLogger for device farm execution tracking."""

from pixelle_video.device_farm.runtime.job_logger import (
    JobLogger,
    JobStatus,
    StepResult
)
from datetime import datetime
import time


def example_successful_job():
    """Example of logging a successful job execution."""
    logger = JobLogger()

    # Create job log
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    job_log = logger.create_job_log(
        job_id=job_id,
        phone_id="phone_001",
        flow_id="xhs_publish_flow",
        metadata={
            "task_id": "task_123",
            "user": "automation_agent"
        }
    )
    print(f"Created job: {job_id}")

    # Start job
    logger.start_job(job_id)
    print(f"Started job: {job_id}")

    # Log steps
    start_time = time.time()

    logger.log_step(
        job_id=job_id,
        step_id="open_app",
        result=StepResult.SUCCESS,
        duration_ms=1200,
        screenshot_after="logs/jobs/screenshots/open_app.png",
        metadata={"app": "xiaohongshu"}
    )
    print("Logged step: open_app")

    logger.log_step(
        job_id=job_id,
        step_id="navigate_to_publish",
        result=StepResult.SUCCESS,
        duration_ms=800,
        screenshot_before="logs/jobs/screenshots/before_nav.png",
        screenshot_after="logs/jobs/screenshots/after_nav.png"
    )
    print("Logged step: navigate_to_publish")

    logger.log_step(
        job_id=job_id,
        step_id="upload_images",
        result=StepResult.SUCCESS,
        duration_ms=3500,
        metadata={"image_count": 3}
    )
    print("Logged step: upload_images")

    logger.log_step(
        job_id=job_id,
        step_id="fill_content",
        result=StepResult.SUCCESS,
        duration_ms=1500,
        metadata={"title": "Test Post", "body_length": 150}
    )
    print("Logged step: fill_content")

    logger.log_step(
        job_id=job_id,
        step_id="submit_post",
        result=StepResult.SUCCESS,
        duration_ms=2000,
        screenshot_after="logs/jobs/screenshots/submit_success.png"
    )
    print("Logged step: submit_post")

    # Complete job
    logger.complete_job(job_id)
    print(f"Completed job: {job_id}")

    return job_id


def example_failed_job():
    """Example of logging a failed job execution."""
    logger = JobLogger()

    # Create and start job
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_fail"
    logger.create_job_log(
        job_id=job_id,
        phone_id="phone_002",
        flow_id="xhs_publish_flow"
    )
    logger.start_job(job_id)
    print(f"Started job: {job_id}")

    # Log successful steps
    logger.log_step(
        job_id=job_id,
        step_id="open_app",
        result=StepResult.SUCCESS,
        duration_ms=1100
    )

    logger.log_step(
        job_id=job_id,
        step_id="navigate_to_publish",
        result=StepResult.SUCCESS,
        duration_ms=750
    )

    # Log failed step
    logger.log_step(
        job_id=job_id,
        step_id="upload_images",
        result=StepResult.FAILED,
        duration_ms=500,
        error="Image file not found: /path/to/image.png",
        screenshot_after="logs/jobs/screenshots/upload_error.png"
    )
    print("Logged failed step: upload_images")

    # Save failure
    logger.save_failure(
        job_id=job_id,
        error="Image file not found: /path/to/image.png",
        failed_step="upload_images",
        screenshot="logs/jobs/screenshots/failure_state.png"
    )
    print(f"Saved failure for job: {job_id}")

    return job_id


def example_query_logs():
    """Example of querying job logs."""
    logger = JobLogger()

    # List all jobs
    all_jobs = logger.list_job_logs(limit=10)
    print(f"\nTotal jobs: {len(all_jobs)}")

    # List failed jobs
    failed_jobs = logger.list_job_logs(status=JobStatus.FAILED, limit=5)
    print(f"Failed jobs: {len(failed_jobs)}")

    # List jobs for specific phone
    phone_jobs = logger.list_job_logs(phone_id="phone_001", limit=5)
    print(f"Jobs for phone_001: {len(phone_jobs)}")

    # Get specific job
    if all_jobs:
        job_id = all_jobs[0].job_id
        job_log = logger.get_job_log(job_id)
        print(f"\nJob details for {job_id}:")
        print(f"  Status: {job_log.status.value}")
        print(f"  Phone: {job_log.phone_id}")
        print(f"  Flow: {job_log.flow_id}")
        print(f"  Steps: {len(job_log.action_log)}")
        print(f"  Screenshots: {len(job_log.screenshots)}")

        if job_log.action_log:
            print(f"\n  Step log:")
            for step in job_log.action_log:
                print(f"    - {step.step_id}: {step.result.value} ({step.duration_ms}ms)")


if __name__ == "__main__":
    print("=== Example 1: Successful Job ===")
    success_job_id = example_successful_job()

    print("\n=== Example 2: Failed Job ===")
    failed_job_id = example_failed_job()

    print("\n=== Example 3: Query Logs ===")
    example_query_logs()

    print("\n=== Log Files ===")
    print(f"Logs saved to: logs/jobs/")
    print(f"  - {success_job_id}.yaml")
    print(f"  - {failed_job_id}.yaml")
