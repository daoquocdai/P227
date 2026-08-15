from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.auth import current_user, require_admin
from src.database import BUILTIN_VIDEO_CAMERA_ID, database_connection
from src.main import app
from src.services.auth_service import hash_password
from src.services.statistics_service import LOCAL_TZ, statistics_service


def _admin():
    return {"role": "admin", "force_password_change": False, "permissions": {}}


def _caregiver():
    return {"role": "caregiver", "force_password_change": False, "permissions": {}}


def _insert_alert(occurred_at: datetime, *, alert_type="fall", action=None, note=None):
    event_id, alert_id = str(uuid4()), str(uuid4())
    timestamp = occurred_at.astimezone(UTC).isoformat()
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO events
               (id, camera_id, event_type, occurred_at, ai_model_name, ai_model_version, ai_confidence)
               VALUES (?, ?, ?, ?, 'test', '1', .9)""",
            (event_id, BUILTIN_VIDEO_CAMERA_ID, "fall_suspected" if alert_type == "fall" else "person_detected", timestamp),
        )
        connection.execute(
            "INSERT INTO alerts (id, event_id, alert_type, severity, created_at) VALUES (?, ?, ?, 'high', ?)",
            (alert_id, event_id, alert_type, timestamp),
        )
        connection.execute(
            "INSERT INTO alert_actions (id, alert_id, action_type, new_status, created_at) VALUES (?, ?, 'created', 'open', ?)",
            (str(uuid4()), alert_id, timestamp),
        )
        if action:
            response_at = (occurred_at + timedelta(seconds=2)).astimezone(UTC).isoformat()
            verdict = "false_positive" if action == "verdict_recorded" else None
            connection.execute(
                """INSERT INTO alert_actions
                   (id, alert_id, action_type, previous_status, new_status, human_verdict, note, created_at)
                   VALUES (?, ?, ?, 'open', 'dismissed', ?, ?, ?)""",
                (str(uuid4()), alert_id, action, verdict, note, response_at),
            )
    return alert_id


@pytest.mark.asyncio
async def test_statistics_requires_admin(client):
    assert (await client.get("/api/v1/statistics")).status_code == 401
    app.dependency_overrides[current_user] = _caregiver
    try:
        assert (await client.get("/api/v1/statistics")).status_code == 403
    finally:
        app.dependency_overrides.pop(current_user, None)


@pytest.mark.asyncio
async def test_statistics_allows_authenticated_admin_and_denies_caregiver(client):
    password = "Statistics@2026"
    caregiver_id = str(uuid4())
    with database_connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ?, force_password_change = 0 WHERE role = 'admin'",
            (hash_password(password),),
        )
        connection.execute(
            """INSERT INTO users
               (id, email, display_name, role, password_hash, force_password_change)
               VALUES (?, 'caregiver-statistics@example.local', 'Caregiver', 'caregiver', ?, 0)""",
            (caregiver_id, hash_password(password)),
        )
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"identity": "admin@example.local", "password": password},
    )
    caregiver_login = await client.post(
        "/api/v1/auth/login",
        json={"identity": "caregiver-statistics@example.local", "password": password},
    )
    assert admin_login.status_code == 200
    assert caregiver_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}
    caregiver_headers = {"Authorization": f"Bearer {caregiver_login.json()['token']}"}
    assert (await client.get("/api/v1/statistics", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/v1/statistics", headers=caregiver_headers)).status_code == 403


@pytest.mark.asyncio
async def test_statistics_periods_custom_validation_and_empty_state(client):
    app.dependency_overrides[require_admin] = _admin
    try:
        for period, bucket, maximum in (("today", "hour", 24), ("7d", "day", 7), ("30d", "day", 30)):
            response = await client.get(f"/api/v1/statistics?period={period}")
            assert response.status_code == 200
            body = response.json()
            assert body["alert_bucket"]["unit"] == bucket
            bucket_count = len({row["bucket_start"] for row in body["alert_timeline"]})
            assert 1 <= bucket_count <= maximum
            if period != "today":
                assert bucket_count == maximum
            assert body["kpis"]["false_alarm_rate"]["value"] is None
            assert body["kpis"]["average_response_ms"]["value"] is None
        valid = await client.get(
            "/api/v1/statistics?period=custom&start=2026-08-01T00:00:00%2B07:00&end=2026-08-02T00:00:00%2B07:00"
        )
        assert valid.status_code == 200
        assert (await client.get("/api/v1/statistics?period=custom")).status_code == 422
        naive = await client.get(
            "/api/v1/statistics?period=custom&start=2026-08-01T00:00:00&end=2026-08-02T00:00:00"
        )
        assert naive.status_code == 422
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_range_for_today_uses_vietnam_calendar_day():
    now = datetime(2026, 8, 15, 1, 0, tzinfo=LOCAL_TZ)
    start, end = statistics_service.range_for("today", None, None, now=now)
    assert start.astimezone(LOCAL_TZ).isoformat() == "2026-08-15T00:00:00+07:00"
    assert end.astimezone(LOCAL_TZ) == now


@pytest.mark.asyncio
async def test_statistics_uses_latest_review_and_first_human_response(client):
    now = datetime.now(UTC) - timedelta(minutes=2)
    false_alert = _insert_alert(now, action="verdict_recorded", note="Bóng đổ")
    _insert_alert(now + timedelta(seconds=1), action="resolved")
    _insert_alert(now + timedelta(seconds=2))
    # A later reopen supersedes the old false verdict and becomes unconfirmed.
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO alert_actions
               (id, alert_id, action_type, previous_status, new_status, created_at)
               VALUES (?, ?, 'reopened', 'dismissed', 'open', ?)""",
            (str(uuid4()), false_alert, (now + timedelta(seconds=4)).isoformat()),
        )
    app.dependency_overrides[require_admin] = _admin
    try:
        body = (await client.get("/api/v1/statistics?period=today")).json()
    finally:
        app.dependency_overrides.pop(require_admin, None)
    assert body["kpis"]["total_alerts"]["value"] == 3
    assert body["kpis"]["true_alerts"]["value"] == 1
    assert body["kpis"]["false_alerts"]["value"] == 0
    assert body["kpis"]["unconfirmed_alerts"]["value"] == 2
    assert body["kpis"]["false_alarm_rate"]["value"] == 0
    assert body["kpis"]["average_response_ms"]["value"] == pytest.approx(2000, abs=2)
    assert body["false_alarm_reasons"] == []


