import asyncio
import importlib
import sys
from datetime import datetime, timedelta


def test_publish_scheduler_constructor_does_not_start_schedule_poll(monkeypatch):
    scheduler_module = importlib.import_module("pixelle_video.services.publish_scheduler")

    calls = []

    class FakeDataDir:
        def mkdir(self, *args, **kwargs):
            calls.append("DATA_DIR.mkdir")

    monkeypatch.setattr(scheduler_module, "DATA_DIR", FakeDataDir())
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_load", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_recover_orphaned_running_jobs", lambda self: None)
    monkeypatch.setattr(
        scheduler_module.PublishScheduler,
        "_start_schedule_poll",
        lambda self: calls.append("_start_schedule_poll") or True,
    )

    scheduler_module.PublishScheduler()

    assert calls == ["DATA_DIR.mkdir"]


def test_publish_scheduler_background_polling_methods_are_idempotent(monkeypatch):
    scheduler_module = importlib.import_module("pixelle_video.services.publish_scheduler")

    calls = []

    class FakeDataDir:
        def mkdir(self, *args, **kwargs):
            calls.append("DATA_DIR.mkdir")

    monkeypatch.setattr(scheduler_module, "DATA_DIR", FakeDataDir())
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_load", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_recover_orphaned_running_jobs", lambda self: None)
    monkeypatch.setattr(
        scheduler_module.PublishScheduler,
        "_start_schedule_poll",
        lambda self: calls.append("_start_schedule_poll") or True,
    )

    scheduler = scheduler_module.PublishScheduler()
    scheduler._sched_poll_stop_event = type(
        "FakeStopEvent",
        (),
        {"set": lambda self: calls.append("stop_event.set")},
    )()

    scheduler.start_background_polling()
    scheduler.start_background_polling()
    scheduler.stop_background_polling()
    scheduler.stop_background_polling()

    assert calls == ["DATA_DIR.mkdir", "_start_schedule_poll", "stop_event.set"]


def test_publish_scheduler_rapid_stop_start_does_not_mark_stopping_thread_started(monkeypatch):
    scheduler_module = importlib.import_module("pixelle_video.services.publish_scheduler")

    calls = []

    class FakeDataDir:
        def mkdir(self, *args, **kwargs):
            calls.append("DATA_DIR.mkdir")

    class FakeStopEvent:
        def __init__(self):
            self._set = False

        def set(self):
            calls.append("stop_event.set")
            self._set = True

        def is_set(self):
            return self._set

    class FakeThread:
        def __init__(self):
            self.joined = False

        def is_alive(self):
            return not self.joined

        def join(self, timeout=None):
            calls.append(("thread.join", timeout))

    monkeypatch.setattr(scheduler_module, "DATA_DIR", FakeDataDir())
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_load", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_recover_orphaned_running_jobs", lambda self: None)

    scheduler = scheduler_module.PublishScheduler()
    scheduler._background_polling_started = True
    scheduler._sched_poll_stop_event = FakeStopEvent()
    scheduler._sched_poll_thread = FakeThread()

    scheduler.stop_background_polling()
    scheduler.start_background_polling()

    assert scheduler._background_polling_started is False
    assert calls == ["DATA_DIR.mkdir", "stop_event.set", ("thread.join", 0.2)]


def test_publish_scheduler_standalone_scheduled_job_starts_background_polling(monkeypatch):
    scheduler_module = importlib.import_module("pixelle_video.services.publish_scheduler")

    calls = []

    class FakeDataDir:
        def mkdir(self, *args, **kwargs):
            calls.append("DATA_DIR.mkdir")

    monkeypatch.setattr(scheduler_module, "DATA_DIR", FakeDataDir())
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_load", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_recover_orphaned_running_jobs", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_save", lambda self: calls.append("_save"))
    monkeypatch.setattr(
        scheduler_module.PublishScheduler,
        "start_background_polling",
        lambda self: calls.append("start_background_polling"),
    )

    scheduler = scheduler_module.PublishScheduler()
    scheduled_at = (datetime.now() + timedelta(minutes=5)).isoformat()

    job = scheduler.add_job(
        serial="device-1",
        task_id="task-1",
        title="title",
        body="body",
        hashtags=[],
        images=[],
        scheduled_at=scheduled_at,
    )

    assert job.status == scheduler_module.JobStatus.SCHEDULED
    assert calls == ["DATA_DIR.mkdir", "_save", "_save", "start_background_polling"]

