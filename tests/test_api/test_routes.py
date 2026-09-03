from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_system_status(client):
    response = await client.get("/api/v1/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["vision_integration"] == "in_process_queue"
    assert data["agent_enabled"] is False


@pytest.mark.asyncio
async def test_system_status_reflects_agent_configuration(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.routes.get_settings",
        lambda: SimpleNamespace(alert_agent_enabled=True),
    )

    response = await client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["agent_enabled"] is True
