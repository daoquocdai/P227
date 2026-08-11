from fastapi import APIRouter, status

from src.models.schemas import VisionEventAccepted, VisionEventRequest
from src.services.event_service import vision_event_sink

router = APIRouter(prefix="/vision", tags=["Vision integration"])


@router.post("/events", response_model=VisionEventAccepted, status_code=status.HTTP_202_ACCEPTED)
async def ingest_vision_event(event: VisionEventRequest):
    """Dev/process-boundary adapter using the same sink as in-process Vision.

    Code Vision tích hợp trong Local Hub nên import ``vision_event_sink`` và gọi
    ``await vision_event_sink.publish(event)`` trực tiếp. Endpoint này giúp nhóm
    Vision và script mock kiểm thử độc lập trước khi merge code.
    """
    return await vision_event_sink.publish(event)
