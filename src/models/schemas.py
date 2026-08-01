from pydantic import BaseModel, Field
from typing import Optional

# 1. SCHEMA ĐẦU VÀO: Khi Camera Edge (YOLO/Pose) phát hiện sự kiện và gửi cho Agent
class EventRequest(BaseModel):
    event_type: str = Field(..., description="Loại sự kiện phát hiện (VD: FALL_DETECTED, UNKNOWN_PERSON)")
    camera_location: str = Field(..., description="Vị trí camera (VD: Phòng khách, Hành lang)")
    timestamp: str = Field(..., description="Thời gian xảy ra sự kiện")
    confidence: float = Field(default=0.9, description="Độ tin cậy của mô hình YOLO/Pose tại Edge")
    snapshot_filename: Optional[str] = Field(default=None, description="Tên file ảnh chụp bằng chứng (nếu có)")

# 2. SCHEMA ĐẦU RA: Quyết định và phân tích của LangGraph Agent
class AgentDecisionResponse(BaseModel):
    threat_level: str = Field(..., description="Mức độ nguy hiểm do Agent đánh giá (VD: CRITICAL, WARNING, INFO)")
    action_taken: str = Field(..., description="Hành động Agent đề xuất (VD: REQUIRE_HITL, TRIGGER_SIREN, IGNORE)")
    reasoning: str = Field(..., description="Chuỗi suy luận giải thích tại sao Agent đưa ra quyết định này")