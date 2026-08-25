from uuid import uuid4

import pytest

from src.agents.summary_agent import IncidentSummaryAgent
from src.database import BUILTIN_LAPTOP_CAMERA_ID, database_connection, initialize_database


@pytest.mark.asyncio
async def test_summary_agent_generation():
    initialize_database()
    summary_agent = IncidentSummaryAgent()

    incident_id = str(uuid4())
    event_id = str(uuid4())
    now_iso = "2026-08-23T12:00:00.000000Z"

    with database_connection() as conn:
        conn.execute(
            """INSERT INTO incidents (id, camera_id, incident_type, status, opened_at, last_seen_at, occurrence_count, version)
               VALUES (?, ?, 'fall', 'OPEN', ?, ?, 1, 1)""",
            (incident_id, BUILTIN_LAPTOP_CAMERA_ID, now_iso, now_iso),
        )
        conn.execute(
            """INSERT INTO events (id, camera_id, event_type, occurred_at, ai_model_name, ai_model_version, ai_confidence)
               VALUES (?, ?, 'fall_suspected', ?, 'SDA-GCN', 'v1', 0.95)""",
            (event_id, BUILTIN_LAPTOP_CAMERA_ID, now_iso),
        )
        conn.execute(
            """INSERT INTO incident_events (incident_id, event_id) VALUES (?, ?)""",
            (incident_id, event_id),
        )
        conn.execute(
            """INSERT INTO fall_event_details (id, event_id, posture, fall_confidence, immobility_duration_ms)
               VALUES (?, ?, 'lying', 0.95, 4500)""",
            (str(uuid4()), event_id),
        )

    res = await summary_agent.generate_summary(incident_id)
    assert res["success"] is True
    assert res["incident_id"] == incident_id
    assert "TÓM TẮT SỰ CỐ TÉ NGÃ" in res["summary"]
    assert len(res["timeline"]) >= 2

    # Check persistence
    with database_connection() as conn:
        inc = conn.execute("SELECT agent_summary FROM incidents WHERE id=?", (incident_id,)).fetchone()
        assert inc["agent_summary"] == res["summary"]
