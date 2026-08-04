from fastapi import APIRouter

from src.services.overview_service import overview_service

router = APIRouter(prefix="/overview", tags=["Overview"])


@router.get("")
async def get_overview():
    return overview_service.get_overview()
