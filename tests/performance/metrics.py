from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "stdev": statistics.pstdev(values) if values else None,
    }


@dataclass
class ScenarioResult:
    scenario: str
    load: str
    sent: int
    success: int
    failed: int
    duration_seconds: float
    latencies_ms: list[float] = field(default_factory=list, repr=False)
    stored: int | None = None
    lost: int | None = None
    duplicates: int | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    cpu_p95: float | None = None
    ram_max_mb: float | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        data = asdict(self)
        data.pop("latencies_ms")
        data.update(distribution(self.latencies_ms))
        data["error_rate"] = self.failed / self.sent if self.sent else 0.0
        data["throughput"] = self.success / self.duration_seconds if self.duration_seconds else 0.0
        data["result"] = self.result()
        return data

    def result(self) -> str:
        if self.stored is None:
            return "NOT MEASURED"
        d = distribution(self.latencies_ms)
        passed = (
            self.failed / max(self.sent, 1) < 0.01
            and (d["p50"] or 0) <= 100
            and (d["p95"] or 0) <= 300
            and (d["p99"] or 0) <= 500
        )
        passed = passed and self.lost == 0 and self.duplicates == 0
        if self.cpu_p95 is not None:
            passed = passed and self.cpu_p95 <= 70
        if self.ram_max_mb is not None:
            passed = passed and self.ram_max_mb <= 1024
        return "PASS" if passed else "FAIL"
