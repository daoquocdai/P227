from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from src.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class IncidentCorrelationResult:
    incident_id: str
    version: int
    occurrence_count: int
    created: bool = False
    updated: bool = False
    suppressed: bool = False
    review_required: bool = False


class IncidentCoordinator:
    """Deterministic Event-to-Incident correlation inside the Event transaction."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.milestones = {
            int(value.strip())
            for value in self.settings.alert_agent_review_milestones.split(",")
            if value.strip().isdigit() and int(value.strip()) > 0
        }

    def correlate(
        self,
        connection,
        *,
        event_id: str,
        camera_id: str,
        incident_type: str,
        occurred_at: str,
        track_id: str | None,
        metadata: dict,
    ) -> IncidentCorrelationResult:
        source_session = str(metadata.get("source_session") or f"legacy:{metadata.get('source_epoch', 0)}")
        episode_key = str(metadata.get("incident_id") or "") or None
        if incident_type == "unknown_person" and not track_id:
            track_id = "untracked"

        resolved = self._matching(
            connection, camera_id, incident_type, track_id, source_session, episode_key, resolved=True
        )
        if resolved and self._same_resolved_episode(incident_type, resolved, track_id, source_session, episode_key):
            connection.execute(
                "INSERT INTO incident_events (incident_id,event_id,disposition) VALUES (?,?,'suppressed_after_resolution')",
                (resolved["id"], event_id),
            )
            self._action(
                connection,
                resolved["id"],
                "event_suppressed",
                event_id,
                resolved["version"],
                "same episode after RESOLVED_SAFE",
            )
            return IncidentCorrelationResult(
                resolved["id"], resolved["version"], resolved["occurrence_count"], suppressed=True
            )

        active = self._matching(
            connection, camera_id, incident_type, track_id, source_session, episode_key, resolved=False
        )
        merge_seconds = (
            self.settings.unknown_incident_merge_seconds
            if incident_type == "unknown_person"
            else self.settings.fall_incident_merge_seconds
        )
        if active and self._within_window(active["last_seen_at"], occurred_at, merge_seconds):
            version = active["version"] + 1
            count = active["occurrence_count"] + 1
            connection.execute(
                """UPDATE incidents SET last_seen_at=?, occurrence_count=?, version=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id=? AND status IN ('OPEN','ACKNOWLEDGED')""",
                (occurred_at, count, version, active["id"]),
            )
            connection.execute(
                "INSERT INTO incident_events (incident_id,event_id) VALUES (?,?)", (active["id"], event_id)
            )
            self._action(connection, active["id"], "occurrence_attached", event_id, version, None)
            return IncidentCorrelationResult(
                active["id"], version, count, updated=True, review_required=count in self.milestones
            )

        incident_id = str(uuid4())
        connection.execute(
            """INSERT INTO incidents
               (id,camera_id,incident_type,status,opened_at,last_seen_at,occurrence_count,track_id,source_session,episode_key,version)
               VALUES (?,?,?,'OPEN',?,?,1,?,?,?,1)""",
            (incident_id, camera_id, incident_type, occurred_at, occurred_at, track_id, source_session, episode_key),
        )
        connection.execute("INSERT INTO incident_events (incident_id,event_id) VALUES (?,?)", (incident_id, event_id))
        self._action(connection, incident_id, "created", event_id, 1, None)
        return IncidentCorrelationResult(incident_id, 1, 1, created=True, review_required=1 in self.milestones)

    @staticmethod
    def _matching(connection, camera_id, incident_type, track_id, source_session, episode_key, *, resolved):
        status = "= 'RESOLVED_SAFE'" if resolved else "IN ('OPEN','ACKNOWLEDGED')"
        if incident_type == "unknown_person":
            extra, args = "track_id=? AND source_session=?", (track_id, source_session)
        elif episode_key:
            extra, args = "episode_key=? AND source_session=?", (episode_key, source_session)
        else:
            extra, args = "source_session=?", (source_session,)
        return connection.execute(
            f"SELECT * FROM incidents WHERE camera_id=? AND incident_type=? AND status {status} AND {extra} ORDER BY last_seen_at DESC LIMIT 1",
            (camera_id, incident_type, *args),
        ).fetchone()

    @staticmethod
    def _same_resolved_episode(incident_type, row, track_id, source_session, episode_key):
        if row["source_session"] != source_session:
            return False
        return (
            row["track_id"] == track_id
            if incident_type == "unknown_person"
            else bool(episode_key and row["episode_key"] == episode_key)
        )

    @staticmethod
    def _within_window(previous: str, current: str, seconds: int) -> bool:
        try:
            return datetime.fromisoformat(current.replace("Z", "+00:00")) - datetime.fromisoformat(
                previous.replace("Z", "+00:00")
            ) <= timedelta(seconds=seconds)
        except ValueError:
            return False

    @staticmethod
    def _action(connection, incident_id, action_type, event_id, version, note):
        connection.execute(
            "INSERT INTO incident_actions (id,incident_id,action_type,event_id,incident_version,note) VALUES (?,?,?,?,?,?)",
            (str(uuid4()), incident_id, action_type, event_id, version, note),
        )
