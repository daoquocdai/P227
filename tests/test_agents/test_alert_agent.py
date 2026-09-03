import asyncio
import threading
from datetime import datetime
from uuid import uuid4

import pytest

from src.agents.alert_orchestrator import AlertAgentOrchestrator
from src.agents.alert_provider import (
    AlertAgentModelProvider,
    AlertAgentProviderError,
    DeterministicAlertAgentProvider,
)
from src.agents.alert_schemas import AgentDecision, AgentExecutionResult
from src.agents.alert_tools import AlertAgentToolError, AlertAgentTools
from src.config import Settings
from src.database import database_connection
from src.models.schemas import VisionEventRequest
from src.services.agent_trace_service import AgentTraceService
from src.services.event_service import EventService
from src.services.sqlite_event_repository import stable_uuid


def fall_event(event_id=None):
    return VisionEventRequest(
        event_id=event_id or f"agent-fall-{uuid4()}",
        camera_id="agent-camera",
        camera_location="Phòng khách",
        event_type="FALL_CONFIRMED",
        occurred_at=datetime.now().astimezone(),
        confidence=0.93,
        metadata={"vision_processing_ms": 82.5},
    )


def unknown_event(event_id=None):
    return VisionEventRequest(
        event_id=event_id or f"agent-unknown-{uuid4()}",
        camera_id="agent-camera",
        camera_location="Cửa chính",
        event_type="UNKNOWN_PERSON",
        occurred_at=datetime.now().astimezone(),
        confidence=0.91,
        track_id="unknown-track",
        metadata={"source_session": "agent-session:1"},
    )


class SuccessfulProvider(AlertAgentModelProvider):
    def __init__(self):
        self.called = asyncio.Event()
        self.thread_name = None

    async def run(self, job, tools):
        self.thread_name = threading.current_thread().name
        context = await asyncio.to_thread(tools.execute, "get_incident_context", "{}")
        assert context["incident_id"] == job.incident_id
        result = await asyncio.to_thread(
            tools.execute,
            "enrich_incident_alert",
            '{"verdict":"CONFIRMED_ALERT","severity":"critical","reason_summary":"Vision event was persisted and reviewed."}',
        )
        self.called.set()
        return AgentExecutionResult(decision=AgentDecision.model_validate(result), tool_calls=2)


class TimeoutProvider(AlertAgentModelProvider):
    async def run(self, job, tools):
        await asyncio.sleep(1)


class ErrorProvider(AlertAgentModelProvider):
    async def run(self, job, tools):
        raise AlertAgentProviderError("provider unavailable")


class CoalescingProvider(AlertAgentModelProvider):
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.versions = []

    async def run(self, job, tools):
        self.versions.append(job.incident_version)
        if job.incident_version == 1:
            self.started.set()
            await self.release.wait()
        result = await asyncio.to_thread(
            tools.execute,
            "enrich_incident_alert",
            '{"verdict":"CONFIRMED_ALERT","severity":"high","reason_summary":"Coalesced review."}',
        )
        return AgentExecutionResult(
            decision=AgentDecision.model_validate(result),
            tool_calls=1,
            applied=bool(result.get("applied")),
            no_op_reason=result.get("no_op_reason"),
        )


@pytest.mark.asyncio
async def test_event_is_broadcast_before_agent_enqueue(monkeypatch):
    order = []

    async def publish(_message):
        order.append("broadcast")

    monkeypatch.setattr("src.services.event_service.alert_broadcaster.publish", publish)
    service = EventService()
    service.set_agent_enqueue(lambda *_args: order.append("enqueue") or True)

    await service.create(fall_event())

    assert order == ["broadcast", "enqueue"]


@pytest.mark.asyncio
async def test_agent_disabled_preserves_baseline_alert():
    settings = Settings(_env_file=None, alert_agent_enabled=False)
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=ErrorProvider())
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    accepted = await service.create(fall_event("disabled-agent-event"))
    alert = await service.get_alert(accepted.id)

    assert accepted.alert_created is True
    assert alert["status"] == "pending"
    assert alert["agent_status"] is None
    assert orchestrator._consumer is None
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_real_tools_persist_idempotent_enrichment():
    accepted = await EventService().create(fall_event("tool-event"))
    event_id = stable_uuid("tool-event", "event")
    trace = AgentTraceService()
    run = trace.create_or_get_run(accepted.incident_id, event_id, accepted.id, "test-model", accepted.incident_version)
    tools = AlertAgentTools(accepted.incident_id, event_id, accepted.id, accepted.incident_version, run["id"], trace)

    context = tools.execute("get_incident_context", "{}")
    first = tools.execute(
        "enrich_incident_alert", '{"verdict":"UNCERTAIN","severity":"high","reason_summary":"Needs human review."}'
    )
    second = tools.execute(
        "enrich_incident_alert", '{"verdict":"UNCERTAIN","severity":"high","reason_summary":"Needs human review."}'
    )

    assert context["latest_event"]["snapshot_present"] is False
    assert context["occurrence_count"] == 1
    assert first["audit_action_id"] == second["audit_action_id"]
    with database_connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM agent_actions WHERE tool_name='enrich_incident_alert'").fetchone()[
                0
            ]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM incident_actions WHERE action_type='agent_summary_applied'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM incident_actions WHERE action_type='agent_result_stale'"
            ).fetchone()[0]
            == 0
        )


