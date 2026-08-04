import json
from pathlib import PurePosixPath
from typing import Any

from src.database import database_connection


class CameraNotFoundError(Exception):
    pass


class CameraService:
    def list_cameras(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(self._camera_query() + " ORDER BY c.name").fetchall()
            return [self._camera(row) for row in rows]

    def get_camera(self, camera_id: str) -> dict[str, Any]:
        with database_connection() as connection:
            row = connection.execute(
                self._camera_query() + " WHERE c.id = ? OR c.name = ?", (camera_id, camera_id)
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            camera = self._camera(row)
            camera["events"] = self._events(connection, row["id"])
            return camera

    def update_source(
        self,
        camera_id: str,
        source_kind: str,
        source_uri: str | None,
        playback_path: str | None,
    ) -> dict[str, Any]:
        self._validate_source(source_kind, source_uri, playback_path)
        with database_connection() as connection:
            row = connection.execute("SELECT id FROM cameras WHERE id = ? OR name = ?", (camera_id, camera_id)).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            connection.execute(
                """INSERT INTO camera_sources (camera_id, source_kind, source_uri, playback_path)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(camera_id) DO UPDATE SET
                     source_kind = excluded.source_kind,
                     source_uri = excluded.source_uri,
                     playback_path = excluded.playback_path,
                     updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                (row["id"], source_kind, source_uri, playback_path),
            )
        return self.get_camera(camera_id)

    @staticmethod
    def _camera_query() -> str:
        return """
            SELECT c.id, c.name, c.location_label, c.operational_status, c.last_seen_at,
                   c.is_active, cs.source_kind, cs.source_uri, cs.playback_path
            FROM cameras c LEFT JOIN camera_sources cs ON cs.camera_id = c.id
        """

    @classmethod
    def _camera(cls, row) -> dict[str, Any]:
        public_id = row["name"] if row["name"].startswith("camera-") else row["id"]
        return {
            "id": public_id,
            "name": row["location_label"] or row["name"],
            "location": row["location_label"],
            "status": row["operational_status"],
            "last_seen_at": row["last_seen_at"],
            "active": bool(row["is_active"]),
            "source_kind": row["source_kind"] or "webcam",
            "playback_url": cls._playback_url(row["source_kind"], row["playback_path"]),
            "stream_ready": row["operational_status"] == "online" and (
                row["source_kind"] == "webcam" or bool(row["playback_path"])
            ),
        }

    @staticmethod
    def _playback_url(source_kind: str | None, playback_path: str | None) -> str | None:
        # source_uri is intentionally private (it may contain RTSP credentials).
        # playback_path is the browser-safe output produced/served by the hub.
        if source_kind not in {"video_file", "rtsp"} or not playback_path:
            return None
        return f"/{playback_path.lstrip('/')}"

    @staticmethod
    def _events(connection, db_camera_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """SELECT e.id, e.event_type, e.occurred_at, e.ai_confidence, e.metadata_json,
                      a.id AS alert_id, a.severity, a.status
               FROM events e LEFT JOIN alerts a ON a.event_id = e.id
               WHERE e.camera_id = ? ORDER BY e.occurred_at DESC LIMIT 100""",
            (db_camera_id,),
        ).fetchall()
        events = []
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            source_type = metadata.get("source_event_type", row["event_type"])
            events.append(
                {
                    "id": row["alert_id"] or row["id"],
                    "event_id": metadata.get("external_event_id", row["id"]),
                    "event_type": source_type,
                    "title": CameraService._event_title(source_type),
                    "description": metadata.get("description", CameraService._event_title(source_type)),
                    "occurred_at": row["occurred_at"],
                    "severity": row["severity"] or "low",
                    "status": row["status"] or "resolved",
                    "confidence": row["ai_confidence"],
                }
            )
        return events

    @staticmethod
    def _event_title(event_type: str) -> str:
        if "FALL" in event_type.upper() or event_type == "fall_suspected":
            return "Có khả năng té ngã"
        if "UNKNOWN" in event_type.upper():
            return "Phát hiện người lạ"
        if "RECOGNIZED" in event_type.upper():
            return "Đã nhận diện người thân"
        return "Phát hiện người"

    @staticmethod
    def _validate_source(source_kind: str, source_uri: str | None, playback_path: str | None) -> None:
        if source_kind == "rtsp" and (not source_uri or not source_uri.lower().startswith("rtsp://")):
            raise ValueError("RTSP source must start with rtsp://")
        if source_kind == "video_file":
            if not source_uri or not playback_path:
                raise ValueError("Video source requires source_uri and playback_path")
        for value in (source_uri if source_kind == "video_file" else None, playback_path):
            if value is None:
                continue
            path = PurePosixPath(value.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Playback and video paths must be relative and cannot contain '..'")


camera_service = CameraService()
