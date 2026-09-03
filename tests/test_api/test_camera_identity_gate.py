import pytest

from src.services.camera_service import camera_service


@pytest.mark.asyncio
async def test_identity_toggle_endpoint_is_not_part_of_product_api(client):
    camera_id = camera_service.desired_states()[0]["id"]
    response = await client.patch(
        f"/api/v1/cameras/{camera_id}/vision/identity",
        json={"enabled": False},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_camera_contract_has_no_identity_toggle(client):
    camera_id = camera_service.desired_states()[0]["id"]
    response = await client.get(f"/api/v1/cameras/{camera_id}")
    assert response.status_code == 200
    assert "identity_enabled" not in response.json()
