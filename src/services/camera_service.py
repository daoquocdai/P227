import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.database import database_connection


class CameraNotFoundError(Exception):
    pass


class CameraConflictError(Exception):
    pass


class CameraService:
    def identity_enabled_state(self, camera_id: str) -> bool | None:
        """Return the persisted unknown-detection gate, or None for external cameras."""
        with database_connection() as connection:
            row = connection.execute(
                "SELECT config_json FROM camera_sources WHERE camera_id = ?",
                (camera_id,),
            ).fetchone()
        return None if row is None else self._identity_enabled(row["config_json"])

    def list_cameras(self, runtime=None, vision=None, frame_hub=None) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(self._camera_query() + " ORDER BY c.name").fetchall()
            return [self._camera(row, runtime, vision, frame_hub) for row in rows]

    def get_camera(self, camera_id: str, runtime=None, vision=None, frame_hub=None) -> dict[str, Any]:
        with database_connection() as connection:
            row = connection.execute(
                self._camera_query() + " WHERE c.id = ? OR c.name = ?", (camera_id, camera_id)
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            camera = self._camera(row, runtime, vision, frame_hub)
            camera["events"] = self._events(connection, row["id"])
            return camera

    def resolve_source(self, camera_id: str) -> tuple[str, str | int]:
        """Return the public runtime id and OpenCV source for a persisted camera."""
        with database_connection() as connection:
            row = connection.execute(
                self._camera_query() + " WHERE c.id = ? OR c.name = ?", (camera_id, camera_id)
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)

        public_id = self._public_id(row)
        kind = row["source_kind"] or "webcam"
        source_uri = row["source_uri"]
        if kind == "webcam":
            source = "0" if source_uri in {None, ""} else source_uri
            return public_id, int(source) if str(source).strip().isdigit() else str(source).strip()
        if not source_uri:
            raise ValueError(f"Camera {public_id} has no configured source URI")
        if kind == "rtsp":
            return public_id, source_uri

        relative = Path(source_uri.replace("/", str(Path("/"))))
        candidates = [Path.cwd() / relative, Path.cwd() / "frontend" / "public" / relative]
        for candidate in candidates:
            if candidate.is_file():
                return public_id, str(candidate.resolve())
        raise ValueError(f"Video source does not exist: {source_uri}")

    def source_kind(self, camera_id: str) -> str:
        with database_connection() as connection:
            row = connection.execute(
                """SELECT cs.source_kind FROM cameras c
                   LEFT JOIN camera_sources cs ON cs.camera_id = c.id
                   WHERE c.id = ? OR c.name = ?""",
                (camera_id, camera_id),
            ).fetchone()
        if not row:
            raise CameraNotFoundError(camera_id)
        return row["source_kind"] or "webcam"

    def public_id(self, camera_id: str) -> str:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT id, name FROM cameras WHERE id = ? OR name = ?", (camera_id, camera_id)
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            return self._public_id(row)

    def desired_states(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(self._camera_query() + " ORDER BY c.created_at, c.id").fetchall()
            return [
                {
                    "id": self._public_id(row),
                    "camera_enabled": bool(row["is_active"]),
                    "vision_enabled": bool(row["vision_enabled"]),
                    "loop_video": self._loop_video(row["config_json"]),
                    "identity_enabled": self._identity_enabled(row["config_json"]),
                }
                for row in rows
            ]

    def set_camera_enabled(self, camera_id: str, enabled: bool) -> None:
        self._set_desired(camera_id, "is_active", enabled)

    def set_vision_enabled(self, camera_id: str, enabled: bool) -> None:
        self._set_desired(camera_id, "vision_enabled", enabled)

    def set_identity_enabled(self, camera_id: str, enabled: bool) -> None:
        with database_connection() as connection:
            row = connection.execute(
                """SELECT c.id, cs.config_json FROM cameras c
                   LEFT JOIN camera_sources cs ON cs.camera_id = c.id
                   WHERE c.id = ? OR c.name = ?""",
                (camera_id, camera_id),
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            config = self._config(row["config_json"])
            config["identity_enabled"] = bool(enabled)
            connection.execute(
                """UPDATE camera_sources SET config_json = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE camera_id = ?""",
                (json.dumps(config), row["id"]),
            )

    @staticmethod
    def _set_desired(camera_id: str, column: str, enabled: bool) -> None:
        with database_connection() as connection:
            updated = connection.execute(
                f"UPDATE cameras SET {column} = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ? OR name = ?",
                (int(enabled), camera_id, camera_id),
            )
            if updated.rowcount == 0:
                raise CameraNotFoundError(camera_id)

    def update_source(
        self,
        camera_id: str,
        source_kind: str,
        source_uri: str | None,
        playback_path: str | None,
    ) -> dict[str, Any]:
        self._validate_source(source_kind, source_uri, playback_path)
        with database_connection() as connection:
            row = connection.execute(
                "SELECT id FROM cameras WHERE id = ? OR name = ?", (camera_id, camera_id)
            ).fetchone()
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

    def update_details(
        self,
        camera_id: str,
        *,
        name: str,
        location: str,
        source_kind: str,
        source_uri: str | None,
        playback_path: str | None,
    ) -> None:
        self._validate_source(source_kind, source_uri, playback_path)
        try:
            with database_connection() as connection:
                row = connection.execute(
                    "SELECT id FROM cameras WHERE id = ? OR name = ?", (camera_id, camera_id)
                ).fetchone()
                if not row:
                    raise CameraNotFoundError(camera_id)
                connection.execute(
                    """UPDATE cameras SET name = ?, location_label = ?,
                       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                    (name.strip(), location.strip(), row["id"]),
                )
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
        except Exception as exc:
            if "UNIQUE constraint failed: cameras.name" in str(exc):
                raise CameraConflictError(name) from exc
            raise

    def delete_inactive(self, camera_id: str) -> None:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT id, is_active FROM cameras WHERE id = ? OR name = ?", (camera_id, camera_id)
            ).fetchone()
            if not row:
                raise CameraNotFoundError(camera_id)
            if row["is_active"]:
                raise CameraConflictError("active_camera")
            if connection.execute("SELECT 1 FROM events WHERE camera_id = ? LIMIT 1", (row["id"],)).fetchone():
                raise CameraConflictError("camera_has_history")
            try:
                connection.execute("DELETE FROM inference_metrics WHERE camera_id = ?", (row["id"],))
                connection.execute("DELETE FROM frame_metrics WHERE camera_id = ?", (row["id"],))
                connection.execute("DELETE FROM cameras WHERE id = ?", (row["id"],))
            except Exception as exc:
                if "FOREIGN KEY constraint failed" in str(exc):
                    raise CameraConflictError("camera_has_history") from exc
                raise

    @staticmethod
    def _camera_query() -> str:
        return """
            SELECT c.id, c.name, c.location_label, c.operational_status, c.last_seen_at,
                   c.is_active, c.vision_enabled, cs.source_kind, cs.source_uri,
                   cs.playback_path, cs.config_json, c.created_at
            FROM cameras c LEFT JOIN camera_sources cs ON cs.camera_id = c.id
        """

    @classmethod
    def _camera(cls, row, runtime=None, vision=None, frame_hub=None) -> dict[str, Any]:
        public_id = cls._public_id(row)
        runtime_state = runtime.get_status(public_id) if runtime is not None else None
        vision_state = vision.get_status(public_id) if vision is not None else None
        packet = frame_hub.get_latest(public_id) if frame_hub is not None else None
        status = runtime_state["status"] if runtime_state is not None else "offline"
        runtime_last_frame = runtime_state["last_frame_at"] if runtime_state is not None else None
        last_seen_at = (
            datetime.fromtimestamp(runtime_last_frame, UTC).isoformat()
            if runtime_last_frame is not None
            else row["last_seen_at"]
        )
        return {
            "id": public_id,
            "name": row["name"],
            "location": row["location_label"] or row["name"],
            "status": status,
            "error": "Không thể mở nguồn camera đã cấu hình" if runtime_state and runtime_state.get("error") else None,
            "last_seen_at": last_seen_at,
            "active": bool(row["is_active"]),
            "vision_enabled": bool(row["vision_enabled"]),
            "vision_status": None if vision_state is None else vision_state["status"],
            "identity_enabled": cls._identity_enabled(row["config_json"]),
            "source_kind": row["source_kind"] or "webcam",
            "source": cls._source_label(row["source_kind"], row["source_uri"]),
            "playback_url": cls._playback_url(row["source_kind"], row["playback_path"]),
            "stream_url": f"/api/v1/cameras/{public_id}/stream",
            "stream_ready": status == "online" and runtime_state is not None,
            "preview_url": f"/api/v1/cameras/{public_id}/preview" if packet is not None else None,
            "preview_version": None if packet is None else packet.frame_id,
        }

    @staticmethod
    def _source_label(source_kind: str | None, source_uri: str | None) -> str:
        if source_kind == "rtsp":
            return "RTSP"
        if source_kind == "webcam":
            return f"Webcam {source_uri or '0'}"
        return source_uri or "Video file"

    @staticmethod
    def _loop_video(config_json: str | None) -> bool:
        return bool(CameraService._config(config_json).get("loop_video", True))

    @staticmethod
    def _identity_enabled(config_json: str | None) -> bool:
        return bool(CameraService._config(config_json).get("identity_enabled", False))

    @staticmethod
    def _config(config_json: str | None) -> dict:
        if not config_json:
            return {}
        try:
            value = json.loads(config_json)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _public_id(row) -> str:
        return row["name"] if row["name"].startswith("camera-") else row["id"]

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
