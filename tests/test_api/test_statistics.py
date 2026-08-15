from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.api.auth import require_admin
from src.database import database_connection
from src.main import app
from src.models.schemas import AlertReviewRequest, VisionEventRequest
from src.services.event_service import event_service


@pytest.mark.asyncio
async def test_statistics_returns_alert_and_device_metrics_for_admin(client):
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    now = datetime.now(UTC)
    event = VisionEventRequest(
        event_id=f"statistics-{uuid4()}", camera_id="camera-statistics", camera_location="Phòng khách",
        event_type="FALL_SUSPECTED", occurred_at=now, confidence=0.92,
    )
    accepted = await event_service.create(event)
    await event_service.review(accepted.id, AlertReviewRequest(status="false_alarm", note="Bóng đổ"))
    with database_connection() as connection:
        camera_id = connection.execute("SELECT id FROM cameras WHERE name='camera-statistics'").fetchone()[0]
        connection.execute(
            """INSERT INTO inference_metrics
               (id,camera_id,measured_at,fps,latency_ms,false_positive_rate)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid4()), camera_id, now.isoformat(), 8.0, 180.0, 0.25),
        )
        connection.execute(
            """INSERT INTO device_metrics
               (id,camera_id,measured_at,ram_usage_mb,ram_total_mb,cpu_usage_percent,ping_ms,disk_usage_percent)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(uuid4()), camera_id, now.isoformat(), 950.0, 1000.0, 92.0, 45.0, 50.0),
        )
    try:
        response = await client.get("/api/v1/statistics?period=today")
        assert response.status_code == 200
        data = response.json()
        assert data["kpis"]["total_alerts"]["value"] >= 1
        assert data["kpis"]["false_alerts"]["value"] >= 1
        assert "unconfirmed_alerts" in data["kpis"]
        assert len({item["day"] for item in data["alert_timeline"]}) == 1
        device = next(item for item in data["devices"] if item["name"] == "camera-statistics")
        assert device["fps"] == 8.0
        assert device["cpu_usage_percent"] == 92.0
        assert any(item["camera_name"] == "camera-statistics" for item in data["threshold_alerts"])
        assert any(item["note"] == "Bóng đổ" for item in data["false_alarm_reasons"])
    finally:
        app.dependency_overrides.pop(require_admin, None)


@pytest.mark.asyncio
async def test_statistics_rejects_invalid_custom_range(client):
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    try:
        response = await client.get("/api/v1/statistics?period=custom")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(require_admin, None)


@pytest.mark.asyncio
async def test_statistics_seven_day_timeline_contains_every_day(client):
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    try:
        response = await client.get("/api/v1/statistics?period=7d")
        assert response.status_code == 200
        timeline = response.json()["alert_timeline"]
        assert len({item["day"] for item in timeline}) == 7
        assert {item["alert_type"] for item in timeline} == {"fall", "unknown_person"}
    finally:
        app.dependency_overrides.pop(require_admin, None)
