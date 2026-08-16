from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from src.database import database_connection

POLICY_VERSION = "gate2-v1"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AgentTraceService:
    """Durable, sanitized Agent execution and tool audit log."""

    def create_or_get_run(
        self, incident_id: str, event_id: str, alert_id: str, model: str, incident_version: int, attempt: int = 1
    ) -> dict:
        run_id = str(uuid4())
        with database_connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO agent_runs
                   (id, event_id, incident_id, incident_version, review_generation, alert_id, model, policy_version, status, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
                (
                    run_id,
                    event_id,
                    incident_id,
                    incident_version,
                    incident_version,
                    alert_id,
                    model,
                    POLICY_VERSION,
                    attempt,
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE incident_id = ? AND review_generation = ?",
                (incident_id, incident_version),
            ).fetchone()
            return dict(row)

    def mark_running(self, run_id: str) -> None:
        with database_connection() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = 'running', started_at = ? WHERE id = ? AND status IN ('queued', 'failed')",
                (utc_now(), run_id),
            )

    def complete(self, run_id: str, verdict: str, severity: str, reason: str, latency_ms: float) -> None:
        with database_connection() as connection:
            connection.execute(
                """UPDATE agent_runs SET status = 'completed', verdict = ?, severity = ?,
                   reason_summary = ?, error_code = NULL, completed_at = ?, latency_ms = ? WHERE id = ?""",
                (verdict, severity, reason[:500], utc_now(), max(0, latency_ms), run_id),
            )

    def fail(self, run_id: str, error_code: str, latency_ms: float = 0) -> None:
        with database_connection() as connection:
            connection.execute(
                """UPDATE agent_runs SET status = 'failed', error_code = ?, completed_at = ?, latency_ms = ?
                   WHERE id = ? AND status <> 'completed'""",
                (error_code[:100], utc_now(), max(0, latency_ms), run_id),
            )

    def skip(self, run_id: str, reason: str, latency_ms: float = 0) -> None:
        with database_connection() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='skipped',error_code=?,completed_at=?,latency_ms=? WHERE id=? AND status<>'completed'",
                (reason[:100], utc_now(), max(0, latency_ms), run_id),
            )

    def record_action(
        self,
        *,
        run_id: str,
        event_id: str,
        tool_name: str,
        action_type: str,
        status: str,
        safe_arguments: dict,
        result_summary: str,
        duration_ms: float,
        idempotency_key: str,
    ) -> dict:
        action_id = str(uuid4())
        with database_connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO agent_actions
                   (id, run_id, event_id, tool_name, action_type, status, safe_arguments_json,
                    safe_result_summary, duration_ms, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id,
                    run_id,
                    event_id,
                    tool_name,
                    action_type,
                    status,
                    json.dumps(safe_arguments, ensure_ascii=False),
                    result_summary[:1000],
                    max(0, duration_ms),
                    idempotency_key,
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_actions WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            return dict(row)
