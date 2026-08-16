from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import require_admin
from src.services.statistics_service import statistics_service

router = APIRouter(prefix="/statistics", tags=["Statistics"])


@router.get("")
async def get_statistics(
    request: Request,
    period: Literal["today", "7d", "30d", "custom"] = "7d",
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    _user: dict = Depends(require_admin),
):
    try:
        range_start, range_end = statistics_service.range_for(period, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return statistics_service.get_statistics(
        range_start,
        range_end,
        period=period,
        runtime=request.app.state.local_runtime,
    )
