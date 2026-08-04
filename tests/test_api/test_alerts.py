from datetime import datetime

import pytest
import pytest_asyncio

from src.models.schemas import VisionEventRequest
from src.services.event_service import event_service


def vision_event(event_id: str = "test-fall", event_type: str = "FALL_SUSPECTED") -> VisionEventRequest:
    return VisionEventRequest(
        event_id=event_id,
        camera_id="camera-bedroom",
        camera_location="Phòng ngủ",
        event_type=event_type,
        occurred_at=datetime.now().astimezone(),
        confidence=0.91,
        snapshot_path="test.svg",
    )


@pytest_asyncio.fixture(autouse=True)
async def reset_events():
    await event_service.clear()
    await event_service.create(vision_event())
    yield
    await event_service.clear()


@pytest.mark.asyncio
async def test_get_alerts(client):
    await event_service.create(vision_event("test-intruder", "UNKNOWN_PERSON"))
    response = await client.get("/api/v1/alerts")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["event_id"] == "test-intruder"


@pytest.mark.asyncio
async def test_confirm_alert_success(client):
    response = await client.post("/api/v1/alerts/confirm?alert_id=1&feedback=True Positive")

    assert response.status_code == 200
    assert response.json()["message"] == "Đã ghi nhận phản hồi 'True Positive' cho cảnh báo #1"
    assert (await event_service.list_alerts())[0]["feedback"] == "True Positive"


@pytest.mark.asyncio
async def test_confirm_alert_not_found(client):
    response = await client.post("/api/v1/alerts/confirm?alert_id=999&feedback=False")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_alert_updates_dashboard_status(client):
    response = await client.patch(
        "/api/v1/alerts/1", json={"status": "false_alarm", "note": "Người dùng xác nhận"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "false_alarm"
    assert response.json()["review_note"] == "Người dùng xác nhận"


@pytest.mark.asyncio
async def test_review_alert_rejects_invalid_status(client):
    response = await client.patch("/api/v1/alerts/1", json={"status": "invalid"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_vision_ingestion_is_end_to_end_and_idempotent(client):
    payload = vision_event("mock-yolo-event").model_dump(mode="json")
    first = await client.post("/api/v1/vision/events", json=payload)
    duplicate = await client.post("/api/v1/vision/events", json=payload)

    assert first.status_code == 202
    assert first.json()["accepted"] is True
    assert duplicate.json()["duplicate"] is True
    alerts = (await client.get("/api/v1/alerts")).json()
    assert len([item for item in alerts if item["event_id"] == "mock-yolo-event"]) == 1
