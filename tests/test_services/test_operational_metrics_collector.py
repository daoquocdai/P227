import time

from src.database import database_connection
from src.services.operational_metrics_collector import OperationalMetricsCollector


class FakeCameraRuntime:
    def get_status(self, _camera_id):
        return {"status": "online", "last_frame_at": time.time(), "frame_id": 12}


class FakeVisionManager:
    processed = 10

    def get_status(self, camera_id):
        return {
            "camera_id": camera_id,
            "processed_frames": self.processed,
            "last_result": {"processing_ms": 12.5},
        }


class FakeRuntime:
    def __init__(self):
        self.camera = FakeCameraRuntime()
        self.vision = FakeVisionManager()


def test_collector_persists_hub_and_camera_metrics(preserve_application_database):
    runtime = FakeRuntime()
    collector = OperationalMetricsCollector(runtime, interval_seconds=30, ping_url="http://127.0.0.1:1")
    collector._tcp_ping_ms = lambda: 4.2
    collector.sample_once()
    runtime.vision.processed += 15
    time.sleep(0.01)
    collector.sample_once()

    with database_connection() as connection:
        hub = connection.execute(
            "SELECT * FROM device_metrics WHERE camera_id IS NULL ORDER BY measured_at DESC LIMIT 1"
        ).fetchone()
        camera = connection.execute(
            "SELECT operational_status,last_seen_at FROM cameras ORDER BY id LIMIT 1"
        ).fetchone()
        inference = connection.execute(
            "SELECT fps,latency_ms,sample_count FROM inference_metrics ORDER BY measured_at DESC LIMIT 1"
        ).fetchone()

    assert hub["ram_usage_mb"] > 0
    assert hub["ram_total_mb"] > hub["ram_usage_mb"]
    assert hub["ping_ms"] == 4.2
    assert camera["operational_status"] == "online"
    assert camera["last_seen_at"] is not None
    assert inference["fps"] > 0
    assert inference["latency_ms"] == 12.5
    assert inference["sample_count"] == 15
