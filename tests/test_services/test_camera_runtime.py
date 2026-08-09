import time

import cv2
import numpy as np

from src.services.camera_runtime import CameraRuntime
from src.services.frame_hub import FrameHub


class FakeCapture:
    def __init__(self):
        self.released = False
        self.read_count = 0

    def isOpened(self):  # noqa: N802 - mirrors OpenCV's API
        return True

    def read(self):
        time.sleep(0.005)
        self.read_count += 1
        return True, np.full((4, 4, 3), self.read_count, dtype=np.uint8)

    def get(self, prop):
        return 30.0 if prop == cv2.CAP_PROP_FPS else 0.0

    def set(self, prop, value):
        return True

    def release(self):
        self.released = True


class FiniteCapture(FakeCapture):
    def read(self):
        self.read_count += 1
        if self.read_count > 3:
            return False, None
        return True, np.full((4, 4, 3), self.read_count, dtype=np.uint8)

    def get(self, prop):
        return 20.0 if prop == cv2.CAP_PROP_FPS else 0.0


class RecordingFrameHub(FrameHub):
    def __init__(self):
        super().__init__()
        self.published_at = []

    def publish(self, packet):
        self.published_at.append(time.monotonic())
        super().publish(packet)


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_runtime_publishes_frames_and_stop_cleans_hub(monkeypatch):
    hub = FrameHub()
    runtime = CameraRuntime(hub)
    capture = FakeCapture()
    monkeypatch.setattr(runtime, "_open_capture", lambda source: capture)

    initial = runtime.start("cam01", 0)
    assert initial["status"] == "connecting"
    wait_until(lambda: hub.has_camera("cam01"))

    frame = hub.get_latest("cam01")
    state = runtime.get_status("cam01")
    assert frame.camera_id == "cam01"
    assert state["status"] == "online"
    assert state["frame_id"] == frame.frame_id

    stopped = runtime.stop("cam01")
    assert stopped["status"] == "offline"
    assert capture.released
    assert not hub.has_camera("cam01")


def test_start_rejects_duplicate_running_camera(monkeypatch):
    runtime = CameraRuntime(FrameHub())
    monkeypatch.setattr(runtime, "_open_capture", lambda source: FakeCapture())
    runtime.start("cam01", "0")
    try:
        try:
            runtime.start("cam01", 0)
            raise AssertionError("duplicate start should fail")
        except RuntimeError as exc:
            assert "already running" in str(exc)
    finally:
        runtime.stop("cam01")


def test_video_file_publish_respects_source_fps(monkeypatch):
    hub = RecordingFrameHub()
    runtime = CameraRuntime(hub)
    capture = FiniteCapture()
    monkeypatch.setattr(runtime, "_open_capture", lambda source: capture)
    monkeypatch.setattr(runtime, "_is_file", lambda source: True)

    runtime.start("video01", "fake.mp4", loop_video=False)
    wait_until(lambda: runtime.get_status("video01")["status"] == "ended")

    assert len(hub.published_at) == 3
    intervals = [later - earlier for earlier, later in zip(hub.published_at, hub.published_at[1:])]
    assert all(interval >= 0.035 for interval in intervals)
    runtime.stop("video01")
