from datetime import datetime
from uuid import uuid4

import pytest

from src.models.schemas import VisionEventRequest
from src.services.event_service import event_service


def vision_event(event_id: str | None = None, event_type: str = "FALL_SUSPECTED") -> VisionEventRequest:
    return VisionEventRequest(
        event_id=event_id or f"test-{uuid4()}",
        camera_id="camera-bedroom",
        camera_location="Phòng ngủ",
        event_type=event_type,
        occurred_at=datetime.now().astimezone(),
        confidence=0.91,
        snapshot_path="test.svg",
    )


@pytest.mark.asyncio
async def test_get_alerts(client):
    event_id = f"test-intruder-{uuid4()}"
    await event_service.create(vision_event(event_id, "UNKNOWN_PERSON"))
    response = await client.get("/api/v1/alerts")

    assert response.status_code == 200
    data = response.json()
    assert any(item["event_id"] == event_id for item in data)


@pytest.mark.asyncio
async def test_mark_alert_read_updates_unread_count(client):
    accepted = await event_service.create(vision_event())
    before = (await client.get(f"/api/v1/alerts/{accepted.id}")).json()
    assert before["is_read"] is False

    marked = await client.post(f"/api/v1/alerts/{accepted.id}/read")
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    alerts = (await client.get("/api/v1/alerts")).json()
    assert next(item for item in alerts if item["id"] == accepted.id)["is_read"] is True


@pytest.mark.asyncio
async def test_confirm_alert_success(client):
    accepted = await event_service.create(vision_event())
    alert_id = accepted.id
    response = await client.post(f"/api/v1/alerts/confirm?alert_id={alert_id}&feedback=True Positive")

    assert response.status_code == 200
    assert response.json()["message"] == f"Đã ghi nhận phản hồi 'True Positive' cho cảnh báo #{alert_id}"
    assert (await event_service.list_alerts())[0]["review_note"] == "True Positive"


@pytest.mark.asyncio
async def test_confirm_alert_not_found(client):
    response = await client.post("/api/v1/alerts/confirm?alert_id=999&feedback=False")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_alert_updates_dashboard_status(client):
    alert_id = (await event_service.create(vision_event())).id
    response = await client.patch(
        f"/api/v1/alerts/{alert_id}", json={"status": "false_alarm", "note": "Người dùng xác nhận"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "false_alarm"
    assert response.json()["review_note"] == "Người dùng xác nhận"


@pytest.mark.asyncio
async def test_review_alert_rejects_invalid_status(client):
    alert_id = (await event_service.create(vision_event())).id
    response = await client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "invalid"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_alert_detail_and_hitl_status_round_trip(client):
    accepted = await event_service.create(vision_event())

    checking = await client.patch(
        f"/api/v1/alerts/{accepted.id}", json={"status": "checking", "note": "Đang gọi người nhà"}
    )
    assert checking.status_code == 200
    assert checking.json()["status"] == "checking"
    assert checking.json()["severity"] == "high"
    assert checking.json()["is_read"] is True

    help_requested = await client.patch(
        f"/api/v1/alerts/{accepted.id}", json={"status": "need_help", "note": "Cần hỗ trợ ngay"}
    )
    assert help_requested.json()["status"] == "need_help"
    assert help_requested.json()["review_note"] == "Cần hỗ trợ ngay"

    detail = await client.get(f"/api/v1/alerts/{accepted.id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "need_help"
    assert detail.json()["event_id"] == accepted.event_id


@pytest.mark.asyncio
async def test_vision_ingestion_is_end_to_end_and_idempotent(client):
    event_id = f"mock-yolo-{uuid4()}"
    payload = vision_event(event_id).model_dump(mode="json")
    first = await client.post("/api/v1/vision/events", json=payload)
    duplicate = await client.post("/api/v1/vision/events", json=payload)

    assert first.status_code == 202
    assert first.json()["accepted"] is True
    assert duplicate.json()["duplicate"] is True
    alerts = (await client.get("/api/v1/alerts")).json()
    assert len([item for item in alerts if item["event_id"] == event_id]) == 1
