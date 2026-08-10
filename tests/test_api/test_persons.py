from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_person_and_face_profile_crud(client):
    name = f"Người thân {uuid4()}"
    created = await client.post(
        "/api/v1/persons",
        json={"name": name, "relationship": "Mẹ", "birth": "1952-08-12", "notes": "Theo dõi tại nhà"},
    )
    assert created.status_code == 201
    person_id = created.json()["id"]
    assert created.json()["faces"] == []

    updated = await client.patch(f"/api/v1/persons/{person_id}", json={"active": False, "notes": "Đã cập nhật"})
    assert updated.status_code == 200
    assert updated.json()["active"] is False
    assert updated.json()["notes"] == "Đã cập nhật"

    with_face = await client.post(f"/api/v1/persons/{person_id}/faces", json={"quality": 0.91, "angle": "Chính diện"})
    assert with_face.status_code == 201
    face_id = with_face.json()["faces"][0]["id"]
    assert with_face.json()["faces"][0]["quality"] == 0.91

    removed = await client.delete(f"/api/v1/persons/{person_id}/faces/{face_id}")
    assert removed.status_code == 200
    assert removed.json()["faces"] == []

    listing = await client.get("/api/v1/persons")
    assert any(person["id"] == person_id for person in listing.json()["items"])
