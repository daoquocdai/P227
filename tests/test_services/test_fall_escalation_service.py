from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.config import get_settings
from src.database import database_connection
from src.models.schemas import AlertReviewRequest, VisionEventRequest
from src.services.emergency_call_provider import CallResult, TwilioEmergencyCallProvider
from src.services.emergency_contact_service import emergency_contact_service
from src.services.event_service import EventService
from src.services.fall_escalation_service import FallEscalationService


class FakeEmergencyCallProvider:
    def __init__(self, results: list[CallResult] | None = None) -> None:
        self.calls: list[dict] = []
        self.results = list(results or [CallResult(True, provider_reference="fake-call")])

    def call(self, **kwargs) -> CallResult:
        self.calls.append(kwargs)
        return self.results.pop(0) if self.results else CallResult(True, provider_reference="fake-call")


def settings(**updates):
    return get_settings().model_copy(
        update={
            "fall_escalation_enabled": True,
            "fall_call_after_seconds": 30,
            "fall_call_retry_seconds": 10,
            "fall_call_max_attempts": 3,
            **updates,
        }
    )


def add_contact(phone: str = "+84901234567", *, priority: int = 1, active: bool = True, name="Primary"):
    return emergency_contact_service.create_contact(
        SimpleNamespace(
            display_name=name,
            relationship_label="Người thân",
            phone_e164=phone,
            priority=priority,
            is_active=active,
        )
    )


async def create_fall(*, opened_at: datetime, event_id: str | None = None, episode: str = "episode-a"):
    return await EventService().create(
        VisionEventRequest(
            event_id=event_id or f"fall-{uuid4()}",
            camera_id="fall-escalation-camera",
            camera_location="Phòng khách",
            event_type="FALL_CONFIRMED",
            occurred_at=opened_at,
            confidence=0.96,
            metadata={"source_session": "escalation-runtime:0", "incident_id": episode},
        )
    )


@pytest.mark.asyncio
async def test_fall_before_delay_does_not_call():
    now = datetime.now(UTC)
    add_contact()
    await create_fall(opened_at=now)
    provider = FakeEmergencyCallProvider()

    assert await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once() == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_escalation_disabled_preserves_critical_baseline_alert(monkeypatch):
    monkeypatch.setenv("FALL_ESCALATION_ENABLED", "false")
    get_settings.cache_clear()
    now = datetime.now(UTC)
    add_contact()
    accepted = await create_fall(opened_at=now - timedelta(minutes=1))
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(get_settings(), provider, now=lambda: now).evaluate_once()
    alert = await EventService().get_alert(accepted.id)
    assert provider.calls == []
    assert (alert["status"], alert["severity"], alert["escalation_enabled"]) == (
        "pending",
        "critical",
        False,
    )


@pytest.mark.asyncio
async def test_fall_suspected_never_triggers_phone_call():
    now = datetime.now(UTC)
    add_contact()
    await EventService().create(
        VisionEventRequest(
            event_id="suspected-only",
            camera_id="fall-escalation-camera",
            camera_location="Phòng khách",
            event_type="FALL_SUSPECTED",
            occurred_at=now - timedelta(minutes=5),
            confidence=0.7,
        )
    )
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_confirmed_active_fall_stays_product_critical_after_enrichment_write():
    now = datetime.now(UTC)
    accepted = await create_fall(opened_at=now)
    with database_connection() as connection:
        connection.execute("UPDATE alerts SET severity='low' WHERE id=?", (accepted.id,))

    alert = await EventService().get_alert(accepted.id)
    assert alert["severity"] == "critical"


@pytest.mark.asyncio
async def test_due_fall_calls_exactly_once_across_repeated_ticks():
    now = datetime.now(UTC)
    add_contact()
    accepted = await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider()
    service = FallEscalationService(settings(), provider, now=lambda: now)

    assert await service.evaluate_once() == 1
    assert await service.evaluate_once() == 0
    assert len(provider.calls) == 1
    with database_connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM emergency_escalation_attempts WHERE incident_id=? AND status='succeeded'",
                (accepted.incident_id,),
            ).fetchone()[0]
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["safe", "false_alarm"])
async def test_terminal_human_resolution_before_due_cancels_call(resolution):
    now = datetime.now(UTC)
    add_contact()
    accepted = await create_fall(opened_at=now - timedelta(seconds=31))
    await EventService().review(accepted.id, AlertReviewRequest(status=resolution))
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_safe_resolution_between_claim_and_provider_recheck_cancels_call():
    now = datetime.now(UTC)
    add_contact()
    accepted = await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider()

    class SafeRaceService(FallEscalationService):
        def _revalidate_claim(self, claim):
            with database_connection() as connection:
                connection.execute("UPDATE incidents SET status='RESOLVED_SAFE' WHERE id=?", (claim.incident_id,))
            return super()._revalidate_claim(claim)

    await SafeRaceService(settings(), provider, now=lambda: now).evaluate_once()
    assert provider.calls == []
    with database_connection() as connection:
        assert (
            connection.execute(
                "SELECT status FROM emergency_escalation_attempts WHERE incident_id=?", (accepted.incident_id,)
            ).fetchone()[0]
            == "cancelled"
        )


