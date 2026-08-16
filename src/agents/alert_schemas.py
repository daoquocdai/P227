from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentVerdict = Literal["CONFIRMED_ALERT", "UNCERTAIN", "DUPLICATE"]
AgentSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class AgentJob:
    incident_id: str
    event_id: str
    alert_id: str
    event_type: str
    enqueued_at: datetime
    incident_version: int
    attempt: int = 1

    @classmethod
    def create(cls, incident_id: str, event_id: str, alert_id: str, event_type: str, incident_version: int) -> AgentJob:
        return cls(incident_id, event_id, alert_id, event_type, datetime.now(UTC), incident_version)


class EnrichAlertArguments(BaseModel):
    verdict: AgentVerdict
    severity: AgentSeverity
    reason_summary: str = Field(min_length=1, max_length=500)


class AgentDecision(BaseModel):
    verdict: AgentVerdict
    severity: AgentSeverity
    reason_summary: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    decision: AgentDecision
    tool_calls: int
    applied: bool = True
    no_op_reason: str | None = None
