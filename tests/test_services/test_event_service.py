from datetime import datetime

import pytest

from src.models.schemas import AlertReviewRequest, VisionEventRequest
from src.services.event_service import EventService


def event(event_id: str = "event-1") -> VisionEventRequest:
    return VisionEventRequest(
        event_id=event_id,
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
    alerts = await service.list_alerts()
    assert alerts[0]["camera_id"] == "camera-living"
    assert alerts[0]["snapshot_url"] == "/snapshots/fall.svg"


@pytest.mark.asyncio
async def test_duplicate_event_is_idempotent():
    service = EventService()
    await service.create(event())
    duplicate = await service.create(event())

    assert duplicate.duplicate is True
    assert len(await service.list_alerts()) == 1


@pytest.mark.asyncio
async def test_review_event():
    service = EventService()
    await service.create(event())
    reviewed = await service.review(1, AlertReviewRequest(status="safe", note="Đã kiểm tra"))

    assert reviewed["status"] == "safe"
    assert reviewed["review_note"] == "Đã kiểm tra"
