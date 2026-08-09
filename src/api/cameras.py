from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.services.camera_service import CameraNotFoundError, camera_service

router = APIRouter(prefix="/cameras", tags=["Cameras"])


class CameraSourceUpdate(BaseModel):
    source_kind: Literal["video_file", "webcam", "rtsp"]
    source_uri: str | None = None
    playback_path: str | None = None


@router.get("")
async def list_cameras(request: Request):
    cameras = camera_service.list_cameras(request.app.state.local_runtime.camera)
    return {"items": cameras, "total": len(cameras)}


@router.get("/{camera_id}")
async def get_camera(camera_id: str, request: Request):
    try:
        return camera_service.get_camera(camera_id, request.app.state.local_runtime.camera)
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


@router.post("/{camera_id}/start", status_code=202)
async def start_camera(camera_id: str, request: Request, loop_video: bool = True):
    runtime = request.app.state.local_runtime.camera
    try:
        public_id, source = camera_service.resolve_source(camera_id)
        return runtime.start(public_id, source, loop_video=loop_video)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{camera_id}/stop")
async def stop_camera(camera_id: str, request: Request):
    runtime = request.app.state.local_runtime.camera
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    state = runtime.stop(public_id)
    return state or {"camera_id": public_id, "status": "offline"}


@router.post("/{camera_id}/vision/enable")
async def enable_camera_vision(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.vision.enable(public_id)


@router.post("/{camera_id}/vision/disable")
async def disable_camera_vision(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.vision.disable(public_id)


@router.get("/{camera_id}/vision/status")
async def get_camera_vision_status(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.vision.get_status(public_id)
