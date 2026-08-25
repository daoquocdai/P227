from __future__ import annotations

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
                "description": "Lấy tóm tắt và danh sách sự kiện gần đây (té ngã hoặc người lạ) theo số lượng yêu cầu.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string", "enum": ["fall_suspected", "person_detected", "all"]},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "query_recent_incidents",
                "description": "Lấy danh sách các sự cố (Incidents) gần nhất cùng mức độ nghiêm trọng và trạng thái.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "incident_type": {"type": "string", "enum": ["fall", "unknown_person", "all"]},
                        "status": {"type": "string", "enum": ["OPEN", "ACKNOWLEDGED", "RESOLVED_SAFE", "all"]},
                        "limit": {"type": "integer", "default": 10},
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
    def get_events_summary(event_type: str = "all", limit: int = 10) -> list[dict[str, Any]]:
        with database_connection() as conn:
            query = """
                SELECT e.id, e.event_type, e.occurred_at, e.ai_confidence, c.name as camera_name, c.location_label
                FROM events e
                JOIN cameras c ON c.id = e.camera_id
            """
            args: list[Any] = []
            if event_type != "all":
                query += " WHERE e.event_type = ?"
                args.append(event_type)
            query += " ORDER BY e.occurred_at DESC LIMIT ?"
            args.append(limit)

            rows = conn.execute(query, tuple(args)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_recent_incidents(incident_type: str = "all", status: str = "all", limit: int = 10) -> list[dict[str, Any]]:
        with database_connection() as conn:
            query = """
                SELECT i.id, i.incident_type, i.status, i.opened_at, i.last_seen_at, i.occurrence_count,
                       i.agent_summary, c.name as camera_name, c.location_label,
                       a.severity as alert_severity
                FROM incidents i
                JOIN cameras c ON c.id = i.camera_id
                LEFT JOIN alerts a ON a.incident_id = i.id
            """
            conditions = []
            args: list[Any] = []
            if incident_type != "all":
                conditions.append("i.incident_type = ?")
                args.append(incident_type)
            if status != "all":
                conditions.append("i.status = ?")
                args.append(status)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY i.last_seen_at DESC LIMIT ?"
            args.append(limit)

            rows = conn.execute(query, tuple(args)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_registered_persons() -> list[dict[str, Any]]:
        with database_connection() as conn:
            rows = conn.execute(
                """SELECT id, display_name, relationship_label, is_active, created_at
                   FROM persons WHERE is_active = 1 ORDER BY display_name ASC"""
            ).fetchall()
            return [dict(r) for r in rows]
