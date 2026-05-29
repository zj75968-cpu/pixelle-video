import asyncio


def test_test_profile_lifecycle_is_noop(monkeypatch):
    import api.lifecycle as lifecycle

    lifecycle.reset_lifecycle_state_for_tests()
    calls = []

    monkeypatch.setattr(lifecycle.task_manager, "start", lambda: calls.append("task_manager.start"))
    monkeypatch.setattr(lifecycle.task_manager, "stop", lambda: calls.append("task_manager.stop"))
    monkeypatch.setattr(lifecycle.device_manager, "start_auto_sync", lambda interval_seconds: calls.append("device_manager.start_auto_sync"))
    monkeypatch.setattr(lifecycle.device_manager, "stop_auto_sync", lambda: calls.append("device_manager.stop_auto_sync"))
    monkeypatch.setattr(lifecycle.publish_scheduler, "start_scheduler", lambda: calls.append("publish_scheduler.start_scheduler"))
    monkeypatch.setattr(lifecycle.publish_scheduler, "stop_scheduler", lambda: calls.append("publish_scheduler.stop_scheduler"))
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
