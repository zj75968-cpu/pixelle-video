from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session
import yaml

from content_factory.core.config import load_settings
from content_factory.domain.devices.models import CoordinateProfile, DeviceProfile


@dataclass
class DeviceProfileInput:
    name: str
    platform: str = "xhs"
    account_name: str | None = None
    ch9329_port: str | None = None
    phone_ip: str | None = None
    camera_index: int | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    app_version: str | None = None
    os_version: str | None = None


@dataclass
class CoordinateProfileInput:
    flow_name: str
    platform: str = "xhs"
    device_id: str | None = None
    app_version: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    steps: list = field(default_factory=list)


class DeviceService:
    def __init__(self, session: Session):
        self.session = session
        self.runtime_dir = load_settings().runtime_dir

    # ----------------------------------------------------------- device profile
    def register_device(self, payload: DeviceProfileInput) -> DeviceProfile:
        device = DeviceProfile(
            name=payload.name,
            platform=payload.platform,
            account_name=payload.account_name,
            ch9329_port=payload.ch9329_port,
            phone_ip=payload.phone_ip,
            camera_index=payload.camera_index,
            screen_width=payload.screen_width,
            screen_height=payload.screen_height,
            app_version=payload.app_version,
            os_version=payload.os_version,
        )
        self.session.add(device)
        self.session.flush()
        return device

    def list_devices(self) -> list[DeviceProfile]:
        return (
            self.session.query(DeviceProfile)
            .order_by(DeviceProfile.created_at.asc())
            .all()
        )

    def get_device(self, device_id: str) -> DeviceProfile | None:
        return self.session.query(DeviceProfile).filter(DeviceProfile.id == device_id).first()

    # ------------------------------------------------------- coordinate profile
    def add_coordinate_profile(self, payload: CoordinateProfileInput) -> CoordinateProfile:
        profile = CoordinateProfile(
            device_id=payload.device_id,
            platform=payload.platform,
            app_version=payload.app_version,
            screen_width=payload.screen_width,
            screen_height=payload.screen_height,
            flow_name=payload.flow_name,
        )
        profile.set_steps(
            self._normalize_steps(payload.steps, payload.screen_width, payload.screen_height)
        )
        self.session.add(profile)
        self.session.flush()
        profile.yaml_path = str(self._write_coordinate_yaml(profile))
        self.session.flush()

        # Link the coordinate profile back to the device when provided.
        if payload.device_id:
            device = self.get_device(payload.device_id)
            if device is not None:
                device.coordinate_profile_id = profile.id
                self.session.flush()
        return profile

    def get_coordinate_profile(self, profile_id: str) -> CoordinateProfile | None:
        return (
            self.session.query(CoordinateProfile)
            .filter(CoordinateProfile.id == profile_id)
            .first()
        )

    def list_coordinate_profiles(
        self, device_id: str | None = None, platform: str | None = None
    ) -> list[CoordinateProfile]:
        query = self.session.query(CoordinateProfile)
        if device_id:
            query = query.filter(CoordinateProfile.device_id == device_id)
        if platform:
            query = query.filter(CoordinateProfile.platform == platform)
        return query.order_by(CoordinateProfile.created_at.desc()).all()

    def get_device_flow(self, device_id: str) -> CoordinateProfile | None:
        device = self.get_device(device_id)
        if device is None or not device.coordinate_profile_id:
            return None
        return self.get_coordinate_profile(device.coordinate_profile_id)

    @staticmethod
    def _normalize_steps(
        steps: list,
        screen_width: int | None,
        screen_height: int | None,
    ) -> list:
        normalized = []
        for step in steps:
            item = dict(step)
            if screen_width and item.get("x") is not None:
                item.setdefault("x_ratio", round(float(item["x"]) / screen_width, 6))
            if screen_height and item.get("y") is not None:
                item.setdefault("y_ratio", round(float(item["y"]) / screen_height, 6))
            normalized.append(item)
        return normalized

    def _write_coordinate_yaml(self, profile: CoordinateProfile) -> Path:
        path = self.runtime_dir / "coordinate_profiles" / f"{profile.id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": profile.id,
            "device_id": profile.device_id,
            "platform": profile.platform,
            "flow_name": profile.flow_name,
            "screen": {
                "width": profile.screen_width,
                "height": profile.screen_height,
            },
            "app_version": profile.app_version,
            "steps": profile.get_steps(),
        }
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path
