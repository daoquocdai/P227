from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def make_event(test_run_id: str, *, event_id: str | None = None, snapshot_path: str | None = None) -> dict:
    completed = datetime.now(UTC)
    return {
        "schema_version": 1,
        "event_id": event_id or f"perf-{uuid4()}",
        "camera_id": "cam_perf_test",
        "camera_location": "Performance Test Lab",
        "event_type": "FALL_SUSPECTED",
        "occurred_at": completed.isoformat(),
        "confidence": 0.91,
        "track_id": f"track-{uuid4()}",
        "identity_status": "UNKNOWN",
        "identity_name": None,
        "snapshot_path": snapshot_path,
        "immobile_seconds": 3.0,
        "metadata": {"test_run_id": test_run_id, "ai_completed_at": completed.isoformat()},
    }
