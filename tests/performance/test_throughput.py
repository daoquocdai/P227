import os

import pytest

from tests.performance.runner import run_load


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [1, 10, 50, 100])
@pytest.mark.skipif(os.getenv("PERF_RUN_MATRIX") != "true", reason="Explicit opt-in required")
async def test_throughput_matrix(rate):
    result = await run_load(rate, int(os.getenv("PERF_DURATION_SECONDS", "60")), "throughput")
    assert result.result() == "PASS"
