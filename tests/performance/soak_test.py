from __future__ import annotations

import asyncio
import os

from tests.performance.config import CONFIG
from tests.performance.reporting import write_reports
from tests.performance.resource_monitor import environment_info
from tests.performance.runner import run_load


async def main():
    duration = int(os.getenv("PERF_DURATION_SECONDS", "7200"))
    rate = int(os.getenv("PERF_RATE", "1"))
    result = await run_load(rate, duration, "soak")
    write_reports(
        [result.summary()],
        CONFIG.report_dir,
        {
            **environment_info(),
            "duration_seconds": duration,
            "snapshot_ratio": float(os.getenv("PERF_SNAPSHOT_RATIO", "0")),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
