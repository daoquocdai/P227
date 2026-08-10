import json
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.database import database_connection
from src.models.schemas import AlertReviewRequest, VisionEventAccepted, VisionEventRequest


class EventNotFoundError(Exception):
    pass


def stable_uuid(value: str, category: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"guardiancam:{category}:{value}"))


class SQLiteEventRepository:
    def create(self, event: VisionEventRequest, description: str) -> VisionEventAccepted:
        event_id = stable_uuid(event.event_id, "event")
        camera_id = stable_uuid(event.camera_id, "camera")
        alert_id = stable_uuid(event.event_id, "alert")
        db_event_type = "fall_suspected" if event.event_type.startswith("FALL_") else "person_detected"
        alert_type = (
            "fall"
            if db_event_type == "fall_suspected"
            else "unknown_person"
            if event.event_type == "UNKNOWN_PERSON"
            else None
        )
        metadata = dict(event.metadata)
        metadata.update(
            {
                "external_event_id": event.event_id,
                "source_event_type": event.event_type,
                "description": description,
                "identity_name": event.identity_name,
                "snapshot_path": event.snapshot_path,
            }
        )

        with database_connection() as connection:
            existing = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
            if existing:
                row = connection.execute("SELECT id, status FROM alerts WHERE event_id = ?", (event_id,)).fetchone()
                return VisionEventAccepted(
                    id=row["id"] if row else event_id,
                    event_id=event.event_id,
                    duplicate=True,
                    status=self._ui_status(row["status"], None) if row else "resolved",
                )

            connection.execute(
                """INSERT OR IGNORE INTO cameras
                   (id, name, source_type, source_reference, location_label, operational_status, last_seen_at)
                   VALUES (?, ?, 'webcam', ?, ?, 'online', ?)""",
                (camera_id, event.camera_id, event.camera_id, event.camera_location, event.occurred_at.isoformat()),
            )
            connection.execute(
                """INSERT INTO events
                   (id, camera_id, event_type, occurred_at, ai_model_name, ai_model_version,
                    ai_confidence, metadata_json)
                   VALUES (?, ?, ?, ?, 'guardian-vision', 'baseline', ?, ?)""",
                (
                    event_id,
                    camera_id,
                    db_event_type,
                    event.occurred_at.isoformat(),
                    event.confidence,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )

            if event.track_id:
                identity_type = "known" if event.identity_status == "KNOWN" else "unknown"
                person_id = self._ensure_person(connection, event) if identity_type == "known" else None
                connection.execute(
                    """INSERT INTO event_persons
                       (id, event_id, person_id, track_id, identity_type, ai_confidence,
                        first_seen_at, last_seen_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        event_id,
                        person_id,
                        event.track_id,
                        identity_type,
                        event.confidence,
                        event.occurred_at.isoformat(),
                        event.occurred_at.isoformat(),
                    ),
                )
            elif alert_type == "unknown_person":
                connection.execute(
                    """INSERT INTO event_persons
                       (id, event_id, track_id, identity_type, ai_confidence, first_seen_at, last_seen_at)
                       VALUES (?, ?, ?, 'unknown', ?, ?, ?)""",
                    (
                        str(uuid4()),
                        event_id,
                        "untracked",
                        event.confidence,
                        event.occurred_at.isoformat(),
                        event.occurred_at.isoformat(),
                    ),
                )

            if db_event_type == "fall_suspected":
                connection.execute(
                    """INSERT INTO fall_event_details
                       (id, event_id, posture, fall_confidence, immobility_duration_ms, algorithm_details_json)
                       VALUES (?, ?, 'lying', ?, ?, ?)""",
                    (
                        str(uuid4()),
                        event_id,
                        event.confidence,
                        round(event.immobile_seconds * 1000) if event.immobile_seconds is not None else None,
                        json.dumps(event.metadata, ensure_ascii=False),
                    ),
                )

            self._insert_media(connection, event_id, event)
            if alert_type is None:
                return VisionEventAccepted(id=event_id, event_id=event.event_id, status="resolved")

            severity = "high" if alert_type == "fall" else "critical"
            connection.execute(
                "INSERT INTO alerts (id, event_id, alert_type, severity, status) VALUES (?, ?, ?, ?, 'open')",
                (alert_id, event_id, alert_type, severity),
            )
            connection.execute(
                "INSERT INTO alert_actions (id, alert_id, action_type, new_status) VALUES (?, ?, 'created', 'open')",
                (str(uuid4()), alert_id),
            )
            return VisionEventAccepted(id=alert_id, event_id=event.event_id, status="pending")

    def list_alerts(self) -> list[dict]:
        query = """
            SELECT a.id, a.event_id, a.alert_type, a.severity, a.status AS db_status, a.is_read,
                   a.created_at, a.updated_at,
                   e.occurred_at, e.ai_confidence, e.metadata_json,
                   c.id AS camera_id, c.name AS camera_name, c.location_label,
                   fed.immobility_duration_ms,
                   (SELECT ma.relative_path FROM media_assets ma
                    WHERE ma.event_id = e.id ORDER BY ma.created_at DESC LIMIT 1) AS snapshot_path,
                   (SELECT aa.human_verdict FROM alert_actions aa
                    WHERE aa.alert_id = a.id AND aa.human_verdict IS NOT NULL
                    ORDER BY aa.created_at DESC, aa.id DESC LIMIT 1) AS verdict,
                   (SELECT aa.note FROM alert_actions aa
                    WHERE aa.alert_id = a.id AND aa.note IS NOT NULL
                    ORDER BY aa.created_at DESC, aa.id DESC LIMIT 1) AS review_note,
                   (SELECT aa.action_type FROM alert_actions aa
                    WHERE aa.alert_id = a.id
                    ORDER BY aa.created_at DESC, aa.id DESC LIMIT 1) AS latest_action
            FROM alerts a
            JOIN events e ON e.id = a.event_id
            JOIN cameras c ON c.id = e.camera_id
            LEFT JOIN fall_event_details fed ON fed.event_id = e.id
            ORDER BY e.occurred_at DESC
        """
        with database_connection() as connection:
            return [self._to_api_alert(row) for row in connection.execute(query).fetchall()]

    def review(self, alert_id: str, review: AlertReviewRequest) -> dict:
        with database_connection() as connection:
            current = connection.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if not current:
                raise EventNotFoundError(alert_id)
            db_status, action_type, verdict = self._review_mapping(review.status)
            # Match SQLite's schema defaults so TEXT timestamp constraints remain
            # chronologically sortable ("...Z" versus Python's "+00:00").
            now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            connection.execute(
                """UPDATE alerts SET status = ?, is_read = 1, updated_at = ?,
                   acknowledged_at = CASE WHEN ? = 'acknowledged' THEN COALESCE(acknowledged_at, ?) ELSE acknowledged_at END,
                   resolved_at = CASE WHEN ? IN ('resolved', 'dismissed') THEN ? ELSE resolved_at END
                   WHERE id = ?""",
                (db_status, now, db_status, now, db_status, now, alert_id),
            )
            connection.execute(
                """INSERT INTO alert_actions
                   (id, alert_id, action_type, previous_status, new_status, human_verdict, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), alert_id, action_type, current["status"], db_status, verdict, review.note),
            )
        return self.get_alert(alert_id)

    def confirm_legacy(self, alert_id: str, feedback: str) -> None:
        status = "false_alarm" if "false" in feedback.lower() else "resolved"
        self.review(alert_id, AlertReviewRequest(status=status, note=feedback))

    def get_alert(self, alert_id: str) -> dict:
        for alert in self.list_alerts():
            if alert["id"] == alert_id:
                return alert
        raise EventNotFoundError(alert_id)

    @staticmethod
    def _ensure_person(connection, event: VisionEventRequest) -> str:
        person_key = event.identity_name or event.track_id or "known-person"
        person_id = stable_uuid(person_key, "person")
        connection.execute(
            "INSERT OR IGNORE INTO persons (id, display_name) VALUES (?, ?)",
            (person_id, event.identity_name or "Người thân"),
        )
        return person_id

    @staticmethod
    def _insert_media(connection, event_id: str, event: VisionEventRequest) -> None:
        if not event.snapshot_path:
            return
        suffix = Path(event.snapshot_path).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix)
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            return
        subject = "fall" if event.event_type.startswith("FALL_") else "scene"
        captured = event.occurred_at.astimezone(UTC)
        connection.execute(
            """INSERT INTO media_assets
               (id, event_id, media_type, subject_type, relative_path, mime_type,
                is_blurred, captured_at, retention_until)
               VALUES (?, ?, 'snapshot', ?, ?, ?, 0, ?, ?)""",
            (
                str(uuid4()),
                event_id,
                subject,
                Path(event.snapshot_path).name,
                mime_type,
                captured.isoformat(),
                (captured + timedelta(days=30)).isoformat(),
            ),
        )

    @classmethod
    def _to_api_alert(cls, row) -> dict:
        metadata = json.loads(row["metadata_json"] or "{}")
        snapshot_path = row["snapshot_path"] or metadata.get("snapshot_path")
        return {
            "id": row["id"],
            "event_id": metadata.get("external_event_id", row["event_id"]),
            "timestamp": row["occurred_at"],
            "event_type": metadata.get("source_event_type", row["alert_type"]),
            "description": metadata.get("description", row["alert_type"]),
            "camera_id": row["camera_name"],
            "camera_location": row["location_label"],
            "confidence": row["ai_confidence"],
            "identity_name": metadata.get("identity_name"),
            "immobile_seconds": (
                row["immobility_duration_ms"] / 1000 if row["immobility_duration_ms"] is not None else None
            ),
            "snapshot_url": f"/snapshots/{Path(snapshot_path).name}" if snapshot_path else None,
            "severity": row["severity"],
            "status": cls._ui_status(row["db_status"], row["verdict"], row["latest_action"]),
            "feedback": row["verdict"],
            "review_note": row["review_note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_read": bool(row["is_read"]),
        }

    def mark_read(self, alert_id: str) -> dict:
        with database_connection() as connection:
            updated = connection.execute("UPDATE alerts SET is_read = 1 WHERE id = ?", (alert_id,))
            if updated.rowcount == 0:
                raise EventNotFoundError(alert_id)
        return self.get_alert(alert_id)

    @staticmethod
    def _ui_status(db_status: str, verdict: str | None, latest_action: str | None = None) -> str:
        if verdict == "false_positive":
            return "false_alarm"
        if db_status == "acknowledged":
            return "need_help" if latest_action == "assigned" else "checking"
        return {"open": "pending", "resolved": "resolved", "dismissed": "safe"}[db_status]

    @staticmethod
    def _review_mapping(ui_status: str) -> tuple[str, str, str | None]:
        return {
            "pending": ("open", "reopened", None),
            "checking": ("acknowledged", "acknowledged", None),
            "need_help": ("acknowledged", "assigned", None),
            "resolved": ("resolved", "resolved", None),
            "safe": ("dismissed", "dismissed", None),
            "false_alarm": ("dismissed", "verdict_recorded", "false_positive"),
        }[ui_status]
