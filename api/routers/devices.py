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
Device management endpoints.
"""

from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from api.schemas.devices import (
    DeviceAddRequest,
    DeviceConnectWiFiRequest,
    DeviceListResponse,
    DeviceResponse,
)
from pixelle_video.services.device_manager import device_manager

router = APIRouter(prefix="/devices", tags=["Device Management"])


def _device_to_response(dev) -> DeviceResponse:
    return DeviceResponse(
        serial=dev.serial,
        name=dev.name,
        theme=dev.theme,
        notes=dev.notes,
        connected=dev.connected,
        last_seen=dev.last_seen,
        added_at=dev.added_at,
    )


@router.get("", response_model=DeviceListResponse)
async def list_devices():
    """List all registered devices and their live connection status."""
    devices = device_manager.get_all()
    return DeviceListResponse(
        devices=[_device_to_response(d) for d in devices],
        total=len(devices),
        adb_available=device_manager.check_adb_available(),
    )


@router.post("", response_model=DeviceResponse, status_code=201)
async def add_device(body: DeviceAddRequest):
    """Register a new device or update an existing one."""
    dev = device_manager.add_device(
        serial=body.serial,
        name=body.name,
        theme=body.theme,
        notes=body.notes,
    )
    return _device_to_response(dev)


@router.delete("/{serial}", status_code=204)
async def remove_device(serial: str):
    """Remove a device from the registry."""
    removed = device_manager.remove_device(serial)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Device {serial} not found")
    return Response(status_code=204)


@router.post("/connect-wifi", response_model=DeviceResponse)
async def connect_wifi(body: DeviceConnectWiFiRequest):
    """Connect to an Android device over WiFi via ADB."""
    serial = f"{body.host}:{body.port}"
    success = device_manager.connect_wifi(body.host, body.port)
    if not success:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to {serial}. Make sure ADB TCP/IP mode is enabled on the device.",
        )
    # Auto-register if not already in registry
    dev = device_manager.get(serial) or device_manager.add_device(serial=serial)
    device_manager.sync_connected()
    return _device_to_response(device_manager.get(serial))


@router.get("/diagnose/status")
async def diagnose_adb():
    """Diagnose ADB and connected devices (for debugging)."""
    adb_available = device_manager.check_adb_available()
    live_serials = device_manager.list_connected_serials() if adb_available else []
    registered_devices = device_manager.get_all()

    return {
        "adb_available": adb_available,
        "adb_command": device_manager.get_adb_command(),
        "live_connected_serials": live_serials,
        "registered_devices": [
            {
                "serial": d.serial,
                "name": d.name,
                "connected": d.connected,
                "last_seen": d.last_seen,
            }
            for d in registered_devices
        ],
        "sync_active": device_manager._auto_sync_thread is not None and device_manager._auto_sync_thread.is_alive(),
    }


@router.get("/{serial}/screenshot")
async def get_screenshot(serial: str):
    """Capture a screenshot from the device and return it as PNG."""
    dev = device_manager.get(serial)
    if not dev:
        raise HTTPException(status_code=404, detail=f"Device {serial} not found")
    data = device_manager.screenshot(serial)
    if data is None:
        raise HTTPException(status_code=502, detail="Failed to capture screenshot")
    return Response(content=data, media_type="image/png")
