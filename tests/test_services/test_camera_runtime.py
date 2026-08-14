import threading
import time

import cv2
import numpy as np
import pytest

from src.models.vision import VisionResult
from src.services.camera_runtime import CameraRuntime
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.synchronous_vision_manager import SynchronousVisionManager
from src.services.vision_sample_buffer import VisionSampleBuffer


class FakeCapture:
    def __init__(self):
        self.released = False
        self.read_count = 0

    def isOpened(self):
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
        self.packets = []

    def publish(self, packet):
        self.published_at.append(time.monotonic())
        self.packets.append(packet)
        super().publish(packet)


class LoopingFiniteCapture(FiniteCapture):
    def set(self, prop, value):
        if prop == cv2.CAP_PROP_POS_FRAMES and value == 0:
            self.read_count = 0
        return True


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


def test_live_source_uses_monotonic_arrival_timestamps(monkeypatch):
    hub = RecordingFrameHub()
    runtime = CameraRuntime(hub)
    monkeypatch.setattr(runtime, "_open_capture", lambda source: FakeCapture())

    runtime.start("cam01", 0)
    try:
        wait_until(lambda: len(hub.packets) >= 3)
        packets = hub.packets[:3]
        assert {packet.source_time_kind for packet in packets} == {"monotonic_arrival"}
        assert [packet.source_timestamp for packet in packets] == sorted(
            packet.source_timestamp for packet in packets
        )
        assert packets[0].discontinuity
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
    assert [packet.source_timestamp for packet in hub.packets] == [0.0, 0.05, 0.1]
    assert hub.packets[0].discontinuity
    assert {packet.source_time_kind for packet in hub.packets} == {"media_timeline"}
    assert {packet.source_epoch for packet in hub.packets} == {0}
    runtime.stop("video01")


def test_video_loop_starts_new_source_epoch_and_resets_media_time(monkeypatch):
    hub = RecordingFrameHub()
    runtime = CameraRuntime(hub)
    capture = LoopingFiniteCapture()
    monkeypatch.setattr(runtime, "_open_capture", lambda source: capture)
    monkeypatch.setattr(runtime, "_is_file", lambda source: True)

    runtime.start("video01", "fake.mp4", loop_video=True)
    wait_until(lambda: len(hub.packets) >= 4)
    runtime.stop("video01")

    first, loop_first = hub.packets[0], hub.packets[3]
    assert (first.source_epoch, first.source_timestamp, first.discontinuity) == (0, 0.0, True)
    assert (loop_first.source_epoch, loop_first.source_timestamp, loop_first.discontinuity) == (1, 0.0, True)


def test_sampler_overload_does_not_block_camera_or_mjpeg(monkeypatch):
    hub = FrameHub()
    buffer = VisionSampleBuffer(capacity=8)
    buffer.enable("cam01")
    runtime = CameraRuntime(hub, vision_sample_buffer=buffer)
    monkeypatch.setattr(runtime, "_open_capture", lambda source: FakeCapture())
    stream = StreamService(hub)

    runtime.start("cam01", 0)
    try:
        wait_until(lambda: buffer.get_status("cam01")["overload_count"] > 0, timeout=2.0)
        before = hub.get_latest("cam01").frame_id
        wait_until(lambda: hub.get_latest("cam01").frame_id > before)
        assert runtime.get_status("cam01")["status"] == "online"
        assert next(stream.mjpeg("cam01")).startswith(b"--frame\r\nContent-Type: image/jpeg")
        assert buffer.get_status("cam01")["buffer_depth"] <= 8
    finally:
        runtime.stop("cam01")


def test_capture_continues_while_async_vision_is_blocked(monkeypatch):
    hub = FrameHub()
    entered = threading.Event()
    release = threading.Event()

    def slow_consumer(_packet):
        entered.set()
        assert release.wait(2)

    # CameraRuntime only invokes a non-blocking offer callback in production;
    # this test models that callback handing work to its own execution context.
    def offer(packet):
        if not entered.is_set():
            threading.Thread(target=slow_consumer, args=(packet,), daemon=True).start()

    runtime = CameraRuntime(hub, vision_processor=offer)
    capture = FakeCapture()
    monkeypatch.setattr(runtime, "_open_capture", lambda source: capture)
    runtime.start("cam01", 0)
    try:
        assert entered.wait(1)
        before = capture.read_count
        wait_until(lambda: capture.read_count >= before + 3)
        assert hub.get_latest("cam01").frame_id >= 3
    finally:
        release.set()
        runtime.stop("cam01")


@pytest.mark.parametrize("vision_delay", [0.0, 0.15, 0.5])
def test_video_playback_duration_does_not_follow_vision_latency(monkeypatch, vision_delay):
    class TwelveFrameCapture(FiniteCapture):
        def read(self):
            self.read_count += 1
            if self.read_count > 12:
                return False, None
            return True, np.full((4, 4, 3), self.read_count, dtype=np.uint8)

        def get(self, prop):
            return 20.0 if prop == cv2.CAP_PROP_FPS else 0.0

    class DelayEngine:
        def start(self): pass
        def stop(self): pass
        def prepare_camera(self, camera_id, session): pass
        def release_camera(self, camera_id): pass
        def process(self, packet, session):
            time.sleep(vision_delay)
            return VisionResult(
                packet.camera_id, packet.frame_id, packet.captured_at, packet.captured_at,
                vision_delay * 1000, metadata={"sampled": True, "observation_time": packet.source_timestamp},
            )

    raw = FrameHub()
    manager = SynchronousVisionManager(DelayEngine())
    manager.start()
    manager.enable("video")
    runtime = CameraRuntime(raw, vision_processor=manager.offer)
    monkeypatch.setattr(runtime, "_open_capture", lambda source: TwelveFrameCapture())
    monkeypatch.setattr(runtime, "_is_file", lambda source: True)

    started = time.monotonic()
    runtime.start("video", "fake.mp4", loop_video=False)
    wait_until(lambda: runtime.get_status("video")["status"] == "ended", timeout=2.0)
    playback_duration = time.monotonic() - started
    status = manager.get_status("video")["realtime"]
    assert playback_duration < 0.8
    assert status["max_pending"] <= 1
    if vision_delay:
        assert status["vision_frames_overwritten"] > 0
    runtime.stop("video")
    manager.stop()