def test_tools_reject_identifiers_and_clamp_recent_query():
    accepted = asyncio.run(EventService().create(fall_event("guarded-event")))
    event_id = stable_uuid("guarded-event", "event")
    trace = AgentTraceService()
    run = trace.create_or_get_run(accepted.incident_id, event_id, accepted.id, "test-model", accepted.incident_version)
    tools = AlertAgentTools(accepted.incident_id, event_id, accepted.id, accepted.incident_version, run["id"], trace)

    with pytest.raises(AlertAgentToolError):
        tools.execute("get_incident_context", '{"incident_id":"someone-else"}')


@pytest.mark.asyncio
async def test_orchestrator_completes_without_blocking_baseline_alert():
    provider = SuccessfulProvider()
    settings = Settings(
        _env_file=None,
        alert_agent_enabled=True,
        openai_api_key="test-only",
        alert_agent_queue_capacity=2,
        alert_agent_max_attempts=1,
        alert_agent_timeout_seconds=2,
        alert_agent_shutdown_timeout_seconds=1,
    )
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=provider)
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    accepted = await service.create(fall_event("orchestrated-event"))
    assert (await service.get_alert(accepted.id))["agent_status"] in {None, "queued", "running"}
    await asyncio.wait_for(provider.called.wait(), 2)
    await asyncio.wait_for(orchestrator._queue.join(), 2)
    assert not provider.thread_name.startswith(("camera-", "vision-"))
    assert (await service.get_alert(accepted.id))["agent_status"] == "completed"
    assert (await service.get_alert(accepted.id))["agent_reason_summary"] == "Vision event was persisted and reviewed."
    assert (await service.get_alert(accepted.id))["severity"] == "critical"
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_enabled_without_openai_key_uses_valid_deterministic_enrichment():
    settings = Settings(
        _env_file=None,
        alert_agent_enabled=True,
        openai_api_key="",
        alert_agent_max_attempts=1,
        alert_agent_shutdown_timeout_seconds=1,
    )
    orchestrator = AlertAgentOrchestrator(settings=settings)
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    accepted = await service.create(unknown_event("deterministic-unknown"))
    await asyncio.wait_for(orchestrator._queue.join(), 2)
    alert = await service.get_alert(accepted.id)

    assert isinstance(orchestrator.provider, DeterministicAlertAgentProvider)
    assert alert["agent_status"] == "completed"
    assert alert["severity"] == "medium"
    assert alert["agent_reason_summary"]
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_bounded_queue_rejects_saturation_without_touching_alert():
    settings = Settings(
        _env_file=None, alert_agent_enabled=True, openai_api_key="test-only", alert_agent_queue_capacity=1
    )
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=SuccessfulProvider())
    orchestrator._queue = asyncio.Queue(maxsize=1)
    orchestrator._accepting = True
    assert orchestrator.enqueue(str(uuid4()), "one", str(uuid4()), "FALL_CONFIRMED", 1) is True
    assert orchestrator.enqueue(str(uuid4()), "two", str(uuid4()), "FALL_CONFIRMED", 1) is False


@pytest.mark.asyncio
async def test_provider_timeout_preserves_baseline_alert_and_records_failure():
    settings = Settings(
        _env_file=None,
        alert_agent_enabled=True,
        openai_api_key="test-only",
        alert_agent_timeout_seconds=0.05,
        alert_agent_max_attempts=1,
        alert_agent_shutdown_timeout_seconds=1,
    )
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=TimeoutProvider())
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    accepted = await service.create(fall_event("timeout-event"))
    await asyncio.wait_for(orchestrator._queue.join(), 1)
    alert = await service.get_alert(accepted.id)

    assert alert["id"] == accepted.id
    assert alert["agent_status"] == "failed"
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_provider_error_preserves_baseline_alert_and_records_failure():
    settings = Settings(
        _env_file=None,
        alert_agent_enabled=True,
        openai_api_key="test-only",
        alert_agent_max_attempts=1,
        alert_agent_shutdown_timeout_seconds=1,
    )
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=ErrorProvider())
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    accepted = await service.create(fall_event("provider-error-event"))
    await asyncio.wait_for(orchestrator._queue.join(), 2)
    alert = await service.get_alert(accepted.id)

    assert alert["id"] == accepted.id
    assert alert["status"] == "pending"
    assert alert["agent_status"] == "failed"
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_coalesced_incident_runs_latest_version_once_without_duplicate_write():
    provider = CoalescingProvider()
    settings = Settings(
        _env_file=None,
        alert_agent_enabled=True,
        openai_api_key="test-only",
        alert_agent_queue_capacity=2,
        alert_agent_max_attempts=1,
        alert_agent_shutdown_timeout_seconds=1,
    )
    orchestrator = AlertAgentOrchestrator(settings=settings, provider=provider)
    orchestrator.start()
    service = EventService()
    service.set_agent_enqueue(orchestrator.enqueue)

    first = await service.create(fall_event("coalesced-1"))
    await asyncio.wait_for(provider.started.wait(), 2)
    second = await service.create(fall_event("coalesced-2"))
    assert second.incident_id == first.incident_id
    assert orchestrator.enqueue(
        second.incident_id,
        second.event_id,
        second.id,
        "FALL_CONFIRMED",
        second.incident_version,
    )
    provider.release.set()
    await asyncio.wait_for(orchestrator._queue.join(), 2)

    with database_connection() as connection:
        incident = connection.execute(
            "SELECT summary_version,agent_summary FROM incidents WHERE id=?", (first.incident_id,)
        ).fetchone()
        applied = connection.execute(
            "SELECT count(*) FROM incident_actions WHERE incident_id=? AND action_type='agent_summary_applied'",
            (first.incident_id,),
        ).fetchone()[0]
    assert provider.versions == [1, 2]
    assert (incident["summary_version"], incident["agent_summary"]) == (2, "Coalesced review.")
    assert applied == 1
    await orchestrator.stop()
