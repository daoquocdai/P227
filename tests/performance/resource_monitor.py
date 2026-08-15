from __future__ import annotations

import platform
import threading
import time
from dataclasses import dataclass, field

import psutil

from tests.performance.metrics import percentile


@dataclass
class ResourceMonitor:
    pid: int | None
    interval: float = 5.0
    samples: list[dict] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
        cpu = [sample["cpu_percent"] for sample in self.samples]
        ram = [sample["ram_mb"] for sample in self.samples]
        return {
            "cpu_mean": sum(cpu) / len(cpu) if cpu else None,
            "cpu_p95": percentile(cpu, 95),
            "cpu_max": max(cpu) if cpu else None,
            "ram_initial_mb": ram[0] if ram else None,
            "ram_mean_mb": sum(ram) / len(ram) if ram else None,
            "ram_max_mb": max(ram) if ram else None,
            "ram_final_mb": ram[-1] if ram else None,
            "ram_growth_mb": ram[-1] - ram[0] if ram else None,
            "samples": self.samples,
        }

    def _run(self) -> None:
        process = psutil.Process(self.pid) if self.pid else psutil.Process()
        process.cpu_percent(None)
        while not self._stop.wait(self.interval):
            try:
                self.samples.append(
                    {
                        "monotonic": time.monotonic(),
                        "cpu_percent": process.cpu_percent(None),
                        "ram_mb": process.memory_info().rss / 1024**2,
                        "system_cpu_percent": psutil.cpu_percent(None),
                        "system_ram_percent": psutil.virtual_memory().percent,
                    }
                )
            except psutil.Error:
                break


def environment_info() -> dict:
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": platform.processor() or "unknown",
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "total_ram_gb": psutil.virtual_memory().total / 1024**3,
        "gpu": "NOT MEASURED",
        "backend_mode": "tiến trình ngoài; cần ghi lệnh khởi chạy backend trong ghi chú báo cáo",
    }