def test_publish_scheduler_start_scheduler_is_idempotent(monkeypatch):
    scheduler_module = importlib.import_module("pixelle_video.services.publish_scheduler")

    calls = []

    class FakeDataDir:
        def mkdir(self, *args, **kwargs):
            calls.append("DATA_DIR.mkdir")

    class FakeAsyncIOScheduler:
        def __init__(self, timezone):
            calls.append(("AsyncIOScheduler", timezone))
            self.running = False

        def start(self):
            calls.append("scheduler.start")
            self.running = True

        def add_job(self, *args, **kwargs):
            calls.append("scheduler.add_job")

    monkeypatch.setattr(scheduler_module, "DATA_DIR", FakeDataDir())
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_load", lambda self: None)
    monkeypatch.setattr(scheduler_module.PublishScheduler, "_recover_orphaned_running_jobs", lambda self: None)

    scheduler = scheduler_module.PublishScheduler()
    monkeypatch.setitem(
        sys.modules,
        "apscheduler.schedulers.asyncio",
        type("FakeApschedulerAsyncioModule", (), {"AsyncIOScheduler": FakeAsyncIOScheduler}),
    )

    scheduler.start_scheduler()
    scheduler.start_scheduler()

    assert calls == [
        "DATA_DIR.mkdir",
        ("AsyncIOScheduler", "Asia/Shanghai"),
        "scheduler.start",
        "scheduler.add_job",
    ]


def test_test_profile_lifecycle_is_noop(monkeypatch):
    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append("device_manager.start_auto_sync")

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")

    class FakePublishScheduler:
        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append("start_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", lambda: calls.append("stop_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", lambda: calls.append("shutdown_pixelle_video"))

    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.TEST))
    asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.TEST))

    assert calls == []


def test_api_server_lifecycle_delegates_in_existing_order(monkeypatch):
    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append(("device_manager.start_auto_sync", interval_seconds))

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")

    class FakePublishScheduler:
        def start_background_polling(self):
            calls.append("publish_scheduler.start_background_polling")

        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")

        def stop_background_polling(self):
            calls.append("publish_scheduler.stop_background_polling")

    async def fake_shutdown_pixelle_video():
        calls.append("shutdown_pixelle_video")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append(("start_cookie_keepalive", interval_hours)))
    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", lambda: calls.append("stop_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", fake_shutdown_pixelle_video)

    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    assert calls == [
        "task_manager.start",
        ("device_manager.start_auto_sync", 8),
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        ("start_cookie_keepalive", 12.0),
        "stop_cookie_keepalive",
        "device_manager.stop_auto_sync",
        "publish_scheduler.stop_scheduler",
        "publish_scheduler.stop_background_polling",
        "task_manager.stop",
        "shutdown_pixelle_video",
    ]


def test_lifecycle_start_stop_are_idempotent(monkeypatch):
    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append("device_manager.start_auto_sync")

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")

    class FakePublishScheduler:
        def start_background_polling(self):
            calls.append("publish_scheduler.start_background_polling")

        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")

        def stop_background_polling(self):
            calls.append("publish_scheduler.stop_background_polling")

    async def fake_shutdown_pixelle_video():
        calls.append("shutdown_pixelle_video")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append("start_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", lambda: calls.append("stop_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", fake_shutdown_pixelle_video)

    asyncio.run(lifecycle.start_app_lifecycle("api_server"))
    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    asyncio.run(lifecycle.stop_app_lifecycle("api_server"))
    asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    assert calls == [
        "task_manager.start",
        "device_manager.start_auto_sync",
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        "start_cookie_keepalive",
        "stop_cookie_keepalive",
        "device_manager.stop_auto_sync",
        "publish_scheduler.stop_scheduler",
        "publish_scheduler.stop_background_polling",
        "task_manager.stop",
        "shutdown_pixelle_video",
    ]


def test_partial_startup_failure_is_tracked_for_cleanup_and_restart_idempotency(monkeypatch):
    import pytest

    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append(("device_manager.start_auto_sync", interval_seconds))

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")

    class FakePublishScheduler:
        def start_background_polling(self):
            calls.append("publish_scheduler.start_background_polling")

        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")
            raise RuntimeError("scheduler failed")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")

        def stop_background_polling(self):
            calls.append("publish_scheduler.stop_background_polling")

    async def fake_shutdown_pixelle_video():
        calls.append("shutdown_pixelle_video")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append(("start_cookie_keepalive", interval_hours)))
    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", lambda: calls.append("stop_cookie_keepalive"))
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", fake_shutdown_pixelle_video)

    with pytest.raises(RuntimeError, match="scheduler failed"):
        asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    repeated_start_state = asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    stopped_state = asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    assert repeated_start_state == lifecycle.LifecycleState(profile=lifecycle.RunProfile.API_SERVER, started=True)
    assert stopped_state == lifecycle.LifecycleState(profile=lifecycle.RunProfile.API_SERVER, started=False)
    assert calls == [
        "task_manager.start",
        ("device_manager.start_auto_sync", 8),
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        "stop_cookie_keepalive",
        "device_manager.stop_auto_sync",
        "publish_scheduler.stop_scheduler",
        "publish_scheduler.stop_background_polling",
        "task_manager.stop",
        "shutdown_pixelle_video",
    ]


