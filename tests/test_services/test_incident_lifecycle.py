from datetime import UTC, datetime, timedelta

import pytest

from src.database import database_connection
from src.models.schemas import AlertReviewRequest, VisionEventRequest
from src.services.event_service import EventService


def unknown(event_id: str, track: str, *, session: str = "runtime-a:0", seconds: int = 0):
    return VisionEventRequest(
        event_id=event_id,
        camera_id="incident-camera",
        camera_location="Cửa chính",
        event_type="UNKNOWN_PERSON",
        occurred_at=datetime.now(UTC) + timedelta(seconds=seconds),
        confidence=0.91,
        track_id=track,
        metadata={"source_session": session, "identity_similarity": 0.12},
    )


@pytest.fixture(autouse=True)
def identity_on(monkeypatch):
    monkeypatch.setattr("src.services.event_service.camera_service.identity_enabled_state", lambda _camera_id: True)


@pytest.mark.asyncio
async def test_same_unknown_track_creates_two_events_one_incident_one_alert():
    service = EventService()
    first = await service.create(unknown("unknown-1", "32"))
    second = await service.create(unknown("unknown-2", "32", seconds=61))

    assert first.incident_id == second.incident_id
    assert second.incident_updated is True
    assert second.id == first.id
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM incidents").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM alerts").fetchone()[0] == 1
        assert connection.execute("SELECT occurrence_count FROM incidents").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_different_unknown_track_creates_new_incident():
    service = EventService()
    first = await service.create(unknown("track-32", "32"))
    second = await service.create(unknown("track-47", "47", seconds=61))
    assert first.incident_id != second.incident_id
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM incidents").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM alerts").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_acknowledged_incident_keeps_collecting_same_track():
    service = EventService()
    first = await service.create(unknown("ack-1", "32"))
    await service.review(first.id, AlertReviewRequest(status="checking", note="Đã xem"))
    second = await service.create(unknown("ack-2", "32", seconds=61))
    alert = await service.get_alert(first.id)
    assert second.id == first.id
    assert alert["incident_status"] == "ACKNOWLEDGED"
    assert alert["occurrence_count"] == 2


@pytest.mark.asyncio
async def test_resolved_same_episode_is_persisted_but_frozen_and_suppressed(monkeypatch):
    messages = []

    async def publish(message):
        messages.append(message["type"])

    monkeypatch.setattr("src.services.event_service.alert_broadcaster.publish", publish)
    enqueued = []
    service = EventService()
    service.set_agent_enqueue(lambda *args: enqueued.append(args) or True)
    first = await service.create(unknown("resolve-1", "32"))
    await service.review(first.id, AlertReviewRequest(status="safe", note="Hiện đã an toàn"))
    before = await service.get_alert(first.id)
    later = await service.create(unknown("resolve-2", "32", seconds=61))
    after = await service.get_alert(first.id)

    assert later.suppressed is True
    assert after["occurrence_count"] == before["occurrence_count"] == 1
    assert after["last_seen_at"] == before["last_seen_at"]
    assert messages == ["alert_created", "alert_resolved"]
    assert len(enqueued) == 1
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT disposition FROM incident_events WHERE event_id<>?",
                (connection.execute("SELECT event_id FROM alerts").fetchone()[0],),
            ).fetchone()[0]
            == "suppressed_after_resolution"
        )


@pytest.mark.asyncio
async def test_new_source_session_after_resolution_creates_new_episode():
    service = EventService()
    first = await service.create(unknown("episode-a", "32"))
    await service.review(first.id, AlertReviewRequest(status="safe"))
    second = await service.create(unknown("episode-b", "32", session="runtime-b:0", seconds=1))
    assert second.incident_id != first.incident_id
    assert second.alert_created is True


@pytest.mark.asyncio
async def test_agent_milestones_are_sparse():
    service = EventService()
    calls = []
    service.set_agent_enqueue(lambda *args: calls.append(args) or True)
    for index in range(1, 7):
        await service.create(unknown(f"milestone-{index}", "32", seconds=(index - 1) * 20))
    assert [call[-1] for call in calls] == [1, 2, 5]


@pytest.mark.asyncio
async def test_late_and_out_of_order_agent_writes_are_no_ops():
    from src.agents.alert_tools import AlertAgentTools
    from src.services.agent_trace_service import AgentTraceService
    from src.services.sqlite_event_repository import stable_uuid

    service = EventService()
    first = await service.create(unknown("race-1", "32"))
    trace = AgentTraceService()
    event1 = stable_uuid("race-1", "event")
    run1 = trace.create_or_get_run(first.incident_id, event1, first.id, "test-model", 1)
    old_tools = AlertAgentTools(first.incident_id, event1, first.id, 1, run1["id"], trace)

    second = await service.create(unknown("race-2", "32", seconds=61))
    event2 = stable_uuid("race-2", "event")
    run2 = trace.create_or_get_run(second.incident_id, event2, second.id, "test-model", 2)
    new_tools = AlertAgentTools(second.incident_id, event2, second.id, 2, run2["id"], trace)
    applied = new_tools.execute(
        "enrich_incident_alert",
        '{"verdict":"CONFIRMED_ALERT","severity":"critical","reason_summary":"Latest summary."}',
    )
    stale = old_tools.execute(
        "enrich_incident_alert", '{"verdict":"UNCERTAIN","severity":"low","reason_summary":"Old summary."}'
    )
    await service.review(first.id, AlertReviewRequest(status="safe"))
    closed = new_tools.execute(
        "enrich_incident_alert", '{"verdict":"UNCERTAIN","severity":"low","reason_summary":"Late after close."}'
    )

    assert applied["applied"] is True
    assert stale["no_op_reason"] == "STALE_VERSION"
    assert closed["no_op_reason"] == "INCIDENT_CLOSED"
    assert (await service.get_alert(first.id))["agent_reason_summary"] == "Latest summary."
