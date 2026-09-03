from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.database import database_connection


class EmergencyContactNotFoundError(Exception):
    pass


class EmergencyContactService:
    def list_contacts(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute("SELECT * FROM emergency_contacts ORDER BY priority, created_at, id").fetchall()
            return [self._serialize(row) for row in rows]

    def create_contact(self, data) -> dict[str, Any]:
        contact_id = str(uuid4())
        with database_connection() as connection:
            connection.execute(
                """INSERT INTO emergency_contacts
                   (id, display_name, relationship_label, phone_e164, priority, is_active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    contact_id,
                    data.display_name.strip(),
                    data.relationship_label,
                    data.phone_e164,
                    data.priority,
                    int(data.is_active),
                ),
            )
        return self.get_contact(contact_id)

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        with database_connection() as connection:
            row = connection.execute("SELECT * FROM emergency_contacts WHERE id=?", (contact_id,)).fetchone()
            if row is None:
                raise EmergencyContactNotFoundError(contact_id)
            return self._serialize(row)

    def update_contact(self, contact_id: str, data) -> dict[str, Any]:
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return self.get_contact(contact_id)
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = [int(value) if key == "is_active" else value for key, value in fields.items()]
        with database_connection() as connection:
            updated = connection.execute(
                f"UPDATE emergency_contacts SET {assignments}, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (*values, contact_id),
            )
            if updated.rowcount == 0:
                raise EmergencyContactNotFoundError(contact_id)
        return self.get_contact(contact_id)

    def deactivate_contact(self, contact_id: str) -> dict[str, Any]:
        with database_connection() as connection:
            updated = connection.execute(
                """UPDATE emergency_contacts SET is_active=0,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (contact_id,),
            )
            if updated.rowcount == 0:
                raise EmergencyContactNotFoundError(contact_id)
        return self.get_contact(contact_id)

    @staticmethod
    def _serialize(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "display_name": row["display_name"],
            "relationship_label": row["relationship_label"],
            "phone_e164": row["phone_e164"],
            "priority": row["priority"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


emergency_contact_service = EmergencyContactService()
