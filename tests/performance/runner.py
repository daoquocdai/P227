from __future__ import annotations

import argparse
import asyncio
import json
import time
from uuid import uuid4

import httpx

from tests.performance.config import CONFIG
from tests.performance.event_factory import make_event
from tests.performance.metrics import ScenarioResult
from tests.performance.reporting import write_reports
from tests.performance.resource_monitor import ResourceMonitor, environment_info


async def run_load(rate: int, duration: int, scenario: str = "api_latency") -> ScenarioResult:
    CONFIG.validate_safe_target()
    run_id = str(uuid4())
    warmup_run_id = str(uuid4())
    latencies, responses, sent_event_ids = [], [], []
    monitor = ResourceMonitor(CONFIG.backend_pid, max(0.1, CONFIG.resource_sample_seconds))
    monitor.start()
    async with httpx.AsyncClient(base_url=CONFIG.base_url, timeout=10) as client:
        warmup_until = time.monotonic() + CONFIG.warmup_seconds
        while time.monotonic() < warmup_until:
            await client.post(CONFIG.event_endpoint, json=make_event(warmup_run_id))
            await asyncio.sleep(1 / max(rate, 1))
        started = time.monotonic()

        async def send(index: int) -> None:
            target = started + index / rate
            await asyncio.sleep(max(0, target - time.monotonic()))
            payload = make_event(run_id)
            sent_event_ids.append(payload["event_id"])
            before = time.perf_counter_ns()
            try:
                response = await client.post(CONFIG.event_endpoint, json=payload)
                latencies.append((time.perf_counter_ns() - before) / 1_000_000)
                responses.append(response)
            except httpx.HTTPError:
                responses.append(None)

        await asyncio.gather(*(send(i) for i in range(rate * duration)))
        elapsed = time.monotonic() - started
    resources = monitor.stop()
    success = sum(r is not None and r.is_success for r in responses)
    result = ScenarioResult(
        scenario, f"{rate} events/s", len(responses), success, len(responses) - success, elapsed, latencies
    )
    result.cpu_p95, result.ram_max_mb = resources["cpu_p95"], resources["ram_max_mb"]
    result.notes.append(
        "Đếm sự kiện đã lưu, bị mất hoặc trùng yêu cầu PERF_DATABASE_PATH trỏ đến database test riêng."
    )
    if CONFIG.database_path.exists():
        import sqlite3

        with sqlite3.connect(CONFIG.database_path) as db:
            rows = db.execute(
                "SELECT json_extract(metadata_json,'$.external_event_id') FROM events WHERE json_extract(metadata_json,'$.test_run_id')=?",
                (run_id,),
            ).fetchall()
        ids = [r[0] for r in rows]
        result.stored = len(ids)
        result.lost = len(set(sent_event_ids) - set(ids))
        result.duplicates = len(ids) - len(set(ids))
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=int, default=CONFIG.rate)
    parser.add_argument("--duration", type=int, default=CONFIG.duration_seconds)
    args = parser.parse_args()
    result = await run_load(args.rate, args.duration)
    paths = write_reports(
        [result.summary()],
        CONFIG.report_dir,
        {
            **environment_info(),
            "base_url": CONFIG.base_url,
            "event_endpoint": CONFIG.event_endpoint,
            "clock": "perf_counter_ns/monotonic",
        },
    )
    print(json.dumps(result.summary(), indent=2))
    print("Reports:", *(str(path) for path in paths))


if __name__ == "__main__":
    asyncio.run(main())
