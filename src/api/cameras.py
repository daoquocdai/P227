from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.camera_service import CameraNotFoundError, camera_service

router = APIRouter(prefix="/cameras", tags=["Cameras"])


class CameraSourceUpdate(BaseModel):
    source_kind: Literal["video_file", "webcam", "rtsp"]
    source_uri: str | None = None
    playback_path: str | None = None


@router.get("")
async def list_cameras():
    cameras = camera_service.list_cameras()
    return {"items": cameras, "total": len(cameras)}


@router.get("/{camera_id}")
async def get_camera(camera_id: str):
    try:
        return camera_service.get_camera(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc


@router.patch("/{camera_id}/source")
async def update_camera_source(camera_id: str, source: CameraSourceUpdate):
    try:
        return camera_service.update_source(camera_id, source.source_kind, source.source_uri, source.playback_path)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
