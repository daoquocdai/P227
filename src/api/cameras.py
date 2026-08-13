from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from src.api.auth import current_user, require_permission
from pydantic import BaseModel, Field

from src.services.camera_service import CameraConflictError, CameraNotFoundError, camera_service

router = APIRouter(prefix="/cameras", tags=["Cameras"])


class CameraSourceUpdate(BaseModel):
    source_kind: Literal["video_file", "webcam", "rtsp"]
    source_uri: str | None = None
    playback_path: str | None = None


class CameraUpdate(CameraSourceUpdate):
    name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")
    location: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")


@router.get("")
async def list_cameras(request: Request, _=Depends(current_user)):
    runtime = request.app.state.local_runtime
    cameras = camera_service.list_cameras(runtime.camera, runtime.vision, runtime.frame_hub)
    return {"items": cameras, "total": len(cameras)}


@router.get("/{camera_id}")
async def get_camera(camera_id: str, request: Request, _=Depends(current_user)):
    try:
        runtime = request.app.state.local_runtime
        return camera_service.get_camera(camera_id, runtime.camera, runtime.vision, runtime.frame_hub)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc


@router.patch("/{camera_id}/source")
async def update_camera_source(camera_id: str, source: CameraSourceUpdate, request: Request, _=Depends(require_permission("manage_cameras"))):
    try:
        camera_service.update_source(camera_id, source.source_kind, source.source_uri, source.playback_path)
        request.app.state.local_runtime.restart_camera_if_enabled(camera_id)
        runtime = request.app.state.local_runtime
        return camera_service.get_camera(camera_id, runtime.camera, runtime.vision, runtime.frame_hub)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{camera_id}")
async def update_camera(camera_id: str, data: CameraUpdate, request: Request, _=Depends(require_permission("manage_cameras"))):
    runtime = request.app.state.local_runtime
    try:
        old_public_id = camera_service.public_id(camera_id)
        desired = next(item for item in camera_service.desired_states() if item["id"] == old_public_id)
        camera_service.update_details(
            camera_id,
            name=data.name,
            location=data.location,
            source_kind=data.source_kind,
            source_uri=data.source_uri,
            playback_path=data.playback_path,
        )
        if runtime.camera.is_running(old_public_id):
            runtime.camera.stop(old_public_id)
        runtime.vision.disable(old_public_id)
        if desired["camera_enabled"]:
            runtime.start_persisted_camera(camera_id, desired["loop_video"])
        if desired["vision_enabled"]:
            runtime.vision.enable(camera_service.public_id(camera_id))
        return camera_service.get_camera(camera_id, runtime.camera, runtime.vision, runtime.frame_hub)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except CameraConflictError as exc:
        raise HTTPException(status_code=409, detail="Tên camera đã tồn tại") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: str, request: Request, _=Depends(require_permission("manage_cameras"))):
    runtime = request.app.state.local_runtime
    try:
        public_id = camera_service.public_id(camera_id)
        if runtime.camera.is_running(public_id):
            raise CameraConflictError("active_camera")
        runtime.vision.disable(public_id)
        camera_service.delete_inactive(camera_id)
        return Response(status_code=204)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except CameraConflictError as exc:
        detail = "Hãy tắt camera trong Cài đặt trước khi xóa"
        if str(exc) == "camera_has_history":
            detail = "Camera còn dữ liệu lịch sử nên chưa thể xóa"
        raise HTTPException(status_code=409, detail=detail) from exc


@router.post("/{camera_id}/start", status_code=202)
async def start_camera(camera_id: str, request: Request, loop_video: bool = True, _=Depends(require_permission("manage_cameras"))):
    try:
        camera_service.set_camera_enabled(camera_id, True)
        return request.app.state.local_runtime.start_persisted_camera(camera_id, loop_video)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{camera_id}/stop")
async def stop_camera(camera_id: str, request: Request, _=Depends(require_permission("manage_cameras"))):
    try:
        return request.app.state.local_runtime.set_camera_enabled(camera_id, False)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc


@router.post("/{camera_id}/vision/enable")
async def enable_camera_vision(camera_id: str, request: Request, _=Depends(require_permission("manage_cameras"))):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.set_vision_enabled(public_id, True)


@router.post("/{camera_id}/vision/disable")
async def disable_camera_vision(camera_id: str, request: Request, _=Depends(require_permission("manage_cameras"))):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.set_vision_enabled(public_id, False)


@router.get("/{camera_id}/vision/status")
async def get_camera_vision_status(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.vision.get_status(public_id)


@router.get("/{camera_id}/preview")
async def latest_camera_preview(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Camera not found") from exc
    encoded = request.app.state.local_runtime.stream.latest_jpeg(public_id)
    if encoded is None:
        raise HTTPException(status_code=404, detail="Camera preview is not available")
    jpeg, frame_id = encoded
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Id": str(frame_id)},
    )
