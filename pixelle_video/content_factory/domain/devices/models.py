from __future__ import annotations

from datetime import datetime
import json
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text

from content_factory.core.database import Base


class DeviceProfile(Base):
    __tablename__ = "device_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(128), nullable=False)
    platform = Column(String(64), nullable=False, default="xhs")
    account_name = Column(String(128), nullable=True)
    ch9329_port = Column(String(64), nullable=True)
    phone_ip = Column(String(64), nullable=True)
    camera_index = Column(Integer, nullable=True)
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)
    app_version = Column(String(64), nullable=True)
    os_version = Column(String(64), nullable=True)
    coordinate_profile_id = Column(String(36), nullable=True)
    status = Column(String(32), nullable=False, default="idle")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CoordinateProfile(Base):
    __tablename__ = "coordinate_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String(36), nullable=True, index=True)
    platform = Column(String(64), nullable=False, default="xhs")
    app_version = Column(String(64), nullable=True)
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)
    flow_name = Column(String(128), nullable=False)
    steps = Column(Text, nullable=False, default="[]")
    yaml_path = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def set_steps(self, steps: list) -> None:
        self.steps = json.dumps(steps, ensure_ascii=False)

    def get_steps(self) -> list:
        return json.loads(self.steps) if self.steps else []
