import threading
import time

import numpy as np

from src.models.frame import FramePacket
from src.models.vision import VisionEvent, VisionResult
from src.runtime import LocalRuntime
from src.services.frame_hub import FrameHub
from src.services.vision_manager import VisionManager
from src.vision.adapters.mock import MockVisionEngine
from src.vision.engine import VisionEngine
from src.vision.worker import VisionWorker


def packet(camera_id: str, frame_id: int) -> FramePacket:
    return FramePacket(camera_id, frame_id, time.time(), np.zeros((8, 8, 3), dtype=np.uint8))


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_real_vision_event_snapshot_uses_exact_processed_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("src.vision.worker.SNAPSHOT_ROOT", tmp_path)
    for frame_id, engine_name in enumerate(("legacy", "legacy_v2"), start=42):
        source = packet("cam01", frame_id)
        source.frame[:, :] = (12, 34, 56)
        event = VisionEvent(type="fall_confirmed", confidence=0.9)
        result = VisionResult(
            "cam01",
            frame_id,
            source.captured_at,
            time.time(),
            1.0,
            events=[event],
            metadata={"engine": engine_name},
        )

        VisionWorker._attach_event_snapshot(source, result)

        snapshot = tmp_path / event.metadata["snapshot_path"]
        assert snapshot.is_file()
        assert snapshot.read_bytes().startswith(b"\xff\xd8")


class RecordingEngine(VisionEngine):
    def __init__(self):
        self.frame_ids = []

    def process(self, frame, session):
        self.frame_ids.append(frame.frame_id)
        return VisionResult(frame.camera_id, frame.frame_id, frame.captured_at, time.time(), 0.0)


class BlockingEngine(RecordingEngine):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def process(self, frame, session):
        self.frame_ids.append(frame.frame_id)
        if len(self.frame_ids) == 1:
            self.entered.set()
            assert self.release.wait(2)
        return VisionResult(frame.camera_id, frame.frame_id, frame.captured_at, time.time(), 0.0)


def test_vision_defaults_disabled_and_waits_for_source_after_enable():
    manager = VisionManager(FrameHub(), MockVisionEngine())
    manager.start()
    try:
        assert manager.get_status("cam01")["status"] == "disabled"
        assert manager.enable("cam01")["status"] == "waiting_for_source"
    finally:
        manager.stop()


def test_worker_does_not_repeat_frame_and_skips_backlog():
    hub = FrameHub()
    engine = BlockingEngine()
    worker = VisionWorker(hub, engine)
    worker.enable("cam01")
    worker.start()
    try:
        hub.publish(packet("cam01", 100))
        assert engine.entered.wait(1)
        for frame_id in (101, 102, 103):
            hub.publish(packet("cam01", frame_id))
        engine.release.set()
        wait_until(lambda: engine.frame_ids == [100, 103])

        # Publishing the same frame object again must not process it twice.
        hub.publish(packet("cam01", 103))
        time.sleep(0.1)
        assert engine.frame_ids == [100, 103]
        session = worker.get_session("cam01")
        assert session.last_processed_frame_id == 103
        assert session.dropped_frames == 2
    finally:
        worker.stop()


def test_sessions_and_arbitrary_temporal_state_are_per_camera():
    worker = VisionWorker(FrameHub(), MockVisionEngine())
    cam01 = worker.enable("cam01")
    cam02 = worker.enable("cam02")
    cam01.state["test"] = "cam01"

    assert cam01 is not cam02
    assert "test" not in cam02.state


def test_disable_resets_session_and_stops_processing_without_touching_framehub():
    hub = FrameHub()
    manager = VisionManager(hub, MockVisionEngine())
    manager.start()
    try:
        manager.enable("cam01")
        hub.publish(packet("cam01", 1))
        wait_until(lambda: manager.get_status("cam01")["processed_frames"] == 1)
        manager.disable("cam01")
        hub.publish(packet("cam01", 2))
        time.sleep(0.1)

        status = manager.get_status("cam01")
        assert status["status"] == "disabled"
        assert status["processed_frames"] == 0
        assert hub.get_latest("cam01").frame_id == 2
    finally:
        manager.stop()


def test_error_isolated_per_camera_and_last_error_is_retained():
    hub = FrameHub()
    engine = MockVisionEngine(raise_on_camera_ids={"bad"})
    manager = VisionManager(hub, engine)
    manager.start()
    try:
        manager.enable("bad")
        manager.enable("good")
        hub.publish(packet("bad", 1))
        hub.publish(packet("good", 1))
        wait_until(lambda: manager.get_status("bad")["status"] == "error")
        wait_until(lambda: manager.get_status("good")["status"] == "running")

        assert manager.get_status("good")["last_result"]["camera_id"] == "good"
        assert manager.worker.is_running

        engine.raise_on_camera_ids.clear()
        hub.publish(packet("bad", 2))
        wait_until(lambda: manager.get_status("bad")["status"] == "running")
        recovered = manager.get_status("bad")
        assert recovered["current_error"] is None
        assert recovered["last_error"]["frame_id"] == 1
    finally:
        manager.stop()


def test_local_runtime_vision_error_does_not_affect_camera_or_mjpeg(monkeypatch):
    runtime = LocalRuntime(vision_engine=MockVisionEngine(raise_on_camera_ids={"cam01"}))

    class Capture:
        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.005)
            return True, np.zeros((8, 8, 3), dtype=np.uint8)

        def get(self, _):
            return 30.0

        def release(self):
            pass

    monkeypatch.setattr(runtime.camera, "_open_capture", lambda source: Capture())
    runtime.start()
    try:
        runtime.camera.start("cam01", 0)
        runtime.vision.enable("cam01")
        wait_until(lambda: runtime.vision.get_status("cam01")["status"] == "error")
        first_frame_id = runtime.frame_hub.get_latest("cam01").frame_id
        wait_until(lambda: runtime.frame_hub.get_latest("cam01").frame_id > first_frame_id)

        assert runtime.camera.get_status("cam01")["status"] == "online"
        assert next(runtime.stream.mjpeg("cam01")).startswith(b"--frame\r\nContent-Type: image/jpeg")
    finally:
        runtime.stop()
