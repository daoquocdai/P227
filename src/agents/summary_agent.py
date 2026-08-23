from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from src.config import get_settings
from src.database import database_connection

logger = logging.getLogger(__name__)


class IncidentSummaryAgent:
    """Agent tóm tắt diễn biến sự cố và tự động khởi tạo Timeline chi tiết."""

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key

    async def generate_summary(self, incident_id: str) -> dict[str, Any]:
        """Tạo timeline và tóm tắt cho một incident_id cụ thể."""
        inc_data = await asyncio.to_thread(self._fetch_incident_events, incident_id)
        if not inc_data or not inc_data.get("incident"):
            return {"success": False, "error": "Incident not found", "incident_id": incident_id}

        incident = inc_data["incident"]
        events = inc_data["events"]

        # Build timeline entries
        timeline = self._build_timeline(incident, events)

        # Generate summary text
        summary_text = self._generate_summary_text(incident, events, timeline)

        # Persist summary back to database
        await asyncio.to_thread(self._save_summary, incident_id, summary_text, incident.get("version", 1))

        return {
            "success": True,
            "incident_id": incident_id,
            "incident_type": incident.get("incident_type"),
            "status": incident.get("status"),
            "summary": summary_text,
            "timeline": timeline,
        }

    @staticmethod
    def _fetch_incident_events(incident_id: str) -> dict[str, Any] | None:
        with database_connection() as conn:
            inc = conn.execute(
                """SELECT i.*, c.name as camera_name, c.location_label, a.severity, a.status as alert_status
                   FROM incidents i
                   JOIN cameras c ON c.id = i.camera_id
                   LEFT JOIN alerts a ON a.incident_id = i.id
                   WHERE i.id = ?""",
                (incident_id,),
            ).fetchone()
            if not inc:
                return None

            events = conn.execute(
                """SELECT e.id, e.event_type, e.occurred_at, e.ai_confidence, e.metadata_json,
                          f.posture, f.immobility_duration_ms, f.fall_confidence
                   FROM incident_events ie
                   JOIN events e ON e.id = ie.event_id
                   LEFT JOIN fall_event_details f ON f.event_id = e.id
                   WHERE ie.incident_id = ?
                   ORDER BY e.occurred_at ASC""",
                (incident_id,),
            ).fetchall()

            return {"incident": dict(inc), "events": [dict(e) for e in events]}

    @staticmethod
    def _build_timeline(incident: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, str]]:
        timeline = []
        opened_at = incident.get("opened_at", "")
        cam_name = incident.get("camera_name", "Camera")
        location = incident.get("location_label", "chưa xác định")

        # Start event
        timeline.append(
            {
                "timestamp": opened_at,
                "title": "Sự cố được kích hoạt",
                "description": f"Phát hiện sự cố loại '{incident.get('incident_type')}' lần đầu tại {cam_name} ({location}).",
            }
        )

        # Intermediate events
        for idx, evt in enumerate(events, start=1):
            meta = json.loads(evt.get("metadata_json") or "{}")
            posture = evt.get("posture") or meta.get("posture", "chưa rõ")
            conf = evt.get("ai_confidence") or 0.0

            desc = f"Khung hình #{idx}: Độ tin cậy AI {conf:.2f}."
            if incident.get("incident_type") == "fall":
                desc += f" Tư thế người dùng: {posture}."
                if evt.get("immobility_duration_ms"):
                    desc += f" Thời gian bất động: {evt['immobility_duration_ms'] // 1000}s."

            timeline.append(
                {
                    "timestamp": evt.get("occurred_at", ""),
                    "title": f"Cập nhật sự kiện #{idx}",
                    "description": desc,
                }
            )

        # End or current status event
        last_seen = incident.get("last_seen_at", opened_at)
        timeline.append(
            {
                "timestamp": last_seen,
                "title": f"Trạng thái hiện tại: {incident.get('status')}",
                "description": f"Ghi nhận tín hiệu cuối cùng lúc {last_seen}. Tổng số lần lặp lại: {incident.get('occurrence_count', 1)}.",
            }
        )

        return timeline

    @staticmethod
    def _generate_summary_text(
        incident: dict[str, Any], events: list[dict[str, Any]], timeline: list[dict[str, str]]
    ) -> str:
        inc_type = incident.get("incident_type")
        location = incident.get("location_label", "chưa xác định")
        count = incident.get("occurrence_count", 1)
        raw_severity = incident.get("severity") or "medium"
        severity = raw_severity.upper()


        if inc_type == "fall":
            max_immobility = max([e.get("immobility_duration_ms") or 0 for e in events] or [0])
            summary = (
                f"TÓM TẮT SỰ CỐ TÉ NGÃ [{severity}]: "
                f"Sự cố té ngã xảy ra tại {location} với {count} lượt ghi nhận. "
            )
            if max_immobility > 0:
                summary += f"Thời gian nằm bất động tối đa quan sát được là {max_immobility // 1000} giây. "
            summary += f"Hiện tại sự cố đang ở trạng thái {incident.get('status')}."

        elif inc_type == "unknown_person":
            summary = (
                f"TÓM TẮT SỰ CỐ NGƯỜI LẠ [{severity}]: "
                f"Phát hiện đối tượng chưa xác định danh tính xuất hiện {count} lần tại {location}. "
                f"Khung hình phát hiện đầu lúc {incident.get('opened_at')}, cuồi lúc {incident.get('last_seen_at')}. "
                f"Trạng thái: {incident.get('status')}."
            )
        else:
            summary = f"Tóm tắt sự cố {inc_type} tại {location}: Trạng thái {incident.get('status')} với {count} sự kiện."

        return summary

    @staticmethod
    def _save_summary(incident_id: str, summary_text: str, version: int) -> None:
        with database_connection() as conn:
            conn.execute(
                """UPDATE incidents
                   SET agent_summary = ?, summary_version = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE id = ?""",
                (summary_text, version, incident_id),
            )
            conn.execute(
                """INSERT INTO incident_actions (id, incident_id, action_type, incident_version, note)
                   VALUES (?, ?, 'agent_summary_applied', ?, ?)""",
                (str(uuid4()), incident_id, version, summary_text),
            )
