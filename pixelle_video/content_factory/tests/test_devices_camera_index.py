from __future__ import annotations

from content_factory.domain.devices.service import DeviceProfileInput, DeviceService


def test_register_device_persists_camera_index(db_session):
    service = DeviceService(db_session)
    device = service.register_device(
        DeviceProfileInput(name="phone-01", platform="xhs", ch9329_port="COM3", camera_index=2)
    )
    db_session.flush()
    fetched = service.get_device(device.id)
    assert fetched is not None
    assert fetched.camera_index == 2


def test_camera_index_defaults_none(db_session):
    service = DeviceService(db_session)
    device = service.register_device(DeviceProfileInput(name="phone-02"))
    assert device.camera_index is None
