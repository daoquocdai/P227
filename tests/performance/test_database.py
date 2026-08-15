from __future__ import annotations

import concurrent.futures
import sqlite3
import time
from uuid import uuid4

import pytest

from src.config import get_settings
from src.database import initialize_database
from src.models.schemas import VisionEventRequest
from src.services.sqlite_event_repository import SQLiteEventRepository
from tests.performance.event_factory import make_event
from tests.performance.metrics import distribution


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "performance.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    initialize_database()
    yield path
    get_settings.cache_clear()


def _insert(repo, run_id, index):
    payload = make_event(run_id, event_id=f"perf-{uuid4()}")
    started = time.perf_counter_ns()
    repo.create(VisionEventRequest.model_validate(payload), "performance test")
    return (time.perf_counter_ns() - started) / 1_000_000


def _measure(db, sql, params=(), repeats=20):
    values = []
    with sqlite3.connect(db) as connection:
        for _ in range(repeats):
            started = time.perf_counter_ns()
            connection.execute(sql, params).fetchall()
            values.append((time.perf_counter_ns() - started) / 1_000_000)
    return distribution(values)


def test_sqlite_write_queries_and_concurrency(isolated_db):
    repo, run_id = SQLiteEventRepository(), str(uuid4())
    warmup = [_insert(repo, run_id, i) for i in range(5)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_insert, repo, run_id, i) for i in range(40)]
        write_ms = [future.result() for future in futures]
    assert distribution(write_ms)["p95"] <= 50
    queries = {
        "latest_20": ("SELECT * FROM events ORDER BY occurred_at DESC LIMIT 20", (), 100),
        "event_type": ("SELECT * FROM events WHERE event_type=? ORDER BY occurred_at DESC", ("fall_suspected",), 100),
        "camera_time": (
            "SELECT * FROM events WHERE camera_id=(SELECT id FROM cameras WHERE name=? LIMIT 1) AND occurred_at BETWEEN ? AND ?",
            ("cam_perf_test", "2000", "2999"),
            100,
        ),
        "daily_count": (
            "SELECT substr(occurred_at,1,10), count(*) FROM events GROUP BY substr(occurred_at,1,10)",
            (),
            300,
        ),
    }
    for _, (sql, params, threshold) in queries.items():
        assert _measure(isolated_db, sql, params)["p95"] <= threshold
    with sqlite3.connect(isolated_db) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 45
    assert warmup  # explicitly excluded from write_ms