@pytest.mark.asyncio
async def test_statistics_distribution_reasons_trend_and_operational_scopes(client):
    now = datetime.now(UTC) - timedelta(minutes=1)
    _insert_alert(now, action="verdict_recorded", note="Ánh sáng yếu")
    previous = now - timedelta(days=7)
    _insert_alert(previous, action="resolved")
    measured = now.isoformat()
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO hub_metrics
               (id, measured_at, process_cpu_percent, process_rss_mb,
                host_memory_total_mb, host_memory_used_percent, disk_used_percent)
               VALUES (?, ?, 12, 256, 8192, 55, 40)""",
            (str(uuid4()), measured),
        )
        connection.execute(
            """INSERT INTO operational_camera_metrics
               (id, camera_id, measured_at, camera_status, raw_fps, vision_status,
                vision_fps, vision_processing_latency_ms, vision_drop_ratio,
                pending, max_pending, vision_frames_offered, vision_frames_overwritten)
               VALUES (?, ?, ?, 'online', 29.9, 'running', 14.2, 68, .1, 1, 1, 100, 10)""",
            (str(uuid4()), BUILTIN_VIDEO_CAMERA_ID, measured),
        )
    app.dependency_overrides[require_admin] = _admin
    try:
        body = (await client.get("/api/v1/statistics?period=7d")).json()
    finally:
        app.dependency_overrides.pop(require_admin, None)
    camera = next(row for row in body["camera_distribution"] if row["id"] == BUILTIN_VIDEO_CAMERA_ID)
    operational = next(row for row in body["camera_metrics"] if row["id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert camera["alert_count"] == 1
    assert camera["false_alarm_rate"] == 1
    assert body["false_alarm_reasons"] == [{"note": "Ánh sáng yếu", "count": 1}]
    assert body["hub_metrics"]["process_rss_mb"] == 256
    assert operational["camera_status"] == "disabled"
    assert operational["vision_fps"] is None
    assert operational["raw_fps"] is None
    assert operational["data_source"] == "runtime"
    assert operational.get("process_cpu_percent") is None
    historical = next(row for row in body["performance_timeline"] if row["camera_id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert historical["vision_fps"] == 14.2
    assert historical["raw_fps"] == 29.9
    assert historical["sample_count"] == 1
    assert historical["bucket_seconds"] == 0
    series = next(row for row in body["performance_series"] if row["camera_id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert series["sample_count"] == 1
    assert series["bucket_count"] == 1
    assert body["kpis"]["total_alerts"]["change_percent"] == 0
    assert len(body["performance_timeline"]) <= 120 * len(body["camera_metrics"])


class _StatusReader:
    def __init__(self, states):
        self.states = states

    def get_status(self, camera_id):
        return self.states.get(camera_id)


def _runtime(camera_states, vision_states):
    return SimpleNamespace(camera=_StatusReader(camera_states), vision=_StatusReader(vision_states))


@pytest.mark.asyncio
async def test_current_camera_card_uses_runtime_while_trend_uses_persisted_samples(client):
    measured = datetime.now(UTC) - timedelta(seconds=20)
    with database_connection() as connection:
        connection.execute(
            "UPDATE cameras SET is_active = 1, vision_enabled = 1 WHERE id = ?",
            (BUILTIN_VIDEO_CAMERA_ID,),
        )
        for offset, vision_fps in ((5, 9.5), (10, 10.5)):
            connection.execute(
                """INSERT INTO operational_camera_metrics
                   (id, camera_id, measured_at, camera_status, raw_fps, vision_status,
                    vision_fps, vision_processing_latency_ms, vision_drop_ratio,
                    pending, max_pending, vision_frames_offered, vision_frames_overwritten)
                   VALUES (?, ?, ?, 'online', 30, 'running', ?, 82.4, .358, 0, 1, 100, 36)""",
                (str(uuid4()), BUILTIN_VIDEO_CAMERA_ID, (measured + timedelta(seconds=offset)).isoformat(), vision_fps),
            )
    app.state.local_runtime = _runtime(
        {
            BUILTIN_VIDEO_CAMERA_ID: {
                "status": "online",
                "capture_fps": 29.97,
                "last_frame_at": measured.timestamp(),
            }
        },
        {
            BUILTIN_VIDEO_CAMERA_ID: {
                "enabled": True,
                "status": "running",
                "realtime": {
                    "vision_frames_processed": 20,
                    "vision_frames_offered": 40,
                    "vision_frames_overwritten": 8,
                    "vision_fps": 14.63,
                    "vision_processing_latency_ms": 72.58,
                    "vision_drop_ratio": .2,
                    "pending": 0,
                    "max_pending": 1,
                },
            }
        },
    )
    app.dependency_overrides[require_admin] = _admin
    try:
        body = (await client.get("/api/v1/statistics?period=today")).json()
    finally:
        app.dependency_overrides.pop(require_admin, None)
    current = next(row for row in body["camera_metrics"] if row["id"] == BUILTIN_VIDEO_CAMERA_ID)
    history = [row for row in body["performance_timeline"] if row["camera_id"] == BUILTIN_VIDEO_CAMERA_ID]
    assert current["data_source"] == "runtime"
    assert current["raw_fps"] == 29.97
    assert current["vision_fps"] == 14.63
    assert current["vision_processing_latency_ms"] == 72.58
    assert current["vision_drop_ratio"] == .2
    assert current["pending"] == 0
    assert current["max_pending"] == 1
    assert [row["vision_fps"] for row in history] == [9.5, 10.5]
    assert all(row["bucket_seconds"] == 0 for row in history)


def test_vietnam_midnight_bucketing_and_period_units():
    local_start = datetime(2026, 8, 15, 0, 0, tzinfo=LOCAL_TZ)
    _insert_alert(local_start + timedelta(minutes=30))
    _insert_alert(local_start + timedelta(hours=1, minutes=30))
    result = statistics_service.get_statistics(
        local_start.astimezone(UTC),
        (local_start + timedelta(hours=2)).astimezone(UTC),
        period="custom",
    )
    totals = {
        row["bucket_start"]: row["total"]
        for row in result["alert_timeline"]
        if row["alert_type"] == "fall"
    }
    assert result["alert_bucket"]["unit"] == "hour"
    assert totals == {
        "2026-08-15T00:00:00+07:00": 1,
        "2026-08-15T01:00:00+07:00": 1,
    }
    assert statistics_service._alert_bucket_unit("7d", local_start, local_start + timedelta(days=7)) == "day"
    assert statistics_service._alert_bucket_unit("30d", local_start, local_start + timedelta(days=30)) == "day"


def test_intentionally_off_camera_is_not_a_connection_warning_but_active_error_is():
    persisted = [
        {
            "id": "off",
            "name": "Off camera",
            "location_label": "A",
            "source_kind": "webcam",
            "is_active": 0,
            "vision_enabled": 0,
            "measured_at": None,
            "camera_status": None,
            "last_seen_at": None,
            "raw_fps": None,
            "vision_status": None,
            "vision_fps": None,
            "vision_processing_latency_ms": None,
            "vision_drop_ratio": None,
            "pending": None,
            "max_pending": None,
            "vision_frames_offered": None,
            "vision_frames_overwritten": None,
        },
        {
            "id": "error",
            "name": "Error camera",
            "location_label": "B",
            "source_kind": "rtsp",
            "is_active": 1,
            "vision_enabled": 0,
            "measured_at": None,
            "camera_status": None,
            "last_seen_at": None,
            "raw_fps": None,
            "vision_status": None,
            "vision_fps": None,
            "vision_processing_latency_ms": None,
            "vision_drop_ratio": None,
            "pending": None,
            "max_pending": None,
            "vision_frames_offered": None,
            "vision_frames_overwritten": None,
        },
    ]
    current = statistics_service._current_camera_metrics(
        persisted,
        _runtime({"error": {"status": "error"}}, {}),
    )
    assert current[0]["camera_status"] == "disabled"
    assert current[1]["camera_status"] == "error"
    alerts = statistics_service._threshold_alerts(None, current)
    assert [alert["id"] for alert in alerts] == ["error"]
    assert all("FPS" not in reason for alert in alerts for reason in alert["reasons"])


def test_performance_history_keeps_early_points_and_bounds_large_series():
    end = datetime.now(UTC)
    start = end - timedelta(hours=2)
    with database_connection() as connection:
        connection.executemany(
            """INSERT INTO operational_camera_metrics
               (id, camera_id, measured_at, camera_status, vision_status,
                vision_fps, vision_processing_latency_ms)
               VALUES (?, ?, ?, 'online', 'running', ?, ?)""",
            [
                (
                    str(uuid4()),
                    BUILTIN_VIDEO_CAMERA_ID,
                    (start + timedelta(seconds=index * 30)).isoformat(),
                    10 + index / 100,
                    70 + index / 10,
                )
                for index in range(121)
            ],
        )
        points, series = statistics_service._performance_timeline(connection, start, end)
    video_points = [row for row in points if row["camera_id"] == BUILTIN_VIDEO_CAMERA_ID]
    video_series = next(row for row in series if row["camera_id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert video_series["sample_count"] == 121
    assert 1 < video_series["bucket_count"] <= 120
    assert video_series["bucket_seconds"] >= 60
    assert len(video_points) == video_series["bucket_count"]
    assert sum(row["sample_count"] for row in video_points) == 121
