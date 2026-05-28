# -*- coding: utf-8 -*-
# Copyright (C) 2025 AIDC-AI
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""
Device management endpoints (重构为 CH9329 硬件直控模式).
"""

from fastapi import APIRouter, HTTPException, Response

from api.schemas.devices import (
    DeviceAddRequest,
    DeviceConnectWiFiRequest,
    DeviceListResponse,
    DeviceResponse,
)
from pixelle_video.services.device_manager import device_manager
from pixelle_video.config import config_manager

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
        adb_available=False,
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
    """Connect WiFi is not supported in hardware mode."""
    raise HTTPException(
        status_code=501,
        detail="WiFi ADB connection is not supported in CH9329 hardware control mode."
    )


@router.get("/diagnose/status")
async def diagnose_adb():
    """Diagnose serial status."""
    com_port = "COM3"
    try:
        com_port = config_manager.config.xhs_publish.hardware.com_port
    except Exception:
        pass

    return {
        "adb_available": False,
        "hardware_mode": True,
        "com_port": com_port,
        "registered_devices": [
            {
                "serial": d.serial,
                "name": d.name,
                "connected": d.connected,
                "last_seen": d.last_seen,
            }
            for d in device_manager.get_all()
        ],
        "sync_active": False,
    }


@router.get("/{serial}/screenshot")
async def get_screenshot(serial: str):
    """Screenshot is not supported in hardware mode."""
    raise HTTPException(
        status_code=501,
        detail="Screenshots are not supported in CH9329 hardware control mode."
    )
