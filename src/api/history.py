from fastapi import APIRouter, Depends
from src.api.auth import require_permission

from src.services.history_service import history_service

router = APIRouter(prefix="/history", tags=["History"])


@router.get("")
async def get_history(_=Depends(require_permission("view_history"))):
    events = history_service.list_events()
    return {"items": events, "total": len(events)}
