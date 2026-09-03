import json
import logging
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.config import get_settings
from src.database import database_connection
from src.models.schemas import AlertReviewRequest, VisionEventAccepted, VisionEventRequest
from src.services.event_presentation import event_description
from src.services.incident_coordinator import IncidentCoordinator
from src.services.media_paths import snapshot_url, valid_snapshot_name

logger = logging.getLogger(__name__)


class EventNotFoundError(Exception):
    pass


def stable_uuid(value: str, category: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"guardiancam:{category}:{value}"))


class SQLiteEventRepository:
    def __init__(self, incident_coordinator: IncidentCoordinator | None = None) -> None:
        self._incidents = incident_coordinator or IncidentCoordinator()

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
        valid_snapshot = valid_snapshot_name(event.snapshot_path)
        privacy_bypass = bool(event.metadata.get("snapshot_privacy_bypass", False))
        privacy_acceptable = bool(event.metadata.get("snapshot_blurred", False)) or (
            get_settings().vision_allow_unblurred_event_snapshot and privacy_bypass
        )
        if event.event_type in {"UNKNOWN_PERSON", "FALL_CONFIRMED"} and not privacy_acceptable:
            valid_snapshot = None
        metadata = dict(event.metadata)
        metadata.update(
            {
                "external_event_id": event.event_id,
                "source_event_type": event.event_type,
                "description": description,
                "identity_name": event.identity_name,
                "snapshot_path": valid_snapshot,
            }
        )

        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            camera = connection.execute(
                "SELECT name, location_label FROM cameras WHERE id = ?", (camera_id,)
            ).fetchone()
            if camera:
                metadata["camera_name"] = camera["name"]
                metadata["camera_location"] = camera["location_label"]
                metadata["description"] = event_description(
                    event.event_type, camera["location_label"], event.identity_name
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

            self._insert_optional_media(connection, event_id, event, valid_snapshot)
            if alert_type is None:
                return VisionEventAccepted(id=event_id, event_id=event.event_id, status="resolved")

            incident = self._incidents.correlate(
                connection,
                event_id=event_id,
                camera_id=camera_id,
                incident_type=alert_type,
                occurred_at=event.occurred_at.isoformat(),
                track_id=event.track_id,
                metadata=metadata,
            )
            if incident.suppressed:
                existing_alert = connection.execute(
                    "SELECT id FROM alerts WHERE incident_id=?", (incident.incident_id,)
                ).fetchone()
                return VisionEventAccepted(
                    id=existing_alert["id"] if existing_alert else event_id,
                    event_id=event.event_id,
                    status="safe",
                    incident_id=incident.incident_id,
                    incident_version=incident.version,
                    occurrence_count=incident.occurrence_count,
                    suppressed=True,
                )
            if incident.updated:
                existing_alert = connection.execute(
                    "SELECT id,status FROM alerts WHERE incident_id=?", (incident.incident_id,)
                ).fetchone()
                connection.execute(
                    "UPDATE alerts SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (existing_alert["id"],),
                )
                return VisionEventAccepted(
                    id=existing_alert["id"],
                    event_id=event.event_id,
                    status=self._ui_status(existing_alert["status"], None),
                    incident_id=incident.incident_id,
                    incident_version=incident.version,
                    occurrence_count=incident.occurrence_count,
                    incident_updated=True,
                    agent_review_required=incident.review_required,
                )

            severity = "critical" if alert_type == "unknown_person" or event.event_type == "FALL_CONFIRMED" else "high"
            connection.execute(
                "INSERT INTO alerts (id, event_id, incident_id, alert_type, severity, status) VALUES (?, ?, ?, ?, ?, 'open')",
                (alert_id, event_id, incident.incident_id, alert_type, severity),
            )
            connection.execute(
                "INSERT INTO alert_actions (id, alert_id, action_type, new_status) VALUES (?, ?, 'created', 'open')",
                (str(uuid4()), alert_id),
            )
            return VisionEventAccepted(
                id=alert_id,
                event_id=event.event_id,
                status="pending",
                incident_id=incident.incident_id,
                incident_version=incident.version,
                occurrence_count=1,
                alert_created=True,
                agent_review_required=incident.review_required,
            )

    def list_alerts(self) -> list[dict]:
        query = """
            SELECT a.id, a.event_id, a.incident_id, a.alert_type, a.severity, a.status AS db_status, a.is_read,
                   a.created_at, a.updated_at,
                   e.occurred_at, e.ai_confidence, e.metadata_json,
                   c.id AS camera_id, c.name AS camera_name, c.location_label,
                   fed.immobility_duration_ms,
                   i.status AS incident_status, i.opened_at AS incident_opened_at,
                   i.last_seen_at AS incident_last_seen_at, i.occurrence_count,
                   i.version AS incident_version, i.agent_summary,
                   i.acknowledged_at AS incident_acknowledged_at,
                   i.help_requested_at AS incident_help_requested_at,
                   i.resolved_at AS incident_resolved_at,
                   EXISTS(SELECT 1 FROM incident_events ie2 JOIN events e2 ON e2.id=ie2.event_id
                    WHERE ie2.incident_id=i.id
                      AND json_extract(e2.metadata_json,'$.source_event_type')='FALL_CONFIRMED') AS fall_confirmed,
                   (SELECT eea.status FROM emergency_escalation_attempts eea
                    WHERE eea.incident_id=i.id AND eea.stage='fall_unconfirmed'
                    ORDER BY CASE eea.status WHEN 'claimed' THEN 0 WHEN 'succeeded' THEN 1 ELSE 2 END,
                             eea.created_at DESC, eea.id DESC LIMIT 1) AS escalation_attempt_status,
                   EXISTS(SELECT 1 FROM emergency_escalation_attempts eea
                    WHERE eea.incident_id=i.id AND eea.stage='fall_unconfirmed'
                      AND eea.status='succeeded') AS escalation_succeeded,
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
                   ,(SELECT ar.status FROM agent_runs ar WHERE ar.alert_id = a.id
                     ORDER BY ar.created_at DESC LIMIT 1) AS agent_status
                   ,(SELECT ar.verdict FROM agent_runs ar WHERE ar.alert_id = a.id
                     ORDER BY ar.created_at DESC LIMIT 1) AS agent_verdict
                   ,(SELECT ar.severity FROM agent_runs ar WHERE ar.alert_id = a.id
                     ORDER BY ar.created_at DESC LIMIT 1) AS agent_severity
                   ,(SELECT ar.reason_summary FROM agent_runs ar WHERE ar.alert_id = a.id
                     ORDER BY ar.created_at DESC LIMIT 1) AS agent_reason_summary
            FROM alerts a
            JOIN events e ON e.id = a.event_id
            JOIN cameras c ON c.id = e.camera_id
            LEFT JOIN fall_event_details fed ON fed.event_id = e.id
            LEFT JOIN incidents i ON i.id = a.incident_id
            ORDER BY e.occurred_at DESC
        """
        with database_connection() as connection:
            return [self._to_api_alert(row) for row in connection.execute(query).fetchall()]

    def review(self, alert_id: str, review: AlertReviewRequest) -> dict:
        with database_connection() as connection:
            current = connection.execute("SELECT status,incident_id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if not current:
                raise EventNotFoundError(alert_id)
            db_status, action_type, verdict = self._review_mapping(review.status)
            # Match SQLite's schema defaults so TEXT timestamp constraints remain
            # chronologically sortable ("...Z" versus Python's "+00:00").
            now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            if current["incident_id"]:
                incident = connection.execute(
                    "SELECT status,version FROM incidents WHERE id=?", (current["incident_id"],)
                ).fetchone()
                if incident["status"] == "RESOLVED_SAFE":
                    return self.get_alert(alert_id)
                if review.status in {"checking", "need_help"}:
                    incident_status = "ACKNOWLEDGED"
                    connection.execute(
                        """UPDATE incidents SET status=?,acknowledged_at=COALESCE(acknowledged_at,?),
                           help_requested_at=CASE WHEN ?='need_help' THEN COALESCE(help_requested_at,?)
                                                  ELSE help_requested_at END,
                           version=version+1,updated_at=? WHERE id=?""",
                        (incident_status, now, review.status, now, now, current["incident_id"]),
                    )
                    self._incident_user_action(
                        connection, current["incident_id"], "acknowledged", incident["version"] + 1, review.note
                    )
                elif review.status in {"safe", "resolved", "false_alarm"}:
                    connection.execute(
                        "UPDATE incidents SET status='RESOLVED_SAFE',resolved_at=?,resolution_reason=?,version=version+1,updated_at=? WHERE id=?",
                        (now, review.note, now, current["incident_id"]),
                    )
                    self._incident_user_action(
                        connection, current["incident_id"], "resolved_safe", incident["version"] + 1, review.note
                    )
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

    def _insert_optional_media(
        self,
        connection,
        event_id: str,
        event: VisionEventRequest,
        snapshot_name: str | None,
    ) -> None:
        """Keep optional visual evidence outside the event/alert failure boundary."""
        if not snapshot_name:
            return
        connection.execute("SAVEPOINT optional_event_media")
        try:
            self._insert_media(connection, event_id, event, snapshot_name)
        except Exception:  # noqa: BLE001 - event delivery must survive evidence failure
            connection.execute("ROLLBACK TO SAVEPOINT optional_event_media")
            logger.exception("Could not persist optional event media event=%s", event.event_id)
        finally:
            connection.execute("RELEASE SAVEPOINT optional_event_media")

    @staticmethod
    def _insert_media(
        connection,
        event_id: str,
        event: VisionEventRequest,
        snapshot_name: str | None,
    ) -> None:
        if not snapshot_name:
            return
        suffix = Path(snapshot_name).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix)
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            return
        unknown = event.event_type == "UNKNOWN_PERSON"
        privacy_blurred = bool(event.metadata.get("snapshot_blurred", False))
        privacy_bypass = bool(event.metadata.get("snapshot_privacy_bypass", False))
        subject = (
            "fall"
            if event.event_type.startswith("FALL_")
            else "scene"
            if unknown and privacy_bypass
            else "unknown_person"
            if unknown
            else "scene"
        )
        captured = event.occurred_at.astimezone(UTC)
        settings_row = connection.execute(
            "SELECT value_json FROM system_settings WHERE setting_key = 'general'"
        ).fetchone()
        retention_days = int(json.loads(settings_row["value_json"]).get("retention_days", 30))
        connection.execute(
            """INSERT INTO media_assets
               (id, event_id, media_type, subject_type, relative_path, mime_type,
                is_blurred, captured_at, retention_until)
               VALUES (?, ?, 'snapshot', ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                event_id,
                subject,
                snapshot_name,
                mime_type,
                int(privacy_blurred),
                captured.isoformat(),
                (captured + timedelta(days=retention_days)).isoformat(),
            ),
        )

    @classmethod
    def _to_api_alert(cls, row) -> dict:
        metadata = json.loads(row["metadata_json"] or "{}")
        snapshot_path = row["snapshot_path"] or metadata.get("snapshot_path")
        source_event_type = metadata.get("source_event_type", row["alert_type"])
        settings = get_settings()
        escalation_enabled = bool(
            settings.fall_escalation_enabled and row["alert_type"] == "fall" and row["fall_confirmed"]
        )
        escalation_due_at = None
        escalation_status = None
        if row["alert_type"] == "fall" and row["fall_confirmed"]:
            opened_at = datetime.fromisoformat((row["incident_opened_at"] or row["occurred_at"]).replace("Z", "+00:00"))
            escalation_due_at = (opened_at + timedelta(seconds=settings.fall_call_after_seconds)).isoformat()
            if row["escalation_succeeded"]:
                escalation_status = "contacted"
            elif not escalation_enabled or row["incident_status"] == "RESOLVED_SAFE":
                escalation_status = "cancelled"
            elif row["escalation_attempt_status"] == "claimed":
                escalation_status = "calling"
            elif row["escalation_attempt_status"] == "failed":
                escalation_status = "failed"
            else:
                escalation_status = "pending"
        product_severity = (
            "critical"
            if row["alert_type"] == "fall"
            and row["fall_confirmed"]
            and row["incident_status"] in {"OPEN", "ACKNOWLEDGED"}
            else row["severity"]
        )
        return {
            "id": row["id"],
            "event_id": metadata.get("external_event_id", row["event_id"]),
            "timestamp": row["occurred_at"],
            "event_type": source_event_type,
            "description": event_description(source_event_type, row["location_label"], metadata.get("identity_name")),
            "camera_id": row["camera_name"],
            "camera_location": row["location_label"],
            "confidence": row["ai_confidence"],
            "identity_name": metadata.get("identity_name"),
            "immobile_seconds": (
                row["immobility_duration_ms"] / 1000 if row["immobility_duration_ms"] is not None else None
            ),
            "snapshot_url": snapshot_url(snapshot_path),
            "severity": product_severity,
            "status": cls._ui_status(row["db_status"], row["verdict"], row["latest_action"]),
            "feedback": row["verdict"],
            "review_note": row["review_note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_read": bool(row["is_read"]),
            "incident_id": row["incident_id"],
            "incident_status": row["incident_status"],
            "occurrence_count": row["occurrence_count"] or 1,
            "first_seen_at": row["incident_opened_at"] or row["occurred_at"],
            "last_seen_at": row["incident_last_seen_at"] or row["occurred_at"],
            "incident_version": row["incident_version"],
            "agent_reason_summary": row["agent_summary"] or row["agent_reason_summary"],
            "acknowledged_at": row["incident_acknowledged_at"],
            "resolved_at": row["incident_resolved_at"],
            "agent_status": row["agent_status"],
            "agent_verdict": row["agent_verdict"],
            "agent_severity": row["agent_severity"],
            "escalation_enabled": escalation_enabled,
            "escalation_due_at": escalation_due_at,
            "escalation_status": escalation_status,
        }

    @staticmethod
    def _incident_user_action(connection, incident_id: str, action_type: str, version: int, note: str | None) -> None:
        connection.execute(
            "INSERT INTO incident_actions (id,incident_id,action_type,incident_version,note) VALUES (?,?,?,?,?)",
            (str(uuid4()), incident_id, action_type, version, note),
        )

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
