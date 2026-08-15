from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psutil

from src.database import database_connection, sqlite_path

logger = logging.getLogger(__name__)


class OperationalMetricsCollector:
    """Persist hub resources and per-camera inference performance periodically."""

    def __init__(self, runtime, interval_seconds: int = 30, ping_url: str = "http://localhost:8000") -> None:
        self._runtime = runtime
        self._interval = interval_seconds
        self._ping_url = ping_url
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process = psutil.Process(os.getpid())
        self._previous_frames: dict[str, tuple[int, float]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._process.cpu_percent(None)
        self._thread = threading.Thread(target=self._run, name="operational-metrics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self._interval + 1, 5))
        self._thread = None

    def sample_once(self) -> None:
        measured_at = datetime.now(UTC).isoformat()
        memory = self._process.memory_info().rss / 1024**2
        total_memory = psutil.virtual_memory().total / 1024**2
        cpu = max(0.0, min(100.0, self._process.cpu_percent(None) / max(psutil.cpu_count() or 1, 1)))
        disk = psutil.disk_usage(str(self._existing_parent(sqlite_path()))).percent
        ping = self._tcp_ping_ms()
        now = time.monotonic()

        with database_connection() as connection:
            connection.execute(
                """INSERT INTO device_metrics
                   (id,camera_id,measured_at,ram_usage_mb,ram_total_mb,cpu_usage_percent,ping_ms,disk_usage_percent)
                   VALUES (?,NULL,?,?,?,?,?,?)""",
                (str(uuid4()), measured_at, memory, total_memory, cpu, ping, disk),
            )
            cameras = connection.execute("SELECT id,name FROM cameras ORDER BY id").fetchall()
            for camera in cameras:
                public_id = camera["name"] if camera["name"].startswith("camera-") else camera["id"]
                runtime_state = self._runtime.camera.get_status(public_id)
                vision_state = self._runtime.vision.get_status(public_id)
                self._persist_camera(connection, camera["id"], runtime_state, vision_state, measured_at, now)

    def _persist_camera(self, connection, camera_id, runtime_state, vision_state, measured_at, now) -> None:
        runtime_status = None if runtime_state is None else runtime_state["status"]
        operational = runtime_status if runtime_status in {"online", "offline", "error"} else "offline"
        last_seen = None if runtime_state is None else runtime_state.get("last_frame_at")
        connection.execute(
            """UPDATE cameras SET operational_status=?,
                   last_seen_at=COALESCE(?,last_seen_at), updated_at=? WHERE id=?""",
            (
                operational,
                datetime.fromtimestamp(last_seen, UTC).isoformat() if last_seen else None,
                measured_at,
                camera_id,
            ),
        )
        frames = int(vision_state.get("processed_frames", 0))
        previous = self._previous_frames.get(camera_id)
        fps = None if previous is None else max(0.0, (frames - previous[0]) / max(now - previous[1], 0.001))
        self._previous_frames[camera_id] = (frames, now)
        result = vision_state.get("last_result")
        latency = None if result is None else result.get("processing_ms")
        if fps is None and latency is None:
            return
        connection.execute(
            """INSERT INTO inference_metrics
               (id,camera_id,measured_at,fps,latency_ms,sample_count)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid4()), camera_id, measured_at, fps, latency, max(0, frames - (previous[0] if previous else frames))),
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 - monitoring must never crash the application
                logger.exception("Operational metrics collection failed")
            if self._stop.wait(self._interval):
                break

    def _tcp_ping_ms(self) -> float | None:
        parsed = urlparse(self._ping_url)
        host = parsed.hostname or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        started = time.perf_counter_ns()
        try:
            with socket.create_connection((host, port), timeout=1):
                return (time.perf_counter_ns() - started) / 1_000_000
        except OSError:
            return None

    @staticmethod
    def _existing_parent(path: Path) -> Path:
        candidate = path.parent
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate
