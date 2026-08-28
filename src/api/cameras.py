import asyncio
import json
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.services.auth_service import AuthenticationError, InactiveAccountError, auth_service
from src.services.camera_service import CameraConflictError, CameraNotFoundError, camera_service

router = APIRouter(prefix="/cameras", tags=["Cameras"])


class CameraSourceUpdate(BaseModel):
    source_kind: Literal["video_file", "webcam", "rtsp"]
    source_uri: str | None = None
    playback_path: str | None = None


class CameraUpdate(CameraSourceUpdate):
    name: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")
    location: str = Field(min_length=1, max_length=255, pattern=r".*\S.*")


class IdentityUpdate(BaseModel):
    enabled: bool


@router.get("")
async def list_cameras(request: Request):
    runtime = request.app.state.local_runtime
    cameras = camera_service.list_cameras(runtime.camera, runtime.vision, runtime.frame_hub)
    return {"items": cameras, "total": len(cameras)}


@router.get("/{camera_id}")
async def get_camera(camera_id: str, request: Request):
    try:
        runtime = request.app.state.local_runtime
        return camera_service.get_camera(camera_id, runtime.camera, runtime.vision, runtime.frame_hub)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc


@router.patch("/{camera_id}/source")
async def update_camera_source(camera_id: str, source: CameraSourceUpdate, request: Request):
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
async def update_camera(camera_id: str, data: CameraUpdate, request: Request):
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
async def delete_camera(camera_id: str, request: Request):
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
async def start_camera(camera_id: str, request: Request, loop_video: bool = True):
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
async def stop_camera(camera_id: str, request: Request):
    try:
        return request.app.state.local_runtime.set_camera_enabled(camera_id, False)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc


@router.post("/{camera_id}/vision/enable")
async def enable_camera_vision(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return request.app.state.local_runtime.set_vision_enabled(public_id, True)


@router.post("/{camera_id}/vision/disable")
async def disable_camera_vision(camera_id: str, request: Request):
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


@router.get("/{camera_id}/vision/latest")
async def get_latest_camera_vision(camera_id: str, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    return {"result": request.app.state.local_runtime.vision.latest_result(public_id)}


@router.websocket("/{camera_id}/webcam")
async def publish_browser_webcam(camera_id: str, websocket: WebSocket):
    await websocket.accept()
    publisher_id = None
    public_id = None
    try:
        try:
            auth_text = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            auth_message = json.loads(auth_text)
            if (
                not isinstance(auth_message, dict)
                or auth_message.get("type") != "auth"
                or not isinstance(auth_message.get("token"), str)
            ):
                raise AuthenticationError
            auth_service.authenticate(auth_message.get("token"))
        except (TimeoutError, ValueError, AuthenticationError, InactiveAccountError):
            await websocket.close(code=4401, reason="Authentication required")
            return

        public_id = camera_service.public_id(camera_id)
        if camera_service.source_kind(public_id) != "webcam":
            await websocket.close(code=4403, reason="Camera is not browser-owned")
            return
        runtime = websocket.app.state.local_runtime
        try:
            publisher_id = runtime.camera.connect_browser_publisher(public_id)
        except RuntimeError:
            await websocket.close(code=4409, reason="Webcam publisher unavailable")
            return
        await websocket.send_json({"type": "ready", "publisher_id": publisher_id})

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            payload = message.get("bytes")
            if payload is None or len(payload) > 5 * 1024 * 1024:
                continue
            encoded = np.frombuffer(payload, dtype=np.uint8)
            frame = await asyncio.to_thread(cv2.imdecode, encoded, cv2.IMREAD_COLOR)
            if frame is not None:
                runtime.camera.submit_browser_frame(public_id, publisher_id, frame)
    except (CameraNotFoundError, WebSocketDisconnect):
        pass
    finally:
        if publisher_id is not None and public_id is not None:
            websocket.app.state.local_runtime.camera.disconnect_browser_publisher(public_id, publisher_id)


@router.patch("/{camera_id}/vision/identity")
async def set_camera_identity(camera_id: str, data: IdentityUpdate, request: Request):
    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy camera") from exc
    runtime = request.app.state.local_runtime
    if not data.enabled:
        # Persist the hard event gate before cancelling the running workflow,
        # so an already queued unknown event cannot commit during the handoff.
        camera_service.set_identity_enabled(public_id, False)
    if runtime.vision.get_status(public_id)["enabled"]:
        await asyncio.to_thread(runtime.vision.set_identity_enabled, public_id, data.enabled)
    if data.enabled:
        # Cold model preparation and runtime activation must succeed before the
        # persisted state advertises the feature as enabled.
        camera_service.set_identity_enabled(public_id, True)
    return {"camera_id": public_id, "identity_enabled": data.enabled}


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
