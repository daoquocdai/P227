from fastapi import APIRouter, HTTPException

from src.models.schemas import AlertReviewRequest
from src.services.event_service import EventNotFoundError, event_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[dict])
async def get_alerts():
    """Danh sách cảnh báo cho dashboard, mới nhất trước."""
    return await event_service.list_alerts()


@router.patch("/{alert_id}", response_model=dict)
async def review_alert(alert_id: int, review: AlertReviewRequest):
    """Cập nhật trạng thái Human-in-the-loop từ dashboard."""
    try:
        return await event_service.review(alert_id, review)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc


@router.post("/confirm")
async def confirm_alert(alert_id: int, feedback: str):
    """Endpoint cũ, được giữ để tương thích với client hiện tại."""
    try:
        await event_service.confirm_legacy(alert_id, feedback)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo") from exc
    return {"message": f"Đã ghi nhận phản hồi '{feedback}' cho cảnh báo #{alert_id}"}