@pytest.mark.asyncio
async def test_viewed_stays_eligible_but_need_help_is_immediate():
    now = datetime.now(UTC)
    add_contact()
    viewed = await create_fall(opened_at=now - timedelta(seconds=31), episode="viewed")
    await EventService().review(viewed.id, AlertReviewRequest(status="checking"))
    help_case = await create_fall(opened_at=now, episode="need-help")
    await EventService().review(help_case.id, AlertReviewRequest(status="need_help"))
    provider = FakeEmergencyCallProvider()

    assert await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once() == 2
    assert {call["incident_id"] for call in provider.calls} == {viewed.incident_id, help_case.incident_id}


@pytest.mark.asyncio
async def test_correlated_fall_events_share_one_persisted_escalation():
    now = datetime.now(UTC)
    add_contact()
    first = await create_fall(opened_at=now - timedelta(seconds=40), event_id="fall-one", episode="same")
    second = await create_fall(opened_at=now - timedelta(seconds=35), event_id="fall-two", episode="same")
    provider = FakeEmergencyCallProvider()
    service = FallEscalationService(settings(), provider, now=lambda: now)

    await service.evaluate_once()
    await service.evaluate_once()
    assert first.incident_id == second.incident_id
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_restart_due_and_restart_after_success_are_idempotent():
    now = datetime.now(UTC)
    add_contact()
    await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once()
    await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once()
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_contact_priority_inactive_skip_and_permanent_failure_fallback():
    now = datetime.now(UTC)
    add_contact("+84900000001", priority=1, active=False, name="Inactive")
    add_contact("+84900000002", priority=2, name="Primary active")
    add_contact("+84900000003", priority=3, name="Secondary")
    await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider(
        [CallResult(False, error_code="INVALID_NUMBER", retryable=False), CallResult(True, "secondary-call")]
    )
    service = FallEscalationService(settings(), provider, now=lambda: now)

    await service.evaluate_once()
    await service.evaluate_once()
    assert [call["phone_number"] for call in provider.calls] == ["+84900000002", "+84900000003"]


@pytest.mark.asyncio
async def test_no_contact_records_failure_without_damaging_alert():
    now = datetime.now(UTC)
    accepted = await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(settings(), provider, now=lambda: now).evaluate_once()
    alert = await EventService().get_alert(accepted.id)
    assert alert["status"] == "pending"
    assert alert["severity"] == "critical"
    assert alert["escalation_status"] == "failed"
    assert provider.calls == []
    with database_connection() as connection:
        assert (
            connection.execute(
                "SELECT error_code FROM emergency_escalation_attempts WHERE incident_id=?", (accepted.incident_id,)
            ).fetchone()[0]
            == "NO_ACTIVE_CONTACT"
        )


@pytest.mark.asyncio
async def test_transient_failure_retries_are_delayed_and_bounded():
    clock = [datetime.now(UTC)]
    add_contact()
    await create_fall(opened_at=clock[0] - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider([CallResult(False, error_code="TIMEOUT", retryable=True)] * 4)
    service = FallEscalationService(settings(), provider, now=lambda: clock[0])

    await service.evaluate_once()
    await service.evaluate_once()
    assert len(provider.calls) == 1
    for _ in range(3):
        clock[0] += timedelta(seconds=11)
        await service.evaluate_once()
    assert len(provider.calls) == 3


@pytest.mark.asyncio
async def test_provider_unavailable_is_persisted_and_baseline_survives():
    now = datetime.now(UTC)
    add_contact()
    accepted = await create_fall(opened_at=now - timedelta(seconds=31))
    provider = FakeEmergencyCallProvider([CallResult(False, error_code="TWILIO_UNAVAILABLE")])
    service = FallEscalationService(settings(), provider, now=lambda: now)

    await service.evaluate_once()
    await service.evaluate_once()
    assert len(provider.calls) == 1
    alert = await EventService().get_alert(accepted.id)
    assert alert["status"] == "pending"
    assert alert["escalation_status"] == "failed"


def test_missing_twilio_credentials_are_unavailable_without_startup_failure():
    provider = TwilioEmergencyCallProvider(
        settings(twilio_account_sid="", twilio_auth_token="", twilio_from_phone_number="")
    )
    assert provider.available is False
    assert provider.call(phone_number="+84901234567", incident_id="test", message="test").error_code == (
        "TWILIO_UNAVAILABLE"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_behavior", ["off", "throws", "delayed"])
async def test_agent_state_does_not_control_escalation(agent_behavior):
    now = datetime.now(UTC)
    add_contact()
    event_service = EventService()
    if agent_behavior == "throws":
        event_service.set_agent_enqueue(lambda *_args: (_ for _ in ()).throw(RuntimeError("agent failed")))
    elif agent_behavior == "delayed":
        event_service.set_agent_enqueue(lambda *_args: True)
    accepted = await event_service.create(
        VisionEventRequest(
            event_id=f"agent-isolation-{agent_behavior}",
            camera_id="agent-isolation-camera",
            camera_location="Phòng ngủ",
            event_type="FALL_CONFIRMED",
            occurred_at=now - timedelta(seconds=31),
            confidence=0.94,
            metadata={"source_session": agent_behavior, "incident_id": agent_behavior},
        )
    )
    provider = FakeEmergencyCallProvider()

    await FallEscalationService(
        settings(alert_agent_enabled=agent_behavior != "off"), provider, now=lambda: now
    ).evaluate_once()
    assert provider.calls[0]["incident_id"] == accepted.incident_id


@pytest.mark.asyncio
async def test_worker_start_stop_does_not_leak_task():
    service = FallEscalationService(settings(fall_escalation_enabled=False), FakeEmergencyCallProvider())
    service.start()
    task = service._task
    service.request_evaluation()
    await asyncio.sleep(0)
    await service.stop()
    assert task is not None and task.done()
