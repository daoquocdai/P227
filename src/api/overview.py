from fastapi import APIRouter, Request

from src.services.overview_service import overview_service

router = APIRouter(prefix="/overview", tags=["Overview"])


@router.get("")
async def get_overview(request: Request):
    runtime = request.app.state.local_runtime
    return overview_service.get_overview(runtime.camera, runtime.vision, runtime.frame_hub)
