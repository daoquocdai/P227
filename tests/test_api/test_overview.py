from datetime import datetime
from uuid import uuid4

import pytest

from src.models.schemas import VisionEventRequest
from src.services.event_service import event_service


@pytest.mark.asyncio
async def test_overview_uses_sqlite_camera_and_alert_data(client):
    event_id = f"overview-{uuid4()}"
    accepted = await event_service.create(
        VisionEventRequest(
            event_id=event_id,
            camera_id="camera-living",
            camera_location="Phòng khách",
            event_type="FALL_SUSPECTED",
            occurred_at=datetime.now().astimezone(),
            confidence=0.93,
            track_id="overview-track",
        )
    )

    response = await client.get("/api/v1/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["system_status"] == "attention"
    assert data["metrics"]["total_cameras"] >= 1
    assert data["metrics"]["events_today"] >= 1
    assert data["current_alert"]["id"] == accepted.id
    living_camera = next(camera for camera in data["cameras"] if camera["id"] == "camera-living")
    assert living_camera["playback_url"].startswith("/videos/")
    assert living_camera["preview_url"] is None
    assert "preview_version" in living_camera
    assert "vision_enabled" in living_camera
    assert "vision_status" in living_camera
