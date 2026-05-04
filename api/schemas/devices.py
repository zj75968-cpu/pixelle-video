# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
API schemas for device management.
"""

from typing import Optional
from pydantic import BaseModel, Field


class DeviceAddRequest(BaseModel):
    serial: str = Field(..., description="ADB device serial (e.g. emulator-5554 or 192.168.1.10:5555)")
    name: str = Field(default="", description="Friendly name for the device")
    theme: str = Field(default="", description="Content theme assigned to this device (e.g. 旅行, 美食)")
    notes: str = Field(default="", description="Optional notes")


class DeviceConnectWiFiRequest(BaseModel):
    host: str = Field(..., description="Device IP address")
    port: int = Field(default=5555, description="ADB TCP port")


class DeviceResponse(BaseModel):
    serial: str
    name: str
    theme: str
    notes: str
    connected: bool
    last_seen: Optional[str]
    added_at: str


class DeviceListResponse(BaseModel):
    devices: list[DeviceResponse]
    total: int
    adb_available: bool
