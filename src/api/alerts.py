from fastapi import APIRouter, HTTPException
from typing import List
from src.services.mqtt_service import ALERTS_DB

router = APIRouter(prefix="/alerts", tags=["Alerts"])

@router.get("", response_model=List[dict])
def get_alerts():
    """API cho Front-End gọi để lấy danh sách cảnh báo khẩn cấp"""
    return sorted(ALERTS_DB, key=lambda x: x['id'], reverse=True)

@router.post("/confirm")
def confirm_alert(alert_id: int, feedback: str):
    """Cơ chế HITL: Xác nhận True/False Positive để tinh chỉnh hệ thống"""
    for alert in ALERTS_DB:
        if alert["id"] == alert_id:
            alert["feedback"] = feedback
            return {"message": f"Đã ghi nhận phản hồi '{feedback}' cho cảnh báo #{alert_id}"}
    raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo")