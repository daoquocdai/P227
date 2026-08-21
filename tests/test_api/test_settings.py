from uuid import uuid4

import pytest

from src.models.vision import VisionDetection, VisionResult
from src.services.vision_product_policy import VisionProductPolicy


@pytest.mark.asyncio
async def test_settings_persist_users_permissions_and_camera_state(client):
    settings = await client.get("/api/v1/settings")
    assert settings.status_code == 200
    assert settings.json()["general"]["fall_threshold"] >= 70
    cameras = settings.json()["cameras"]
    assert cameras
    assert all("vision_enabled" in camera for camera in cameras)

    general = await client.patch("/api/v1/settings/general", json={"retention_days": 7, "fall_threshold": 80})
    assert general.json()["retention_days"] == 7
    assert general.json()["fall_threshold"] == 80

    email = f"caregiver-{uuid4()}@example.local"
    created = await client.post(
        "/api/v1/settings/users",
        json={"name": "Người chăm sóc", "email": email, "password": "TamThoi@123", "role": "caregiver"},
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
    stopped_camera = next(item for item in camera.json()["cameras"] if item["id"] == camera_id)
    assert stopped_camera["is_active"] is False
    assert stopped_camera["operational_status"] == "offline"

    vision = await client.patch(
        f"/api/v1/settings/cameras/{camera_id}", json={"vision_enabled": True}
    )
    vision_camera = next(item for item in vision.json()["cameras"] if item["id"] == camera_id)
    assert vision_camera["vision_enabled"] is True
    assert vision_camera["vision_status"] == "waiting_for_source"


@pytest.mark.asyncio
async def test_cannot_disable_last_admin(client):
    settings = (await client.get("/api/v1/settings")).json()
    admin = next(user for user in settings["users"] if user["role"] == "admin")
    response = await client.patch(f"/api/v1/settings/users/{admin['id']}", json={"active": False})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_stranger_threshold_update_changes_live_product_decision_without_restart(client):
    def candidate():
        return VisionResult(
            camera_id="settings-live-camera",
            frame_id=1,
            captured_at=1.0,
            processed_at=1.0,
            processing_ms=1.0,
            detections=[
                VisionDetection(
                    "person",
                    0.9,
                    track_id=7,
                    metadata={
                        "identity_state": "LOCKED_UNKNOWN",
                            "identity_face_detected": True,
                            "identity_face_verified": True,
                        "identity_similarity": 0.4,
                    },
                )
            ],
            metadata={"observation_time": 1.0},
        )

    policy = VisionProductPolicy()
    high = await client.patch("/api/v1/settings/general", json={"stranger_threshold": 70})
    assert high.status_code == 200
    assert policy.apply(candidate()).events == []

    low = await client.patch("/api/v1/settings/general", json={"stranger_threshold": 50})
    assert low.status_code == 200
    assert [event.type for event in policy.apply(candidate()).events] == ["unknown_person"]