def test_lifecycle_import_keeps_heavy_services_lazy(monkeypatch):
    sys.modules.pop("api.lifecycle", None)
    sys.modules.pop("pixelle_video.services.publish_scheduler", None)
    sys.modules.pop("pixelle_video.services.device_manager", None)

    lifecycle = importlib.import_module("api.lifecycle")

    assert "pixelle_video.services.publish_scheduler" not in sys.modules
    assert "pixelle_video.services.device_manager" not in sys.modules
    assert lifecycle.task_manager is None
    assert lifecycle.device_manager is None
    assert lifecycle.publish_scheduler is None


def test_cleanup_failure_attempts_all_steps_then_raises_first_error(monkeypatch):
    import pytest

    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")
            raise RuntimeError("task cleanup failed")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append(("device_manager.start_auto_sync", interval_seconds))

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")
            raise RuntimeError("device cleanup failed")

    class FakePublishScheduler:
        def start_background_polling(self):
            calls.append("publish_scheduler.start_background_polling")

        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")
            raise RuntimeError("scheduler cleanup failed")

        def stop_background_polling(self):
            calls.append("publish_scheduler.stop_background_polling")

    async def fake_shutdown_pixelle_video():
        calls.append("shutdown_pixelle_video")
        raise RuntimeError("pixelle cleanup failed")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append(("start_cookie_keepalive", interval_hours)))

    def fail_cookie_stop():
        calls.append("stop_cookie_keepalive")
        raise RuntimeError("cookie cleanup failed")

    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", fail_cookie_stop)
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", fake_shutdown_pixelle_video)

    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    with pytest.raises(RuntimeError, match="cookie cleanup failed"):
        asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    assert calls == [
        "task_manager.start",
        ("device_manager.start_auto_sync", 8),
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        ("start_cookie_keepalive", 12.0),
        "stop_cookie_keepalive",
        "device_manager.stop_auto_sync",
        "publish_scheduler.stop_scheduler",
        "publish_scheduler.stop_background_polling",
        "task_manager.stop",
        "shutdown_pixelle_video",
        "task_manager.start",
        ("device_manager.start_auto_sync", 8),
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        ("start_cookie_keepalive", 12.0),
    ]


def test_cookie_cleanup_failure_attempts_later_steps_then_raises_cookie_error(monkeypatch):
    import pytest

    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    class FakeTaskManager:
        async def start(self):
            calls.append("task_manager.start")

        async def stop(self):
            calls.append("task_manager.stop")

    class FakeDeviceManager:
        def start_auto_sync(self, interval_seconds):
            calls.append(("device_manager.start_auto_sync", interval_seconds))

        def stop_auto_sync(self):
            calls.append("device_manager.stop_auto_sync")

    class FakePublishScheduler:
        def start_background_polling(self):
            calls.append("publish_scheduler.start_background_polling")

        def start_scheduler(self):
            calls.append("publish_scheduler.start_scheduler")

        def stop_scheduler(self):
            calls.append("publish_scheduler.stop_scheduler")

        def stop_background_polling(self):
            calls.append("publish_scheduler.stop_background_polling")

    async def fake_shutdown_pixelle_video():
        calls.append("shutdown_pixelle_video")

    def fail_cookie_stop():
        calls.append("stop_cookie_keepalive")
        raise RuntimeError("cookie cleanup failed")

    monkeypatch.setattr(lifecycle, "task_manager", FakeTaskManager())
    monkeypatch.setattr(lifecycle, "device_manager", FakeDeviceManager())
    monkeypatch.setattr(lifecycle, "publish_scheduler", FakePublishScheduler())
    monkeypatch.setattr(lifecycle, "start_cookie_keepalive", lambda interval_hours: calls.append(("start_cookie_keepalive", interval_hours)))
    monkeypatch.setattr(lifecycle, "stop_cookie_keepalive", fail_cookie_stop)
    monkeypatch.setattr(lifecycle, "shutdown_pixelle_video", fake_shutdown_pixelle_video)

    asyncio.run(lifecycle.start_app_lifecycle(lifecycle.RunProfile.API_SERVER))
    with pytest.raises(RuntimeError, match="cookie cleanup failed"):
        asyncio.run(lifecycle.stop_app_lifecycle(lifecycle.RunProfile.API_SERVER))

    assert calls == [
        "task_manager.start",
        ("device_manager.start_auto_sync", 8),
        "publish_scheduler.start_background_polling",
        "publish_scheduler.start_scheduler",
        ("start_cookie_keepalive", 12.0),
        "stop_cookie_keepalive",
        "device_manager.stop_auto_sync",
        "publish_scheduler.stop_scheduler",
        "publish_scheduler.stop_background_polling",
        "task_manager.stop",
        "shutdown_pixelle_video",
    ]
