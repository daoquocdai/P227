from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class PerfConfig:
    base_url: str = os.getenv("PERF_BASE_URL", "http://127.0.0.1:8000")
    database_path: Path = Path(os.getenv("PERF_DATABASE_PATH", "tests/performance/.tmp/perf.db"))
    event_endpoint: str = os.getenv("PERF_EVENT_ENDPOINT", "/api/v1/vision/events")
    health_endpoint: str = os.getenv("PERF_HEALTH_ENDPOINT", "/health")
    stream_endpoint: str = os.getenv("PERF_STREAM_ENDPOINT", "/api/v1/alerts/stream")
    rate: int = _int("PERF_RATE", 1)
    duration_seconds: int = _int("PERF_DURATION_SECONDS", 10)
    concurrency: int = _int("PERF_CONCURRENCY", 4)
    warmup_seconds: int = _int("PERF_WARMUP_SECONDS", 2)
    snapshot_size_kb: int = _int("PERF_SNAPSHOT_SIZE_KB", 0)
    resource_sample_seconds: int = _int("PERF_RESOURCE_SAMPLE_SECONDS", 5)
    report_dir: Path = Path(os.getenv("PERF_REPORT_DIR", "tests/performance/reports"))
    backend_pid: int | None = int(os.environ["PERF_BACKEND_PID"]) if os.getenv("PERF_BACKEND_PID") else None
    allow_production: bool = os.getenv("PERF_ALLOW_PRODUCTION", "").lower() == "true"

    def validate_safe_target(self) -> None:
        host = (urlparse(self.base_url).hostname or "").lower()
        local = host in {"localhost", "127.0.0.1", "::1", "test"}
        if not local and not self.allow_production:
            raise RuntimeError("Refusing non-local target; set PERF_ALLOW_PRODUCTION=true to confirm explicitly")
        if self.rate > 10 and os.getenv("PERF_CONFIRM_HIGH_LOAD", "").lower() != "true":
            raise RuntimeError("Rates above 10/s require PERF_CONFIRM_HIGH_LOAD=true")


CONFIG = PerfConfig()
