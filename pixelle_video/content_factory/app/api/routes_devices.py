from __future__ import annotations

from fastapi import APIRouter, HTTPException
import yaml

from content_factory.app.api.schemas import (
    CoordinateProfileCreateRequest,
    CoordinateProfileResponse,
    CoordinateProfileYamlRequest,
    DeviceProfileResponse,
    DeviceRegisterRequest,
)
from content_factory.core.database import session_scope
from content_factory.domain.devices.models import CoordinateProfile, DeviceProfile
from content_factory.domain.devices.service import (
    CoordinateProfileInput,
    DeviceProfileInput,
    DeviceService,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])


def device_to_response(device: DeviceProfile) -> DeviceProfileResponse:
    return DeviceProfileResponse(
        id=device.id,
        name=device.name,
        platform=device.platform,
        account_name=device.account_name,
        ch9329_port=device.ch9329_port,
        phone_ip=device.phone_ip,
        camera_index=device.camera_index,
        screen_width=device.screen_width,
        screen_height=device.screen_height,
        app_version=device.app_version,
        os_version=device.os_version,
        coordinate_profile_id=device.coordinate_profile_id,
        status=device.status,
        created_at=device.created_at,
    )


def coordinate_to_response(profile: CoordinateProfile) -> CoordinateProfileResponse:
    return CoordinateProfileResponse(
        id=profile.id,
        device_id=profile.device_id,
        platform=profile.platform,
        app_version=profile.app_version,
        screen_width=profile.screen_width,
        screen_height=profile.screen_height,
        flow_name=profile.flow_name,
        steps=profile.get_steps(),
        yaml_path=profile.yaml_path,
        created_at=profile.created_at,
    )


@router.post("", response_model=DeviceProfileResponse)
def register_device(payload: DeviceRegisterRequest) -> DeviceProfileResponse:
    with session_scope() as session:
        service = DeviceService(session)
        device = service.register_device(
            DeviceProfileInput(
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
        )
        return device_to_response(device)


@router.get("", response_model=list[DeviceProfileResponse])
def list_devices() -> list[DeviceProfileResponse]:
    with session_scope() as session:
        service = DeviceService(session)
        return [device_to_response(device) for device in service.list_devices()]


@router.post("/coordinate-profile", response_model=CoordinateProfileResponse)
def add_coordinate_profile(payload: CoordinateProfileCreateRequest) -> CoordinateProfileResponse:
    with session_scope() as session:
        service = DeviceService(session)
        profile = service.add_coordinate_profile(
            CoordinateProfileInput(
                flow_name=payload.flow_name,
                platform=payload.platform,
                device_id=payload.device_id,
                app_version=payload.app_version,
                screen_width=payload.screen_width,
                screen_height=payload.screen_height,
                steps=payload.steps,
            )
        )
        return coordinate_to_response(profile)


@router.post("/coordinate-profile/yaml", response_model=CoordinateProfileResponse)
def add_coordinate_profile_from_yaml(
    payload: CoordinateProfileYamlRequest,
) -> CoordinateProfileResponse:
    try:
        data = yaml.safe_load(payload.yaml_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail="invalid_coordinate_yaml") from exc
    screen = data.get("screen") or {}
    with session_scope() as session:
        service = DeviceService(session)
        profile = service.add_coordinate_profile(
            CoordinateProfileInput(
                flow_name=data.get("flow_name") or "uploaded_flow",
                platform=data.get("platform") or "xhs",
                device_id=payload.device_id or data.get("device_id"),
                app_version=data.get("app_version"),
                screen_width=screen.get("width") or data.get("screen_width"),
                screen_height=screen.get("height") or data.get("screen_height"),
                steps=data.get("steps") or [],
            )
        )
        return coordinate_to_response(profile)


@router.get("/coordinate-profile", response_model=list[CoordinateProfileResponse])
def list_coordinate_profiles(
    device_id: str | None = None,
    platform: str | None = None,
) -> list[CoordinateProfileResponse]:
    with session_scope() as session:
        service = DeviceService(session)
        profiles = service.list_coordinate_profiles(device_id=device_id, platform=platform)
        return [coordinate_to_response(profile) for profile in profiles]


@router.get("/coordinate-profile/{profile_id}", response_model=CoordinateProfileResponse)
def get_coordinate_profile(profile_id: str) -> CoordinateProfileResponse:
    with session_scope() as session:
        service = DeviceService(session)
        profile = service.get_coordinate_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="coordinate_profile_not_found")
        return coordinate_to_response(profile)


@router.get("/{device_id}", response_model=DeviceProfileResponse)
def get_device(device_id: str) -> DeviceProfileResponse:
    with session_scope() as session:
        service = DeviceService(session)
        device = service.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="device_not_found")
        return device_to_response(device)
