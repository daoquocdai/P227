from __future__ import annotations

import json
import logging
from typing import Any

from src.database import database_connection

logger = logging.getLogger(__name__)


class QATools:
    """An toàn và bảo mật helper tools cho Q&A Security Assistant."""

    @staticmethod
    def definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "query_events_summary",
                "description": "Lấy tóm tắt và danh sách sự kiện gần đây (té ngã hoặc người lạ) theo số lượng yêu cầu và/hoặc ngày cụ thể.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string", "enum": ["fall_suspected", "person_detected", "all"]},
                        "limit": {"type": "integer", "default": 10},
                        "date": {
                            "type": "string",
                            "description": "Lọc theo ngày định dạng YYYY-MM-DD (ví dụ: '2026-09-01'). Quy đổi 'hôm nay', 'hôm qua' sang YYYY-MM-DD tương ứng.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "query_recent_incidents",
                "description": "Lấy danh sách các sự cố (Incidents) cùng mức độ nghiêm trọng và trạng thái theo loại, ngày cụ thể, tên người thân hoặc gần nhất.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "incident_type": {"type": "string", "enum": ["fall", "unknown_person", "all"]},
                        "status": {"type": "string", "enum": ["OPEN", "ACKNOWLEDGED", "RESOLVED_SAFE", "all"]},
                        "limit": {"type": "integer", "default": 10},
                        "date": {
                            "type": "string",
                            "description": "Lọc theo ngày định dạng YYYY-MM-DD (ví dụ: '2026-09-01'). Quy đổi 'hôm nay', 'hôm qua' sang YYYY-MM-DD tương ứng.",
                        },
                        "person_name": {
                            "type": "string",
                            "description": "Tên người thân cần tra cứu sự cố (ví dụ: 'Mạnh', 'Bà Nội', 'Mẹ', 'Bố').",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "query_camera_status",
                "description": "Lấy danh sách camera hiện có và trạng thái hoạt động của từng camera.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "query_registered_persons",
                "description": "Lấy danh sách người thân đã đăng ký danh tính trong gia đình.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ]

    @staticmethod
    def get_camera_status() -> list[dict[str, Any]]:
        with database_connection() as conn:
            rows = conn.execute(
                """SELECT id, name, location_label, operational_status, vision_enabled, last_seen_at
                   FROM cameras ORDER BY name ASC"""
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _matches_date(iso_str: str | None, target_date: str) -> bool:
        if not iso_str:
            return False
        if str(iso_str).startswith(target_date):
            return True
        try:
            clean_iso = str(iso_str).replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%Y-%m-%d") == target_date
        except Exception:
            return False

    @classmethod
    def get_events_summary(
        cls, event_type: str = "all", limit: int = 10, date: str | None = None
    ) -> list[dict[str, Any]]:
        with database_connection() as conn:
            query = """
                SELECT e.id, e.event_type, e.occurred_at, e.ai_confidence, c.name as camera_name, c.location_label
                FROM events e
                JOIN cameras c ON c.id = e.camera_id
            """
            conditions = []
            args: list[Any] = []
            if event_type != "all":
                conditions.append("e.event_type = ?")
                args.append(event_type)
            if date:
                conditions.append("(e.occurred_at LIKE ? OR date(e.occurred_at) = ?)")
                args.append(f"{date}%")
                args.append(date)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY e.occurred_at DESC"
            if not date:
                query += " LIMIT ?"
                args.append(limit)

            rows = [dict(r) for r in conn.execute(query, tuple(args)).fetchall()]
            if date:
                rows = [r for r in rows if cls._matches_date(r.get("occurred_at"), date)]
                rows = rows[:limit]
            return rows

    @classmethod
    def get_recent_incidents(
        cls,
        incident_type: str = "all",
        status: str = "all",
        limit: int = 10,
        date: str | None = None,
        person_name: str | None = None,
    ) -> list[dict[str, Any]]:
        with database_connection() as conn:
            query = """
                SELECT DISTINCT i.id, i.incident_type, i.status, i.opened_at, i.last_seen_at, i.occurrence_count,
                       i.agent_summary, c.name as camera_name, c.location_label,
                       a.severity as alert_severity
                FROM incidents i
                JOIN cameras c ON c.id = i.camera_id
                LEFT JOIN alerts a ON a.incident_id = i.id
                LEFT JOIN incident_events ie ON ie.incident_id = i.id
                LEFT JOIN events e ON e.id = ie.event_id
                LEFT JOIN event_persons ep ON ep.event_id = e.id
                LEFT JOIN persons p ON p.id = ep.person_id
            """
            conditions = []
            args: list[Any] = []
            if incident_type != "all":
                conditions.append("i.incident_type = ?")
                args.append(incident_type)
            if status != "all":
                conditions.append("i.status = ?")
                args.append(status)
            if date:
                conditions.append("(i.opened_at LIKE ? OR i.last_seen_at LIKE ? OR date(i.opened_at) = ? OR date(i.last_seen_at) = ?)")
                args.append(f"{date}%")
                args.append(f"{date}%")
                args.append(date)
                args.append(date)
            if person_name:
                conditions.append("(p.display_name LIKE ? OR e.metadata_json LIKE ? OR i.agent_summary LIKE ?)")
                args.append(f"%{person_name}%")
                args.append(f"%{person_name}%")
                args.append(f"%{person_name}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY i.last_seen_at DESC"
            if not date and not person_name:
                query += " LIMIT ?"
                args.append(limit)

            rows = [dict(r) for r in conn.execute(query, tuple(args)).fetchall()]
            if date:
                rows = [
                    r for r in rows
                    if cls._matches_date(r.get("opened_at"), date) or cls._matches_date(r.get("last_seen_at"), date)
                ]
            rows = rows[:limit]
            return rows

    @staticmethod
    def get_registered_persons() -> list[dict[str, Any]]:
        with database_connection() as conn:
            rows = conn.execute(
                """SELECT id, display_name, relationship_label, is_active, created_at
                   FROM persons WHERE is_active = 1 ORDER BY display_name ASC"""
            ).fetchall()
            return [dict(r) for r in rows]
