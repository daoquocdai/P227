import pytest


@pytest.mark.asyncio
async def test_health(client):
    """Kiểm tra health check endpoint của ứng dụng."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_evaluate_event_valid(client):
    """Kiểm tra API đánh giá sự kiện với payload hợp lệ[cite: 3]."""
    payload = {
        "event_type": "FALL_DETECTED",
        "camera_location": "Phòng khách",
        "timestamp": "2026-08-01 14:30:00",
        "confidence": 0.95,
        "snapshot_filename": "room_fall_test.jpg"
    }
    response = await client.post("/api/v1/evaluate-event", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "threat_level" in data
    assert "action_taken" in data
    assert "reasoning" in data


@pytest.mark.asyncio
async def test_evaluate_event_validation_error(client):
    """Kiểm tra Pydantic validation error khi thiếu dữ liệu đầu vào[cite: 3]."""
    response = await client.post("/api/v1/evaluate-event", json={})
    assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.asyncio
async def test_agent_status(client):
    """Kiểm tra endpoint trạng thái của Agent[cite: 3]."""
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"