from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# Sự kiện đã được Vision Service và Temporal Event Engine trên Local Hub xử lý.
# Agent chỉ diễn giải/điều phối HITL, không ra quyết định thị giác từ frame thô.
class EventRequest(BaseModel):
    event_type: str = Field(..., description="Loại sự kiện phát hiện (VD: FALL_DETECTED, UNKNOWN_PERSON)")
    camera_location: str = Field(..., description="Vị trí camera (VD: Phòng khách, Hành lang)")
    timestamp: str = Field(..., description="Thời gian xảy ra sự kiện")
    confidence: float = Field(
        default=0.9, ge=0.0, le=1.0, description="Độ tin cậy do Vision Service trên Local Hub cung cấp"
    )
    snapshot_filename: str | None = Field(default=None, description="Tên file ảnh chụp bằng chứng (nếu có)")


# 2. SCHEMA ĐẦU RA: Quyết định và phân tích của LangGraph Agent
class AgentDecisionResponse(BaseModel):
    threat_level: str = Field(..., description="Mức độ nguy hiểm do Agent đánh giá (VD: CRITICAL, WARNING, INFO)")
    action_taken: str = Field(..., description="Hành động Agent đề xuất (VD: REQUIRE_HITL, TRIGGER_SIREN, IGNORE)")
    reasoning: str = Field(..., description="Chuỗi suy luận giải thích tại sao Agent đưa ra quyết định này")


AlertStatus = Literal["pending", "checking", "resolved", "safe", "false_alarm", "need_help"]


class AlertReviewRequest(BaseModel):
    status: AlertStatus
    note: str | None = Field(default=None, max_length=1000)


class AlertResponse(BaseModel):
    id: str
    event_id: str
    timestamp: str
    event_type: str
    description: str
    camera_id: str
    camera_location: str
    confidence: float | None = None
    identity_name: str | None = None
    immobile_seconds: float | None = None
    snapshot_url: str | None = None
    severity: Literal["low", "medium", "high", "critical"]
    status: AlertStatus
    feedback: str | None = None
    review_note: str | None = None
    created_at: str
    updated_at: str
    is_read: bool
    agent_status: Literal["queued", "running", "completed", "failed", "skipped"] | None = None
    agent_verdict: Literal["CONFIRMED_ALERT", "UNCERTAIN", "DUPLICATE"] | None = None
    agent_severity: Literal["low", "medium", "high", "critical"] | None = None
    agent_reason_summary: str | None = None
    incident_id: str | None = None
    incident_status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED_SAFE"] | None = None
    occurrence_count: int = 1
    first_seen_at: str
    last_seen_at: str
    incident_version: int | None = None
    acknowledged_at: str | None = None
    resolved_at: str | None = None


EventType = Literal[
    "FALL_SUSPECTED",
    "FALL_CONFIRMED",
    "UNKNOWN_PERSON",
    "PERSON_RECOGNIZED",
    "INACTIVITY_DETECTED",
    "CAMERA_OFFLINE",
    "CAMERA_ONLINE",
]
IdentityStatus = Literal["KNOWN", "UNKNOWN", "UNCERTAIN", "DISABLED"]


class VisionEventRequest(BaseModel):
    """Contract dùng chung giữa Vision pipeline và backend baseline."""

    schema_version: int = Field(default=1, ge=1)
    event_id: str = Field(min_length=1, max_length=128)
    camera_id: str = Field(min_length=1, max_length=128)
    camera_location: str = Field(min_length=1, max_length=255)
    event_type: EventType
    occurred_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    track_id: str | None = Field(default=None, max_length=128)
    identity_status: IdentityStatus = "UNKNOWN"
    identity_name: str | None = Field(default=None, max_length=255)
    snapshot_path: str | None = Field(default=None, max_length=500)
    immobile_seconds: float | None = Field(default=None, ge=0.0)
    metadata: dict = Field(default_factory=dict)


class VisionEventAccepted(BaseModel):
    id: str
    event_id: str
    accepted: bool = True
    duplicate: bool = False
    status: AlertStatus
    incident_id: str | None = None
    incident_version: int | None = None
    occurrence_count: int | None = None
    alert_created: bool = False
    incident_updated: bool = False
    suppressed: bool = False
    agent_review_required: bool = False
