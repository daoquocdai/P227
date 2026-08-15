import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from tests.performance.config import CONFIG
from tests.performance.event_factory import make_event
from tests.performance.metrics import distribution


async def receive_matching_sse(client, event_id, ready, result):
    async with client.stream("GET", CONFIG.stream_endpoint, timeout=30) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line == "event: ready":
                ready.set()
            if line.startswith("data: "):
                message = json.loads(line[6:])
                alert = message.get("alert", {})
                if alert.get("event_id") == event_id:
                    result.append(datetime.now(UTC))
                    return


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PERF_RUN_LIVE") != "true", reason="Set PERF_RUN_LIVE=true")
async def test_client_receive_latency():
    CONFIG.validate_safe_target()
    values = []
    async with httpx.AsyncClient(base_url=CONFIG.base_url) as client:
        for _ in range(5):
            event_id, ready, received = f"perf-{uuid4()}", asyncio.Event(), []
            task = asyncio.create_task(receive_matching_sse(client, event_id, ready, received))
            await ready.wait()
            payload = make_event(str(uuid4()), event_id=event_id)
            completed = datetime.fromisoformat(payload["metadata"]["ai_completed_at"])
            response = await client.post(CONFIG.event_endpoint, json=payload)
            response.raise_for_status()
            await task
            values.append((received[0] - completed).total_seconds() * 1000)
    stats = distribution(values)
    assert stats["p50"] <= 500 and stats["p95"] <= 1000 and stats["p99"] <= 2000
