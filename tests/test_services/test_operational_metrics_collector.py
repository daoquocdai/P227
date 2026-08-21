import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.database import BUILTIN_VIDEO_CAMERA_ID, database_connection
from src.services.operational_metrics_collector import OperationalMetricsCollector


class FakeCameraRuntime:
    status = "online"

    def get_status(self, _camera_id):
        if self.status == "missing":
            return None
        return {
            "status": self.status,
            "last_frame_at": time.time(),
            "capture_fps": 29.8,
        }


class FakeVisionRuntime:
    processed = 10
    enabled = True

    def get_status(self, camera_id):
        offered = 20 if self.processed else 0
        return {
            "camera_id": camera_id,
            "enabled": self.enabled,
            "status": "running" if self.enabled else "disabled",
            "realtime": {
                "vision_frames_processed": self.processed,
                "vision_frames_offered": offered,
                "vision_frames_overwritten": 2 if offered else 0,
                "vision_fps": 14.5,
                "vision_processing_latency_ms": 71.2,
                "vision_drop_ratio": .1,
                "pending": 1,
                "max_pending": 1,
            },
        }


class FakeRuntime:
    def __init__(self):
        self.camera = FakeCameraRuntime()
        self.vision = FakeVisionRuntime()


def test_collector_persists_truthful_hub_and_current_camera_metrics():
    runtime = FakeRuntime()
    collector = OperationalMetricsCollector(runtime)
    collector.sample_once()
    with database_connection() as connection:
        hub = connection.execute("SELECT * FROM hub_metrics").fetchone()
        camera = connection.execute(
            "SELECT * FROM operational_camera_metrics ORDER BY camera_id LIMIT 1"
        ).fetchone()
    assert hub["process_rss_mb"] > 0
    assert hub["host_memory_total_mb"] > 0
    assert camera["raw_fps"] == 29.8
    assert camera["vision_fps"] == 14.5
    assert camera["vision_processing_latency_ms"] == 71.2
    assert camera["vision_drop_ratio"] == .1
    assert camera["max_pending"] == 1


def test_collector_represents_camera_and_vision_off_without_fake_zeroes():
    runtime = FakeRuntime()
    runtime.camera.status = "missing"
    runtime.vision.enabled = False
    OperationalMetricsCollector(runtime).sample_once()
    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM operational_camera_metrics ORDER BY camera_id LIMIT 1"
        ).fetchone()
    assert row["camera_status"] == "offline"
    assert row["raw_fps"] is None
    assert row["vision_status"] == "disabled"
    assert row["vision_fps"] is None
    assert row["vision_drop_ratio"] is None


def test_collector_uses_canonical_values_after_counter_reset():
    runtime = FakeRuntime()
    collector = OperationalMetricsCollector(runtime)
    collector.sample_once()
    runtime.vision.processed = 0
    collector.sample_once()
    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM operational_camera_metrics ORDER BY measured_at DESC, id DESC LIMIT 1"
        ).fetchone()
    assert row["vision_fps"] is None
    assert row["vision_processing_latency_ms"] is None
    assert row["vision_frames_offered"] == 0


def test_collector_does_not_run_database_bootstrap_or_password_hashing(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("steady-state collection invoked startup bootstrap")

    monkeypatch.setattr("src.database.initialize_database", forbidden)
    monkeypatch.setattr("hashlib.pbkdf2_hmac", forbidden)
    OperationalMetricsCollector(FakeRuntime()).sample_once()


def test_start_is_idempotent_sample_failure_isolated_and_stop_safe():
    collector = OperationalMetricsCollector(FakeRuntime(), interval_seconds=.01)
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("sample failed")

    collector.sample_once = fail_once
    collector.start()
    first = collector._thread
    collector.start()
    assert collector._thread is first
    deadline = time.time() + 1
    while calls < 2 and time.time() < deadline:
        time.sleep(.01)
    collector.stop()
    collector.stop()
    assert calls >= 2
    assert not collector.running
    assert not any(thread is first and thread.is_alive() for thread in threading.enumerate())


def test_retention_deletes_only_old_operational_samples():
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    run_id, inference_id = str(uuid4()), str(uuid4())
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO hub_metrics (id, measured_at, process_rss_mb) VALUES (?, ?, 1)",
            (str(uuid4()), old),
        )
        connection.execute(
            """INSERT INTO operational_camera_metrics
               (id, camera_id, measured_at, camera_status, vision_status)
               VALUES (?, ?, ?, 'offline', 'disabled')""",
            (str(uuid4()), BUILTIN_VIDEO_CAMERA_ID, old),
        )
        connection.execute(
            """INSERT INTO evaluation_runs (id, name, model_name, model_version)
               VALUES (?, 'offline', 'test', '1')""",
            (run_id,),
        )
        connection.execute(
            """INSERT INTO inference_metrics
               (id, camera_id, evaluation_run_id, measured_at, fps)
               VALUES (?, ?, ?, ?, 10)""",
            (inference_id, BUILTIN_VIDEO_CAMERA_ID, run_id, old),
        )
    OperationalMetricsCollector(FakeRuntime(), retention_days=30).sample_once()
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM hub_metrics WHERE measured_at = ?", (old,)).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM operational_camera_metrics WHERE measured_at = ?", (old,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM inference_metrics WHERE id = ?", (inference_id,)
        ).fetchone()[0] == 1
