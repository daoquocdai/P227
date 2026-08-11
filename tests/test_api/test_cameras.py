from datetime import datetime
from uuid import uuid4

import pytest

from src.database import database_connection
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


@pytest.mark.asyncio
async def test_inactive_camera_can_be_edited_and_deleted(client):
    camera_id = str(uuid4())
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO cameras
               (id, name, source_type, source_reference, location_label, is_active, vision_enabled)
               VALUES (?, ?, 'video_file', 'videos/old.mp4', 'Vị trí cũ', 0, 0)""",
            (camera_id, f"Camera test {camera_id}"),
        )
        connection.execute(
            """INSERT INTO camera_sources (camera_id, source_kind, source_uri, playback_path)
               VALUES (?, 'video_file', 'videos/old.mp4', 'videos/old.mp4')""",
            (camera_id,),
        )
        connection.execute(
            "INSERT INTO frame_metrics (camera_id, frame_id, timestamp) VALUES (?, 1, ?)",
            (camera_id, datetime.now().astimezone().isoformat()),
        )
        connection.commit()

    updated = await client.patch(
        f"/api/v1/cameras/{camera_id}",
        json={
            "name": f"Camera đã sửa {camera_id}",
            "location": "Phòng mới",
            "source_kind": "video_file",
            "source_uri": "videos/76621-559757958.mp4",
            "playback_path": "videos/76621-559757958.mp4",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == f"Camera đã sửa {camera_id}"
    assert updated.json()["location"] == "Phòng mới"
    assert updated.json()["source"] == "videos/76621-559757958.mp4"

    deleted = await client.delete(f"/api/v1/cameras/{camera_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/cameras/{camera_id}")).status_code == 404
