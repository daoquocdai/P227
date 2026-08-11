from fastapi import APIRouter

from src.services.history_service import history_service

router = APIRouter(prefix="/history", tags=["History"])


@router.get("")
async def get_history():
    events = history_service.list_events()
    return {"items": events, "total": len(events)}
