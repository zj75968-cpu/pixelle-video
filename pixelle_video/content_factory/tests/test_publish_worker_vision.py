from __future__ import annotations

from content_factory.domain.devices.service import DeviceProfileInput, DeviceService
from content_factory.workers.publish_worker import PublishWorker


def test_executor_gets_vision_when_camera_index_set(db_session):
    service = DeviceService(db_session)
    device = service.register_device(
        DeviceProfileInput(name="p1", platform="xhs", ch9329_port="COM3", camera_index=0)
    )
    db_session.flush()
    worker = PublishWorker(db_session, simulate=True)
    executor = worker._resolve_executor(device.id)
    assert executor.vision is not None
    # simulate=True -> vision present but not available (degrade-to-pass)
    assert executor.vision.available is False


def test_executor_no_vision_without_camera_index(db_session):
    service = DeviceService(db_session)
    device = service.register_device(DeviceProfileInput(name="p2", platform="xhs", ch9329_port="COM3"))
    db_session.flush()
    worker = PublishWorker(db_session, simulate=True)
    executor = worker._resolve_executor(device.id)
    assert executor.vision is None
