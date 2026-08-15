from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import app
from tests.performance.event_factory import make_event
from tests.performance.metrics import ScenarioResult
from tests.performance.reporting import write_reports
from tests.performance.resource_monitor import ResourceMonitor, environment_info


@pytest.mark.asyncio
async def test_isolated_smoke_and_write_reports(tmp_path, monkeypatch):
    database = tmp_path / "smoke.db"
    report_dir = Path("tests/performance/reports")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    run_id, latencies, responses = str(uuid4()), [], []
    monitor = ResourceMonitor(None, 0.1)
    monitor.start()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            await client.post("/api/v1/vision/events", json=make_event(run_id))  # warm-up, excluded
            started_run = time.monotonic()
            for _ in range(3):
                started = time.perf_counter_ns()
                response = await client.post("/api/v1/vision/events", json=make_event(run_id))
                latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                responses.append(response)
            elapsed = time.monotonic() - started_run
    resources = monitor.stop()
    with sqlite3.connect(database) as connection:
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT json_extract(metadata_json,'$.external_event_id') FROM events "
                "WHERE json_extract(metadata_json,'$.test_run_id')=?",
                (run_id,),
            )
        ]
    success = sum(response.is_success for response in responses)
    measured_ids = ids[1:]  # warm-up row
    result = ScenarioResult(
        "isolated_smoke",
        "sequential low load",
        3,
        success,
        3 - success,
        elapsed,
        latencies,
        stored=len(measured_ids),
        lost=max(0, success - len(set(measured_ids))),
        duplicates=len(measured_ids) - len(set(measured_ids)),
        cpu_p95=resources["cpu_p95"],
        ram_max_mb=resources["ram_max_mb"],
    )
    paths = write_reports(
        [result.summary()],
        report_dir,
        {**environment_info(), "mode": "ASGI in-process with full lifespan", "database": str(database)},
    )
    assert all(path.exists() for path in paths)
    report = json.loads(paths[0].read_text(encoding="utf-8"))["results"][0]
    assert report["success"] == 3
    assert report["lost"] == 0
    assert report["duplicates"] == 0
    get_settings.cache_clear()
