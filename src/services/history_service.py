import json
from pathlib import Path
from typing import Any

from src.database import database_connection
from src.services.media_paths import snapshot_url


class HistoryService:
    def list_events(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT e.*, c.name AS camera_public_id, c.location_label,
                          ep.person_id, ep.identity_type, p.display_name,
                          fed.posture, fed.immobility_duration_ms, fed.fall_confidence,
                          a.id AS alert_id, a.severity, a.status AS alert_status
                   FROM events e
                   JOIN cameras c ON c.id = e.camera_id
                   LEFT JOIN event_persons ep ON ep.id = (
                       SELECT ep2.id FROM event_persons ep2 WHERE ep2.event_id = e.id
                       ORDER BY ep2.first_seen_at LIMIT 1
                   )
                   LEFT JOIN persons p ON p.id = ep.person_id
                   LEFT JOIN fall_event_details fed ON fed.event_id = e.id
                   LEFT JOIN alerts a ON a.event_id = e.id
                   ORDER BY e.occurred_at DESC"""
            ).fetchall()
            return [self._event(connection, row) for row in rows]

    def _event(self, connection, row) -> dict[str, Any]:
        metadata = json.loads(row["metadata_json"] or "{}")
        media = connection.execute(
            """SELECT id, subject_type, is_blurred, relative_path
               FROM media_assets WHERE event_id = ? ORDER BY captured_at""",
            (row["id"],),
        ).fetchall()
        actions = []
        verdict = None
        if row["alert_id"]:
            action_rows = connection.execute(
                """SELECT aa.id, aa.action_type, aa.note, aa.human_verdict, aa.created_at,
                          COALESCE(u.display_name, 'Hệ thống AI') AS actor
                   FROM alert_actions aa LEFT JOIN users u ON u.id = aa.user_id
                   WHERE aa.alert_id = ? ORDER BY aa.created_at, aa.id""",
                (row["alert_id"],),
            ).fetchall()
            actions = [
                {
                    "id": action["id"],
                    "actor": action["actor"],
                    "action": self._action_label(action["action_type"]),
                    "note": action["note"],
                    "verdict": action["human_verdict"],
                    "at": action["created_at"],
                }
                for action in action_rows
            ]
            verdict = next((item["verdict"] for item in reversed(actions) if item["verdict"]), None)

        media_payload = [
            {
                "id": item["id"],
                "subject_type": item["subject_type"],
                "is_blurred": bool(item["is_blurred"]),
                "label": Path(item["relative_path"]).stem,
                "url": snapshot_url(item["relative_path"]),
            }
            for item in media
            if snapshot_url(item["relative_path"]) is not None
        ]
        fallback_snapshot = metadata.get("snapshot_path")
        fallback_url = snapshot_url(fallback_snapshot)
        if not media_payload and fallback_url:
            media_payload.append(
                {
                    "id": f"snapshot-{row['id']}",
                    "subject_type": "fall" if row["event_type"] == "fall_suspected" else "scene",
                    "is_blurred": False,
                    "label": Path(fallback_snapshot).stem,
                    "url": fallback_url,
                }
            )

        public_camera_id = (
            row["camera_public_id"] if row["camera_public_id"].startswith("camera-") else row["camera_id"]
        )
        return {
            "id": row["id"],
            "event_id": metadata.get("external_event_id", row["id"]),
            "kind": row["event_type"],
            "camera_id": public_camera_id,
            "camera_name": f"Camera {row['location_label']}",
            "location": row["location_label"],
            "occurred_at": row["occurred_at"],
            "ended_at": row["ended_at"],
            "confidence": row["ai_confidence"] or 0,
            "model": row["ai_model_name"],
            "model_version": row["ai_model_version"],
            "person": {"id": row["person_id"], "name": row["display_name"]} if row["person_id"] else None,
            "unknown": row["identity_type"] == "unknown",
            "fall": {
                "posture": row["posture"],
                "immobility_ms": row["immobility_duration_ms"] or 0,
                "confidence": row["fall_confidence"],
            }
            if row["posture"]
            else None,
            "alert": {"id": row["alert_id"], "severity": row["severity"], "status": row["alert_status"]}
            if row["alert_id"]
            else None,
            "verdict": verdict,
            "media": media_payload,
            "actions": actions,
        }

    @staticmethod
    def _action_label(action: str) -> str:
        return {
            "created": "Đã tạo cảnh báo",
            "acknowledged": "Đã xác nhận xem cảnh báo",
            "assigned": "Đã yêu cầu hỗ trợ",
            "commented": "Đã thêm ghi chú",
            "resolved": "Đã xử lý cảnh báo",
            "dismissed": "Đã đánh dấu an toàn",
            "reopened": "Đã mở lại cảnh báo",
            "verdict_recorded": "Đã ghi nhận cảnh báo sai",
        }.get(action, action)


history_service = HistoryService()
