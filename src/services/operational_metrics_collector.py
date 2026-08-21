from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psutil

from src.database import database_connection, sqlite_path

logger = logging.getLogger(__name__)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OperationalMetricsCollector:
    """Periodically observe runtime state without owning or changing it."""

    def __init__(self, runtime, interval_seconds: int = 30, retention_days: int = 30) -> None:
        self._runtime = runtime
        self._interval = interval_seconds
        self._retention_days = retention_days
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._process = psutil.Process(os.getpid())
        self._last_cleanup: date | None = None

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._process.cpu_percent(None)
            self._thread = threading.Thread(
                target=self._run,
                name="operational-metrics",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lifecycle_lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lifecycle_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def sample_once(self) -> None:
        measured = datetime.now(UTC)
        measured_at = _utc_text(measured)
        hub = self._hub_snapshot()

        with database_connection(initialize=False) as connection:
            cameras = [
                dict(row)
                for row in connection.execute(
                    "SELECT id, name, is_active, vision_enabled FROM cameras ORDER BY id"
                ).fetchall()
            ]

        camera_samples = []
        for camera in cameras:
            try:
                camera_samples.append(self._camera_snapshot(camera, measured_at))
            except Exception:  # noqa: BLE001 - one camera must not discard other observations
                logger.exception("Operational metrics snapshot failed camera=%s", camera["id"])

        with database_connection(initialize=False) as connection:
            connection.execute(
                """INSERT INTO hub_metrics
                   (id, measured_at, process_cpu_percent, process_rss_mb,
                    host_memory_total_mb, host_memory_used_percent, disk_used_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), measured_at, *hub),
            )
            connection.executemany(
                """INSERT INTO operational_camera_metrics
                   (id, camera_id, measured_at, camera_status, last_seen_at, raw_fps,
                    vision_status, vision_fps, vision_processing_latency_ms,
                    vision_drop_ratio, pending, max_pending, vision_frames_offered,
                    vision_frames_overwritten)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                camera_samples,
            )
            if self._last_cleanup != measured.date():
                cutoff = _utc_text(measured - timedelta(days=self._retention_days))
                connection.execute("DELETE FROM hub_metrics WHERE measured_at < ?", (cutoff,))
                connection.execute(
                    "DELETE FROM operational_camera_metrics WHERE measured_at < ?",
                    (cutoff,),
                )
                self._last_cleanup = measured.date()

    def _hub_snapshot(self) -> tuple[float, float, float, float, float]:
        cpu_count = max(psutil.cpu_count() or 1, 1)
        process_cpu = max(0.0, min(100.0, self._process.cpu_percent(None) / cpu_count))
        process_rss = self._process.memory_info().rss / 1024**2
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self._existing_parent(sqlite_path())))
        return process_cpu, process_rss, memory.total / 1024**2, memory.percent, disk.percent

    def _camera_snapshot(self, camera: dict, measured_at: str) -> tuple:
        public_id = camera["name"] if camera["name"].startswith("camera-") else camera["id"]
        camera_state = self._runtime.camera.get_status(public_id)
        vision_state = self._runtime.vision.get_status(public_id)

        camera_status = "offline" if camera_state is None else camera_state.get("status", "offline")
        if camera_status not in {"connecting", "online", "offline", "error"}:
            camera_status = "offline"
        last_frame = None if camera_state is None else camera_state.get("last_frame_at")
        last_seen_at = _utc_text(datetime.fromtimestamp(last_frame, UTC)) if last_frame else None
        raw_fps = (
            float(camera_state["capture_fps"])
            if camera_status == "online" and camera_state is not None and camera_state.get("capture_fps") is not None
            else None
        )

        vision_enabled = bool(vision_state and vision_state.get("enabled", camera["vision_enabled"]))
        vision_status = (
            vision_state.get("status", "waiting_for_source")
            if vision_enabled and vision_state is not None
            else "disabled"
        )
        if vision_status not in {"disabled", "error", "running", "waiting_for_source"}:
            vision_status = "error"
        realtime = vision_state.get("realtime") if vision_state else None
        realtime = realtime if isinstance(realtime, dict) else {}
        processed = int(realtime.get("vision_frames_processed", 0))
        offered = realtime.get("vision_frames_offered")
        overwritten = realtime.get("vision_frames_overwritten")
        vision_fps = realtime.get("vision_fps") if vision_enabled and processed >= 2 else None
        latency = realtime.get("vision_processing_latency_ms") if vision_enabled and processed else None
        drop_ratio = realtime.get("vision_drop_ratio") if vision_enabled and offered else None

        return (
            str(uuid4()),
            camera["id"],
            measured_at,
            camera_status,
            last_seen_at,
            raw_fps,
            vision_status,
            vision_fps,
            latency,
            drop_ratio,
            realtime.get("pending") if vision_enabled else None,
            realtime.get("max_pending") if vision_enabled else None,
            offered if vision_enabled else None,
            overwritten if vision_enabled else None,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 - monitoring must never crash production runtime
                logger.exception("Operational metrics collection failed")
            if self._stop.wait(self._interval):
                break

    @staticmethod
    def _existing_parent(path: Path) -> Path:
        candidate = path.parent
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate
