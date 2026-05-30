from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from loguru import logger


task_manager: Any | None = None
device_manager: Any | None = None
publish_scheduler: Any | None = None
start_cookie_keepalive: Callable[..., Any] | None = None
stop_cookie_keepalive: Callable[..., Any] | None = None
shutdown_pixelle_video: Callable[..., Any] | None = None


class RunProfile(StrEnum):
    API_SERVER = "api_server"
    LOCAL_UI = "local_ui"
    WORKER = "worker"
    CLI = "cli"
    DEV = "dev"
    TEST = "test"

    @classmethod
    def coerce(cls, value: RunProfile | str) -> RunProfile:
        if isinstance(value, cls):
            return value
        return cls(str(value).lower())


@dataclass(frozen=True)
class LifecycleState:
    profile: RunProfile | None
    started: bool


_started_profile: RunProfile | None = None


def _task_manager() -> Any:
    if task_manager is not None:
        return task_manager
    from api.tasks import task_manager as imported_task_manager

    return imported_task_manager


def _device_manager() -> Any:
    if device_manager is not None:
        return device_manager
    from pixelle_video.services.device_manager import device_manager as imported_device_manager

    return imported_device_manager


def _publish_scheduler() -> Any:
    if publish_scheduler is not None:
        return publish_scheduler
    from pixelle_video.services.publish_scheduler import publish_scheduler as imported_publish_scheduler

    return imported_publish_scheduler


def _start_cookie_keepalive() -> Callable[..., Any]:
    if start_cookie_keepalive is not None:
        return start_cookie_keepalive
    from pixelle_video.services.smart_scraper import start_cookie_keepalive as imported_start_cookie_keepalive

    return imported_start_cookie_keepalive


def _stop_cookie_keepalive() -> Callable[..., Any]:
    if stop_cookie_keepalive is not None:
        return stop_cookie_keepalive
    from pixelle_video.services.smart_scraper import stop_cookie_keepalive as imported_stop_cookie_keepalive

    return imported_stop_cookie_keepalive


def _shutdown_pixelle_video() -> Callable[..., Any]:
    if shutdown_pixelle_video is not None:
        return shutdown_pixelle_video
    from api.dependencies import shutdown_pixelle_video as imported_shutdown_pixelle_video

    return imported_shutdown_pixelle_video


def reset_lifecycle_state_for_tests() -> None:
    global _started_profile
    _started_profile = None


def _profile_owns_background_services(profile: RunProfile | str) -> bool:
    coerced = RunProfile.coerce(profile)
    return coerced in {RunProfile.API_SERVER, RunProfile.WORKER, RunProfile.LOCAL_UI}


async def start_app_lifecycle(profile: RunProfile | str = RunProfile.API_SERVER) -> LifecycleState:
    global _started_profile

    coerced = RunProfile.coerce(profile)
    if coerced is RunProfile.TEST or not _profile_owns_background_services(coerced):
        return LifecycleState(profile=coerced, started=False)

    if _started_profile is not None:
        return LifecycleState(profile=_started_profile, started=True)

    _started_profile = coerced
    task_manager_service = _task_manager()
    device_manager_service = _device_manager()
    publish_scheduler_service = _publish_scheduler()

    await task_manager_service.start()
    device_manager_service.start_auto_sync(interval_seconds=8)
    if hasattr(publish_scheduler_service, "start_background_polling"):
        publish_scheduler_service.start_background_polling()
    publish_scheduler_service.start_scheduler()
    _start_cookie_keepalive()(interval_hours=12.0)
    return LifecycleState(profile=coerced, started=True)


async def stop_app_lifecycle(profile: RunProfile | str = RunProfile.API_SERVER) -> LifecycleState:
    global _started_profile

    coerced = RunProfile.coerce(profile)
    if coerced is RunProfile.TEST or _started_profile is None:
        return LifecycleState(profile=coerced, started=False)

    active_profile = _started_profile
    try:
        try:
            _stop_cookie_keepalive()()
        except Exception as exc:
            logger.warning(f"Failed to stop cookie keepalive: {exc}")

        device_manager_service = _device_manager()
        publish_scheduler_service = _publish_scheduler()
        task_manager_service = _task_manager()

        device_manager_service.stop_auto_sync()
        publish_scheduler_service.stop_scheduler()
        if hasattr(publish_scheduler_service, "stop_background_polling"):
            publish_scheduler_service.stop_background_polling()
        await task_manager_service.stop()
        await _shutdown_pixelle_video()()
    finally:
        _started_profile = None
    return LifecycleState(profile=active_profile, started=False)
