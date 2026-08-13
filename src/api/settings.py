from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.services.camera_service import CameraNotFoundError
from src.services.settings_service import SettingsConflictError, SettingsNotFoundError, settings_service
from src.api.auth import current_user, require_admin, require_permission

router = APIRouter(prefix="/settings", tags=["Settings"])


class GeneralUpdate(BaseModel):
    retention_days: Literal[7, 30, 90] | None = None
    stranger_threshold: int | None = Field(default=None, ge=50, le=99)
    fall_threshold: int | None = Field(default=None, ge=70, le=99)
    sensitive_enabled: bool | None = None
    sensitive_from: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sensitive_to: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class NotificationUpdate(BaseModel):
    app: bool | None = None
    email: bool | None = None
    sms: bool | None = None
    level: Literal["all", "important"] | None = None
    grouped: bool | None = None
    quiet_enabled: bool | None = None
    quiet_from: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_to: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")
    email: str = Field(min_length=4, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["caregiver"] = "caregiver"


class UserStatusUpdate(BaseModel):
    active: bool


class PermissionUpdate(BaseModel):
    granted: bool


class CameraStatusUpdate(BaseModel):
    active: bool | None = None
    vision_enabled: bool | None = None


@router.get("")
async def get_settings(request: Request, user: dict = Depends(current_user)):
    runtime = request.app.state.local_runtime
    return settings_service.get(runtime.camera, runtime.vision)


@router.patch("/general")
async def update_general(data: GeneralUpdate, _=Depends(require_permission("manage_cameras"))):
    return settings_service.update_group("general", data.model_dump(exclude_none=True))


@router.patch("/notifications")
async def update_notifications(data: NotificationUpdate, _=Depends(current_user)):
    return settings_service.update_group("notifications", data.model_dump(exclude_none=True))


@router.post("/users", status_code=201)
async def create_user(data: UserCreate, _=Depends(require_admin)):
    try:
        return settings_service.create_user(data)
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail="Email đã tồn tại") from exc


@router.patch("/users/{user_id}")
async def update_user(user_id: str, data: UserStatusUpdate, _=Depends(require_admin)):
    try:
        return settings_service.update_user(user_id, data.active)
    except SettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng") from exc
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail="Không thể khóa admin cuối cùng") from exc


@router.patch("/users/{user_id}/permissions/{permission}")
async def update_permission(user_id: str, permission: str, data: PermissionUpdate, _=Depends(require_admin)):
    try:
        return settings_service.update_permission(user_id, permission, data.granted)
    except SettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng hoặc quyền") from exc
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail="Admin luôn có toàn quyền") from exc


@router.patch("/cameras/{camera_id}")
async def update_camera(camera_id: str, data: CameraStatusUpdate, request: Request, _=Depends(require_permission("manage_cameras"))):
    try:
        runtime = request.app.state.local_runtime
        if data.active is not None:
            runtime.set_camera_enabled(camera_id, data.active)
        if data.vision_enabled is not None:
            runtime.set_vision_enabled(camera_id, data.vision_enabled)
        return settings_service.get(runtime.camera, runtime.vision)
    except (SettingsNotFoundError, CameraNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
