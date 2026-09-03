import pytest

from src.api.auth import current_user
from src.main import app


@pytest.fixture(autouse=True)
def contact_manager():
    app.dependency_overrides[current_user] = lambda: {
        "id": "11111111-1111-4111-8111-111111111111",
        "role": "admin",
        "force_password_change": False,
        "permissions": {},
    }
    try:
        yield
    finally:
        app.dependency_overrides.pop(current_user, None)


@pytest.mark.asyncio
async def test_emergency_contact_crud_deactivates_instead_of_deleting(client):
    created = await client.post(
        "/api/v1/emergency-contacts",
        json={
            "display_name": "Chị Lan",
            "relationship_label": "Con gái",
            "phone_e164": "+84901234567",
            "priority": 2,
        },
    )
    assert created.status_code == 201
    contact_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/emergency-contacts/{contact_id}", json={"priority": 1, "phone_e164": "+84907654321"}
    )
    assert updated.status_code == 200
    assert (updated.json()["priority"], updated.json()["phone_e164"]) == (1, "+84907654321")
    assert (await client.get("/api/v1/emergency-contacts")).json()["items"][0]["id"] == contact_id

    deactivated = await client.delete(f"/api/v1/emergency-contacts/{contact_id}")
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", ["0901234567", "+012345678", "+84abc", "+1234567", "+1234567890123456"])
async def test_invalid_e164_contact_is_rejected(client, phone):
    response = await client.post(
        "/api/v1/emergency-contacts",
        json={"display_name": "Invalid", "phone_e164": phone, "priority": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_contact_management_uses_existing_permission_model(client):
    app.dependency_overrides[current_user] = lambda: {
        "role": "caregiver",
        "force_password_change": False,
        "permissions": {"manage_persons": False},
    }
    response = await client.get("/api/v1/emergency-contacts")
    assert response.status_code == 403
