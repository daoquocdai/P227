import json

import pytest

from src.database import database_connection
from src.main import app
from src.services.camera_service import camera_service


@pytest.mark.asyncio
async def test_identity_off_is_persisted_and_applied_to_running_vision_without_restart(client):
    camera_id = camera_service.desired_states()[0]["id"]
    enabled = await client.post(f"/api/v1/cameras/{camera_id}/vision/enable")
    assert enabled.status_code == 200

    response = await client.patch(
        f"/api/v1/cameras/{camera_id}/vision/identity",
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["identity_enabled"] is False
    assert app.state.local_runtime.vision.get_status(camera_id)["identity_enabled"] is False
    assert (await client.get(f"/api/v1/cameras/{camera_id}")).json()["identity_enabled"] is False


def test_identity_config_update_merges_unrelated_settings():
    camera_id = camera_service.desired_states()[0]["id"]
    with database_connection() as connection:
        connection.execute(
            "UPDATE camera_sources SET config_json = ? WHERE camera_id = ?",
            (
                json.dumps(
                    {
                        "vision_enabled": True,
                        "identity_enabled": True,
                        "some_other_setting": "value",
                    }
                ),
                camera_id,
            ),
        )

    camera_service.set_identity_enabled(camera_id, False)

    with database_connection() as connection:
        row = connection.execute("SELECT config_json FROM camera_sources WHERE camera_id = ?", (camera_id,)).fetchone()
    assert json.loads(row["config_json"]) == {
        "vision_enabled": True,
        "identity_enabled": False,
        "some_other_setting": "value",
    }
