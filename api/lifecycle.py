from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from api.dependencies import shutdown_pixelle_video
from api.tasks import task_manager
from pixelle_video.services.device_manager import device_manager
from pixelle_video.services.publish_scheduler import publish_scheduler
from pixelle_video.services.smart_scraper import start_cookie_keepalive, stop_cookie_keepalive


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

    await task_manager.start()
    device_manager.start_auto_sync(interval_seconds=8)
    if hasattr(publish_scheduler, "start_background_polling"):
        publish_scheduler.start_background_polling()
    publish_scheduler.start_scheduler()
    start_cookie_keepalive(interval_hours=12.0)
    _started_profile = coerced
    return LifecycleState(profile=coerced, started=True)


async def stop_app_lifecycle(profile: RunProfile | str = RunProfile.API_SERVER) -> LifecycleState:
    global _started_profile

    coerced = RunProfile.coerce(profile)
    if coerced is RunProfile.TEST or _started_profile is None:
        return LifecycleState(profile=coerced, started=False)

    active_profile = _started_profile
    try:
        stop_cookie_keepalive()
    except Exception as exc:
        logger.warning(f"Failed to stop cookie keepalive: {exc}")

    device_manager.stop_auto_sync()
    publish_scheduler.stop_scheduler()
    if hasattr(publish_scheduler, "stop_background_polling"):
        publish_scheduler.stop_background_polling()
    await task_manager.stop()
    await shutdown_pixelle_video()
    _started_profile = None
    return LifecycleState(profile=active_profile, started=False)
