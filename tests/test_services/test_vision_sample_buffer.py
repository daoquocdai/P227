import threading
import time

import numpy as np

from src.models.frame import FramePacket
from src.services.frame_hub import FrameHub
from src.services.vision_manager import VisionManager
from src.services.vision_sample_buffer import VisionSampleBuffer
from src.vision.adapters.mock import MockVisionEngine


def packet(camera_id: str, frame_id: int, timestamp: float, *, epoch: int = 0, discontinuity: bool = False):
    return FramePacket(
        camera_id=camera_id,
        frame_id=frame_id,
        captured_at=1_000.0 + timestamp,
        frame=np.zeros((4, 4, 3), dtype=np.uint8),
        source_timestamp=timestamp,
        source_epoch=epoch,
        discontinuity=discontinuity,
    )


def test_target_grid_preserves_legacy_pairing_and_model_observation_cadence():
    buffer = VisionSampleBuffer(target_sample_rate=15.0, legacy_skip_factor=2, capacity=8)
    buffer.enable("cam01")

    accepted = [buffer.offer(packet("cam01", index, index / 30.0)) for index in range(6)]
    selected = [buffer.get_nowait("cam01") for _ in range(6)]

    assert accepted == [True] * 6
    assert [item.frame_id for item in selected] == list(range(6))
    # Legacy processes the first packet in each pair and skips the second.
    assert [item.source_timestamp for item in selected[::2]] == [0.0, 2 / 30.0, 4 / 30.0]
    assert buffer.get_status("cam01")["target_sample_rate"] == 15.0
    assert buffer.get_status("cam01")["target_input_rate"] == 30.0


def test_buffer_is_bounded_nonblocking_and_drops_oldest_pairs_on_overload():
    buffer = VisionSampleBuffer(capacity=8)
    buffer.enable("cam01")
    finished = threading.Event()

    def produce():
        for index in range(60):
            buffer.offer(packet("cam01", index, index / 30.0))
        finished.set()

    thread = threading.Thread(target=produce)
    thread.start()
    assert finished.wait(0.5)
    thread.join()

    status = buffer.get_status("cam01")
    remaining = []
    while item := buffer.get_nowait("cam01"):
        remaining.append(item.frame_id)
    assert status["buffer_depth"] <= 8
    assert status["overload_count"] > 0
    assert status["temporal_drop_count"] > 0
    assert status["temporal_fidelity"] == "degraded"
    assert status["degraded_reason"] == "buffer_overload"
    assert remaining == list(range(52, 60))


def test_discontinuity_clears_queue_and_starts_new_source_epoch():
    buffer = VisionSampleBuffer()
    buffer.enable("cam01")
    for index in range(4):
        buffer.offer(packet("cam01", index, index / 30.0))

    reset = packet("cam01", 4, 0.0, epoch=1, discontinuity=True)
    assert buffer.offer(reset)
    assert buffer.get_nowait("cam01") is reset
    assert buffer.get_nowait("cam01") is None
    status = buffer.get_status("cam01")
    assert status["source_epoch"] == 1
    assert status["last_discontinuity"]["reason"] == "packet_discontinuity"
    assert status["temporal_drop_count"] == 0


def test_timestamp_rollback_and_major_gap_become_vision_discontinuities():
    buffer = VisionSampleBuffer()
    buffer.enable("cam01")
    buffer.offer(packet("cam01", 0, 10.0))
    buffer.get_nowait("cam01")

    buffer.offer(packet("cam01", 1, 1.0))
    rollback = buffer.get_nowait("cam01")
    assert rollback.discontinuity is True
    assert buffer.get_status("cam01")["last_discontinuity"]["reason"] == "timestamp_rollback"

    buffer.offer(packet("cam01", 2, 10.0))
    major_gap = buffer.get_nowait("cam01")
    assert major_gap.discontinuity is True
    assert buffer.get_status("cam01")["last_discontinuity"]["reason"] == "major_source_gap"


def test_source_gap_and_state_are_isolated_per_camera():
    buffer = VisionSampleBuffer()
    buffer.enable("cam01")
    buffer.enable("cam02")
    buffer.offer(packet("cam01", 0, 0.0))
    buffer.offer(packet("cam01", 1, 0.2))
    buffer.offer(packet("cam02", 0, 0.0))

    assert buffer.get_status("cam01")["temporal_fidelity"] == "degraded"
    assert buffer.get_status("cam01")["temporal_drop_count"] > 0
    assert buffer.get_status("cam02")["temporal_drop_count"] == 0


def test_disable_clears_sampler_and_worker_shutdown_wakes_cleanly():
    hub = FrameHub()
    buffer = VisionSampleBuffer()
    manager = VisionManager(hub, MockVisionEngine(), sample_buffer=buffer)
    manager.start()
    manager.enable("cam01")
    buffer.offer(packet("cam01", 1, 0.0))
    manager.disable("cam01")

    assert buffer.get_nowait("cam01") is None
    assert manager.get_status("cam01")["temporal"]["temporal_fidelity"] == "unavailable"
    started = time.monotonic()
    manager.stop()
    assert time.monotonic() - started < 1.0
    assert not manager.worker.is_running


def test_strict_requires_a_complete_source_time_window_without_drops():
    buffer = VisionSampleBuffer()
    buffer.enable("cam01")
    first = packet("cam01", 0, 0.0)
    buffer.note_result(first, {"sampled": True, "window_source_time_span": None})
    last = packet("cam01", 126, 4.2)
    buffer.note_result(last, {"sampled": True, "window_source_time_span": 4.2})

    status = buffer.get_status("cam01")
    assert status["window_source_time_span"] == 4.2
    assert status["temporal_fidelity"] == "strict"
