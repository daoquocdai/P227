from datetime import datetime
from uuid import uuid4

import pytest

from src.models.schemas import VisionEventRequest
from src.services.event_service import event_service


@pytest.mark.asyncio
async def test_history_returns_persisted_event_details(client):
    external_id = f"history-{uuid4()}"
    await event_service.create(
        VisionEventRequest(
            event_id=external_id,
            camera_id="camera-living",
            camera_location="Phòng khách",
            event_type="FALL_SUSPECTED",
            occurred_at=datetime.now().astimezone(),
            confidence=0.94,
            track_id="history-track",
            identity_status="KNOWN",
            identity_name="Bà Lan",
            snapshot_path="history-fall.svg",
            immobile_seconds=8,
        )
    )

    response = await client.get("/api/v1/history")
    assert response.status_code == 200
    event = next(item for item in response.json()["items"] if item["event_id"] == external_id)
    assert event["camera_id"] == "camera-living"
    assert event["fall"]["immobility_ms"] == 8000
    assert event["person"]["name"] == "Bà Lan"
    assert event["media"] == []
    assert event["alert"]["status"] == "open"
