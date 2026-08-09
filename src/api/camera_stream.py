from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from fastapi.responses import (
    StreamingResponse,
)

from src.services.camera_service import CameraNotFoundError, camera_service

router = APIRouter(
    prefix="/cameras",
    tags=["camera-runtime"],
)


def get_runtime(request: Request):

    runtime = getattr(
        request.app.state,
        "local_runtime",
        None
    )

    if runtime is None:

        raise RuntimeError(
            "LocalRuntime not initialized"
        )

    return runtime


@router.get(
    "/{camera_id}/stream"
)
def stream_camera(
    camera_id: str,
    request: Request,
):

    runtime = get_runtime(
        request
    )

    try:
        public_id = camera_service.public_id(camera_id)
    except CameraNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Camera not found") from exc

    state = runtime.camera.get_status(public_id)
    if state is None or state["status"] != "online" or not runtime.frame_hub.has_camera(public_id):
        raise HTTPException(status_code=409, detail="Camera is not streaming; start it and wait for the first frame")

    return StreamingResponse(
        runtime.stream.mjpeg(
            public_id
        ),

        media_type=(
            "multipart/x-mixed-replace; boundary=frame"
        ),

        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        }
    )


@router.get(
    "/{camera_id}/runtime/status"
)
def runtime_status(
    camera_id: str,
    request: Request,
):

    runtime = get_runtime(
        request
    )

    camera_status = (
        runtime.camera.get_status(
            camera_id
        )
    )

    if camera_status is None:

        raise HTTPException(
            status_code=404,
            detail="Camera not found"
        )

    return camera_status
