from datetime import datetime
from uuid import uuid4

import pytest

from src.models.schemas import VisionEventRequest
from src.services.event_service import event_service


@pytest.mark.asyncio
async def test_camera_list_detail_and_source_update(client):
    public_camera_id = "camera-living"
    external_event_id = f"camera-event-{uuid4()}"
    await event_service.create(
        VisionEventRequest(
            event_id=external_event_id,
            camera_id=public_camera_id,
            camera_location="Phòng camera API",
            event_type="FALL_SUSPECTED",
            occurred_at=datetime.now().astimezone(),
            confidence=0.9,
            track_id="camera-api-track",
        )
    )

    listing = await client.get("/api/v1/cameras")
    assert listing.status_code == 200
    assert any(camera["id"] == public_camera_id for camera in listing.json()["items"])

    detail = await client.get(f"/api/v1/cameras/{public_camera_id}")
    assert detail.status_code == 200
    assert any(event["event_id"] == external_event_id for event in detail.json()["events"])

    updated = await client.patch(
        f"/api/v1/cameras/{public_camera_id}/source",
        json={
            "source_kind": "video_file",
            "source_uri": "videos/76621-559757958.mp4",
            "playback_path": "videos/76621-559757958.mp4",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["playback_url"] == "/videos/76621-559757958.mp4"


@pytest.mark.asyncio
async def test_rtsp_credentials_are_not_exposed_to_frontend(client):
    camera_id = "camera-bedroom"
    await event_service.create(
        VisionEventRequest(
            event_id=f"camera-rtsp-event-{uuid4()}",
            camera_id=camera_id,
            camera_location="Camera RTSP test",
            event_type="UNKNOWN_PERSON",
            occurred_at=datetime.now().astimezone(),
            confidence=0.85,
            track_id="camera-rtsp-track",
        )
    )

    try:
        updated = await client.patch(
            f"/api/v1/cameras/{camera_id}/source",
            json={"source_kind": "rtsp", "source_uri": "rtsp://user:secret@192.168.1.20/live"},
        )

        assert updated.status_code == 200
        assert updated.json()["source_kind"] == "rtsp"
        assert updated.json()["playback_url"] is None
        assert "secret" not in str(updated.json())
    finally:
        await client.patch(
            f"/api/v1/cameras/{camera_id}/source",
            json={
                "source_kind": "video_file",
                "source_uri": "videos/45353-448489443_medium.mp4",
                "playback_path": "videos/45353-448489443_medium.mp4",
            },
        )
