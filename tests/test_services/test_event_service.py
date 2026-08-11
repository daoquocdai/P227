from datetime import datetime
from uuid import uuid4

import pytest

from src.models.schemas import AlertReviewRequest, VisionEventRequest
from src.services.event_service import EventService


def event(event_id: str | None = None) -> VisionEventRequest:
    return VisionEventRequest(
        event_id=event_id or f"event-{uuid4()}",
        camera_id="camera-living",
        camera_location="Phòng khách",
        event_type="FALL_SUSPECTED",
        occurred_at=datetime.now().astimezone(),
        confidence=0.92,
        track_id="37",
        snapshot_path="fall.svg",
    )


@pytest.mark.asyncio
async def test_create_and_list_event():
    service = EventService()
    accepted = await service.create(event())

    assert accepted.accepted is True
    alerts = await EventService().list_alerts()
    persisted = next(item for item in alerts if item["event_id"] == accepted.event_id)
    assert persisted["camera_id"] == "camera-living"
    assert persisted["snapshot_url"] is None


@pytest.mark.asyncio
async def test_duplicate_event_is_idempotent():
    service = EventService()
    same_event = event()
    await service.create(same_event)
    duplicate = await service.create(same_event)

    assert duplicate.duplicate is True
    assert len([item for item in await service.list_alerts() if item["event_id"] == same_event.event_id]) == 1


@pytest.mark.asyncio
async def test_review_event():
    service = EventService()
    accepted = await service.create(event())
    reviewed = await service.review(accepted.id, AlertReviewRequest(status="safe", note="Đã kiểm tra"))

    assert reviewed["status"] == "safe"
    assert reviewed["review_note"] == "Đã kiểm tra"


@pytest.mark.asyncio
async def test_recognized_person_is_persisted_without_creating_alert():
    service = EventService()
    recognized = event()
    recognized.event_type = "PERSON_RECOGNIZED"
    recognized.identity_status = "KNOWN"
    recognized.identity_name = "Bà Lan"

    accepted = await service.create(recognized)

    assert accepted.status == "resolved"
    assert all(item["event_id"] != recognized.event_id for item in await service.list_alerts())
