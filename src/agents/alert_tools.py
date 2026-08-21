from __future__ import annotations

import json
import time
from uuid import uuid4

from src.agents.alert_schemas import EnrichAlertArguments
from src.database import database_connection
from src.services.agent_trace_service import AgentTraceService


class AlertAgentToolError(ValueError):
    pass


class AlertAgentTools:
    def __init__(self, incident_id, event_id, alert_id, expected_version, run_id, trace: AgentTraceService):
        self.incident_id, self.event_id, self.alert_id = incident_id, event_id, alert_id
        self.expected_version, self.run_id, self.trace = expected_version, run_id, trace

    @staticmethod
    def definitions():
        empty = {"type": "object", "properties": {}, "additionalProperties": False}
        decision = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["CONFIRMED_ALERT", "UNCERTAIN", "DUPLICATE"]},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "reason_summary": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["verdict", "severity", "reason_summary"],
            "additionalProperties": False,
        }
        return [
            {
                "type": "function",
                "name": "get_incident_context",
                "description": "Read authoritative current Incident state and counts.",
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "get_event_context",
                "description": "Read allow-listed trigger Event evidence.",
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "enrich_incident_alert",
                "description": "Persist a concise Incident review; stale or closed writes are safe no-ops.",
                "parameters": decision,
                "strict": True,
            },
        ]

    def execute(self, name, raw_arguments):
        started = time.perf_counter()
        try:
            args = json.loads(raw_arguments or "{}")
            if not isinstance(args, dict):
                raise AlertAgentToolError("arguments must be object")
            if name == "get_incident_context":
                if args:
                    raise AlertAgentToolError("identifiers are server-authoritative")
                result, kind, key = self._incident_context(), "read", f"{self.run_id}:incident"
            elif name == "get_event_context":
                if args:
                    raise AlertAgentToolError("identifiers are server-authoritative")
                result, kind, key = self._event_context(), "read", f"{self.run_id}:event"
            elif name == "enrich_incident_alert":
                parsed = EnrichAlertArguments.model_validate(args)
                result = self._enrich(parsed)
                kind, key = "enrichment", f"incident-enrichment:{self.incident_id}:{self.expected_version}"
            else:
                raise AlertAgentToolError("unknown tool")
        except (json.JSONDecodeError, ValueError) as exc:
            raise AlertAgentToolError(str(exc)) from exc
        action = self.trace.record_action(
            run_id=self.run_id,
            event_id=self.event_id,
            tool_name=name,
            action_type=kind,
            status="succeeded" if result.get("applied", True) else "reused",
            safe_arguments=args,
            result_summary=self._summary(name, result),
            duration_ms=(time.perf_counter() - started) * 1000,
            idempotency_key=key,
        )
        return {**result, "audit_action_id": action["id"]}

    def _incident_context(self):
        with database_connection() as c:
            r = c.execute(
                """SELECT i.*,c.name camera_name,c.location_label,a.id alert_id,a.severity alert_severity,a.status alert_status,
            (SELECT e.ai_confidence FROM incident_events ie JOIN events e ON e.id=ie.event_id WHERE ie.incident_id=i.id AND ie.disposition='attached' ORDER BY e.occurred_at DESC LIMIT 1) latest_confidence,
            EXISTS(SELECT 1 FROM incident_events ie JOIN media_assets m ON m.event_id=ie.event_id WHERE ie.incident_id=i.id) snapshot_present
            FROM incidents i JOIN cameras c ON c.id=i.camera_id JOIN alerts a ON a.incident_id=i.id WHERE i.id=? AND a.id=?""",
                (self.incident_id, self.alert_id),
            ).fetchone()
        if not r:
            raise AlertAgentToolError("current incident not found")
        return {
            "incident_id": r["id"],
            "incident_type": r["incident_type"],
            "status": r["status"],
            "camera": {"id": r["camera_id"], "name": r["camera_name"], "location": r["location_label"]},
            "occurrence_count": r["occurrence_count"],
            "first_seen_at": r["opened_at"],
            "last_seen_at": r["last_seen_at"],
            "latest_event": {"confidence": r["latest_confidence"], "snapshot_present": bool(r["snapshot_present"])},
            "alert": {"id": r["alert_id"], "severity": r["alert_severity"], "status": r["alert_status"]},
        }

    def _event_context(self):
        with database_connection() as c:
            r = c.execute(
                """SELECT e.id,e.event_type,e.occurred_at,e.ai_confidence,e.metadata_json,EXISTS(SELECT 1 FROM media_assets m WHERE m.event_id=e.id) snapshot_present FROM events e JOIN incident_events ie ON ie.event_id=e.id WHERE e.id=? AND ie.incident_id=?""",
                (self.event_id, self.incident_id),
            ).fetchone()
        if not r:
            raise AlertAgentToolError("trigger event not found")
        m = json.loads(r["metadata_json"] or "{}")
        return {
            "event_id": r["id"],
            "event_type": m.get("source_event_type", r["event_type"]),
            "occurred_at": r["occurred_at"],
            "confidence": r["ai_confidence"],
            "snapshot_present": bool(r["snapshot_present"]),
            "vision_processing_ms": m.get("vision_processing_ms"),
        }

    def _enrich(self, d):
        with database_connection() as c:
            i = c.execute(
                "SELECT status,version,summary_version FROM incidents WHERE id=?", (self.incident_id,)
            ).fetchone()
            if not i:
                raise AlertAgentToolError("current incident not found")
            reason = None
            if i["status"] == "RESOLVED_SAFE":
                reason = "INCIDENT_CLOSED"
            elif i["version"] != self.expected_version or i["summary_version"] >= self.expected_version:
                reason = "STALE_VERSION"
            if reason:
                c.execute(
                    "INSERT INTO incident_actions (id,incident_id,action_type,event_id,incident_version,note) VALUES (?,?,'agent_result_stale',?,?,?)",
                    (str(uuid4()), self.incident_id, self.event_id, self.expected_version, reason),
                )
                return {**d.model_dump(), "applied": False, "no_op_reason": reason}
            c.execute(
                "UPDATE incidents SET agent_summary=?,summary_version=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (d.reason_summary, self.expected_version, self.incident_id),
            )
            c.execute(
                "UPDATE alerts SET severity=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND incident_id=?",
                (d.severity, self.alert_id, self.incident_id),
            )
            c.execute(
                "INSERT INTO incident_actions (id,incident_id,action_type,event_id,incident_version,note) VALUES (?,?,'agent_summary_applied',?,?,?)",
                (str(uuid4()), self.incident_id, self.event_id, self.expected_version, d.reason_summary),
            )
        return {**d.model_dump(), "applied": True, "incident_id": self.incident_id, "alert_id": self.alert_id}

    @staticmethod
    def _summary(name, r):
        if name == "get_incident_context":
            return f"incident found; status={r['status']}; occurrences={r['occurrence_count']}"
        if name == "get_event_context":
            return f"trigger event found; type={r['event_type']}; snapshot_present={r['snapshot_present']}"
        return f"incident enrichment applied={r['applied']}; verdict={r['verdict']}"
