import os

import pytest

from tests.performance.runner import run_load


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PERF_RUN_LIVE") != "true", reason="Set PERF_RUN_LIVE=true for live performance tests")
async def test_api_latency_thresholds():
    result = await run_load(rate=1, duration=3)
    summary = result.summary()
    assert summary["error_rate"] < 0.01
    assert summary["p50"] <= 100
    assert summary["p95"] <= 300
    assert summary["p99"] <= 500
