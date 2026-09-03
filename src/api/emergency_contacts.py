from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.api.auth import current_user
from src.services.auth_service import auth_service
from src.services.emergency_contact_service import (
    EmergencyContactNotFoundError,
    emergency_contact_service,
)

router = APIRouter(prefix="/emergency-contacts", tags=["Emergency Contacts"])


def require_contact_manager(user: dict = Depends(current_user)) -> dict:
    if user["force_password_change"] or not auth_service.allowed(user, "manage_persons"):
        raise HTTPException(403, "Không có quyền quản lý liên hệ khẩn cấp")
    return user


class EmergencyContactCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")
    relationship_label: str | None = Field(default=None, max_length=100)
    phone_e164: str
    priority: int = Field(default=1, ge=1, le=1000)
    is_active: bool = True

    @field_validator("phone_e164")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("+") or not value[1:].isdigit() or value[1] == "0" or not 8 <= len(value[1:]) <= 15:
            raise ValueError("phone_e164 must be a valid E.164 number")
        return value


class EmergencyContactUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255, pattern=r".*\S.*")
    relationship_label: str | None = Field(default=None, max_length=100)
    phone_e164: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool | None = None

    @field_validator("phone_e164")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("phone_e164 cannot be null")
        return EmergencyContactCreate.validate_phone(value)

    @field_validator("display_name", "priority", "is_active")
    @classmethod
    def reject_required_nulls(cls, value):
        if value is None:
            raise ValueError("field cannot be null")
        return value


@router.get("")
async def list_emergency_contacts(_user: dict = Depends(require_contact_manager)):
    return {"items": emergency_contact_service.list_contacts()}


@router.post("", status_code=201)
async def create_emergency_contact(data: EmergencyContactCreate, _user: dict = Depends(require_contact_manager)):
    return emergency_contact_service.create_contact(data)


@router.patch("/{contact_id}")
async def update_emergency_contact(
    contact_id: str,
    data: EmergencyContactUpdate,
    _user: dict = Depends(require_contact_manager),
):
    try:
        return emergency_contact_service.update_contact(contact_id, data)
    except EmergencyContactNotFoundError as exc:
        raise HTTPException(404, "Không tìm thấy liên hệ khẩn cấp") from exc


@router.delete("/{contact_id}")
async def deactivate_emergency_contact(contact_id: str, _user: dict = Depends(require_contact_manager)):
    try:
        return emergency_contact_service.deactivate_contact(contact_id)
    except EmergencyContactNotFoundError as exc:
        raise HTTPException(404, "Không tìm thấy liên hệ khẩn cấp") from exc
