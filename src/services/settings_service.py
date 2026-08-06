import json
from typing import Any
from uuid import uuid4

from src.database import database_connection

PERMISSIONS = (
    "view_history",
    "acknowledge_alert",
    "resolve_alert",
    "manage_cameras",
    "manage_persons",
    "manage_users",
)


class SettingsNotFoundError(Exception):
    pass


class SettingsConflictError(Exception):
    pass


class SettingsService:
    def get(self) -> dict[str, Any]:
        with database_connection() as connection:
            settings = {
                row["setting_key"]: json.loads(row["value_json"])
                for row in connection.execute("SELECT setting_key, value_json FROM system_settings")
            }
            users = connection.execute("SELECT * FROM users ORDER BY role, display_name").fetchall()
            cameras = connection.execute(
                """SELECT c.id, c.name, c.location_label, c.operational_status, c.last_seen_at,
                          c.is_active, COALESCE(cs.source_kind, c.source_type) AS source_kind
                   FROM cameras c LEFT JOIN camera_sources cs ON cs.camera_id = c.id ORDER BY c.name"""
            ).fetchall()
            return {
                "general": settings["general"],
                "notifications": settings["notifications"],
                "users": [self._user(connection, user) for user in users],
                "cameras": [dict(camera) | {"is_active": bool(camera["is_active"])} for camera in cameras],
            }

    def update_group(self, group: str, values: dict[str, Any]) -> dict[str, Any]:
        if group not in {"general", "notifications"}:
            raise SettingsNotFoundError(group)
        with database_connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM system_settings WHERE setting_key = ?", (group,)
            ).fetchone()
            current = json.loads(row["value_json"])
            current.update(values)
            connection.execute(
                """UPDATE system_settings SET value_json = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE setting_key = ?""",
                (json.dumps(current, ensure_ascii=False), group),
            )
        return self.get()[group]

    def create_user(self, data) -> dict[str, Any]:
        user_id = str(uuid4())
        try:
            with database_connection() as connection:
                connection.execute(
                    "INSERT INTO users (id, email, display_name, role) VALUES (?, ?, ?, ?)",
                    (user_id, data.email.strip(), data.name.strip(), data.role),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise SettingsConflictError(data.email) from exc
            raise
        return next(user for user in self.get()["users"] if user["id"] == user_id)

    def update_user(self, user_id: str, active: bool) -> dict[str, Any]:
        with database_connection() as connection:
            user = connection.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                raise SettingsNotFoundError(user_id)
            if user["role"] == "admin" and user["is_active"] and not active:
                active_admins = connection.execute(
                    "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
                ).fetchone()[0]
                if active_admins <= 1:
                    raise SettingsConflictError("last_admin")
            connection.execute(
                "UPDATE users SET is_active = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (int(active), user_id),
            )
        return next(user for user in self.get()["users"] if user["id"] == user_id)

    def update_permission(self, user_id: str, permission: str, granted: bool) -> dict[str, Any]:
        if permission not in PERMISSIONS:
            raise SettingsNotFoundError(permission)
        with database_connection() as connection:
            user = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                raise SettingsNotFoundError(user_id)
            if user["role"] == "admin":
                raise SettingsConflictError("admin_permissions")
            connection.execute(
                """INSERT INTO user_permissions (id, user_id, permission_key, is_granted)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, permission_key) DO UPDATE SET is_granted = excluded.is_granted,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                (str(uuid4()), user_id, permission, int(granted)),
            )
        return next(user for user in self.get()["users"] if user["id"] == user_id)

    def update_camera(self, camera_id: str, active: bool) -> dict[str, Any]:
        with database_connection() as connection:
            updated = connection.execute(
                "UPDATE cameras SET is_active = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? OR name = ?",
                (int(active), camera_id, camera_id),
            )
            if updated.rowcount == 0:
                raise SettingsNotFoundError(camera_id)
        return self.get()

    @staticmethod
    def _user(connection, user) -> dict[str, Any]:
        permissions = {key: user["role"] == "admin" for key in PERMISSIONS}
        if user["role"] != "admin":
            permissions.update(
                {
                    row["permission_key"]: bool(row["is_granted"])
                    for row in connection.execute(
                        "SELECT permission_key, is_granted FROM user_permissions WHERE user_id = ?", (user["id"],)
                    )
                }
            )
        return {
            "id": user["id"],
            "name": user["display_name"],
            "email": user["email"],
            "role": user["role"],
            "active": bool(user["is_active"]),
            "created_at": user["created_at"],
            "permissions": permissions,
        }


settings_service = SettingsService()
