from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_settings_persist_users_permissions_and_camera_state(client):
    settings = await client.get("/api/v1/settings")
    assert settings.status_code == 200
    assert settings.json()["general"]["fall_threshold"] >= 70
    cameras = settings.json()["cameras"]
    assert len(cameras) == 3
    assert {camera["name"] for camera in cameras} == {
        "Webcam phòng khách",
        "Video mô phỏng",
        "Video hành lang",
    }

    general = await client.patch("/api/v1/settings/general", json={"retention_days": 7, "fall_threshold": 80})
    assert general.json()["retention_days"] == 7
    assert general.json()["fall_threshold"] == 80

    email = f"caregiver-{uuid4()}@example.local"
    created = await client.post(
        "/api/v1/settings/users", json={"name": "Người chăm sóc", "email": email, "role": "caregiver"}
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert created.json()["permissions"]["view_history"] is True

    permission = await client.patch(
        f"/api/v1/settings/users/{user_id}/permissions/manage_persons", json={"granted": True}
    )
    assert permission.json()["permissions"]["manage_persons"] is True

    camera_id = settings.json()["cameras"][0]["id"]
    camera = await client.patch(f"/api/v1/settings/cameras/{camera_id}", json={"active": False})
    assert next(item for item in camera.json()["cameras"] if item["id"] == camera_id)["is_active"] is False


@pytest.mark.asyncio
async def test_cannot_disable_last_admin(client):
    settings = (await client.get("/api/v1/settings")).json()
    admin = next(user for user in settings["users"] if user["role"] == "admin")
    response = await client.patch(f"/api/v1/settings/users/{admin['id']}", json={"active": False})
    assert response.status_code == 409
