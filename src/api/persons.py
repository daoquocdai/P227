import base64
import binascii
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from src.api.auth import current_user, require_permission
from pydantic import BaseModel, Field

from src.services.face_identity_service import FaceEnrollmentError
from src.services.person_service import FaceProfileNotFoundError, PersonNotFoundError, person_service

router = APIRouter(prefix="/persons", tags=["Persons"])


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")
    relationship: str | None = Field(default=None, max_length=100)
    birth: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    active: bool = True


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255, pattern=r".*\S.*")
    relationship: str | None = Field(default=None, max_length=100)
    birth: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class FaceCreate(BaseModel):
    image_data_url: str = Field(min_length=10, max_length=14_000_000)
    angle: str = Field(default="Ảnh mới", max_length=100)


@router.get("")
async def list_people(_=Depends(current_user)):
    return {"items": person_service.list_people()}


@router.post("", status_code=201)
async def create_person(person: PersonCreate, _=Depends(require_permission("manage_persons"))):
    return person_service.create_person(person)


@router.patch("/{person_id}")
async def update_person(person_id: str, person: PersonUpdate, user=Depends(require_permission("manage_persons"))):
    if person.active is False and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên được vô hiệu hóa người thân")
    try:
        return person_service.update_person(person_id, person)
    except PersonNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy người thân") from exc


@router.post("/{person_id}/faces", status_code=201)
async def add_face(person_id: str, face: FaceCreate, _=Depends(require_permission("manage_persons"))):
    try:
        header, separator, payload = face.image_data_url.partition(",")
        if separator != "," or not header.startswith("data:image/") or ";base64" not in header:
            raise FaceEnrollmentError("Face image must be a base64 image data URL")
        image_bytes = base64.b64decode(payload, validate=True)
        return person_service.add_face(person_id, image_bytes, face.angle)
    except (binascii.Error, FaceEnrollmentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PersonNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy người thân") from exc


@router.delete("/{person_id}/faces/{face_id}", status_code=200)
async def delete_face(person_id: str, face_id: str, _=Depends(require_permission("manage_persons"))):
    try:
        return person_service.delete_face(person_id, face_id)
    except (PersonNotFoundError, FaceProfileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khuôn mặt") from exc
