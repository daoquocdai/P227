import pytest


@pytest.mark.asyncio
async def test_system_status(client):
    response = await client.get("/api/v1/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["vision_integration"] == "in_process_queue"
    assert data["agent_enabled"] is False
