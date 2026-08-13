import json

from fastapi import APIRouter, Depends, HTTPException
from src.api.auth import current_user
from src.services.auth_service import auth_service
from fastapi.responses import StreamingResponse

from src.models.schemas import AlertResponse, AlertReviewRequest
from src.services.alert_broadcaster import alert_broadcaster
from src.services.event_service import EventNotFoundError, event_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertResponse])
async def get_alerts(_=Depends(current_user)):
    """Danh sách cảnh báo cho dashboard, mới nhất trước."""
    return await event_service.list_alerts()


@router.get("/stream")
async def stream_alerts():
    async def events():
        yield "event: ready\ndata: {}\n\n"
        async for message in alert_broadcaster.subscribe():
            if message["type"] == "heartbeat":
                yield ": heartbeat\n\n"
            else:
                yield f"event: alert\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, _=Depends(current_user)):
    try:
        return await event_service.get_alert(alert_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc


@router.patch("/{alert_id}", response_model=AlertResponse)
async def review_alert(alert_id: str, review: AlertReviewRequest, user=Depends(current_user)):
    """Cập nhật trạng thái Human-in-the-loop từ dashboard."""
    required = "resolve_alert" if getattr(review, "status", None) in {"resolved", "dismissed"} else "acknowledge_alert"
    if not auth_service.allowed(user, required):
        raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này")
    try:
        return await event_service.review(alert_id, review)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_alert_read(alert_id: str, _=Depends(current_user)):
    try:
        return await event_service.mark_read(alert_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc


@router.post("/confirm")
async def confirm_alert(alert_id: str, feedback: str):
    """Endpoint cũ, được giữ để tương thích với client hiện tại."""
    try:
        await event_service.confirm_legacy(alert_id, feedback)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc
    return {"message": f"Đã ghi nhận phản hồi '{feedback}' cho cảnh báo #{alert_id}"}
