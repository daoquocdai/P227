import asyncio
import threading
import time
from uuid import uuid4

import numpy as np
import pytest

from src.database import database_connection
from src.models.frame import FramePacket
from src.models.vision import VisionDetection, VisionEvent, VisionResult
from src.services.event_service import EventService, VisionEventSink
from src.services.frame_hub import FrameHub
from src.services.sqlite_event_repository import stable_uuid
from src.services.stream_service import StreamService
from src.services.synchronous_vision_manager import SynchronousVisionManager
from src.services.vision_event_dispatcher import ThreadsafeVisionEventDispatcher


class FakeEngine:
    identity_enabled = False

    def __init__(self, event_id=None):
        self.processed_frame_ids = []
        self.event_id = event_id

    def start(self):
        pass

    def stop(self):
        pass

    def prepare_camera(self, camera_id, session):
        pass

    def release_camera(self, camera_id):
        pass

    def set_identity_enabled(self, enabled):
        self.identity_enabled = enabled

    def process(self, packet, session):
        self.processed_frame_ids.append(packet.frame_id)
        events = (
            [VisionEvent("fall_confirmed", 0.95, {"event_id": self.event_id})]
            if self.event_id is not None
            else []
        )
        return VisionResult(
            packet.camera_id,
            packet.frame_id,
            packet.captured_at,
            packet.captured_at,
            1.0,
            events=events,
            metadata={
                "sampled": packet.frame_id % 2 == 0,
                "observation_time": packet.source_timestamp,
                "source_epoch": packet.source_epoch,
            },
        )


def packet(frame_id):
    return FramePacket(
        "cam", frame_id, float(frame_id), np.zeros((4, 4, 3), dtype=np.uint8),
        source_timestamp=float(frame_id), source_frame_index=frame_id,
    )


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_manager_keeps_one_session_with_one_latest_slot_worker():
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    manager.process(packet(2))
    wait_until(lambda: manager.latest_result("cam") is not None)
    status = manager.get_status("cam")
    assert status["worker_threads"] == 1
    assert status["processed_frames"] == 1
    assert status["last_result"]["frame_id"] == 2
    assert status["temporal"]["pre_vision_sampler"] is None
    manager.stop()


def test_identity_toggle_does_not_replace_session():
    engine = FakeEngine()
    manager = SynchronousVisionManager(engine)
    manager.start()
    manager.enable("cam")
    session = manager._sessions["cam"]
    manager.set_identity_enabled("cam", True)
    assert manager._sessions["cam"] is session
    assert manager.get_status("cam")["identity_enabled"] is True
    manager.stop()


def test_identity_is_not_visible_to_capture_until_native_model_is_ready():
    class SlowIdentityEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.initializing = threading.Event()
            self.release_initialization = threading.Event()
            self.model_ready = False

        def set_identity_enabled(self, enabled):
            self.initializing.set()
            assert self.release_initialization.wait(2)
            self.model_ready = True
            super().set_identity_enabled(enabled)

        def process(self, packet, session):
            if session.state.get("vision_identity_enabled") and not self.model_ready:
                raise AssertionError("capture observed identity before model readiness")
            return super().process(packet, session)

    engine = SlowIdentityEngine()
    manager = SynchronousVisionManager(engine)
    manager.start()
    manager.enable("cam")
    toggle = threading.Thread(target=manager.set_identity_enabled, args=("cam", True))
    toggle.start()
    assert engine.initializing.wait(1)

    assert manager.get_status("cam")["identity_enabled"] is False
    manager.process(packet(2))
    wait_until(lambda: manager.latest_result("cam") is not None)
    assert manager.latest_result("cam").frame_id == 2

    engine.release_initialization.set()
    toggle.join(2)
    assert not toggle.is_alive()
    assert manager.get_status("cam")["identity_enabled"] is True
    manager.process(packet(4))
    wait_until(
        lambda: manager.latest_result("cam") is not None
        and manager.latest_result("cam").frame_id == 4
    )
    manager.stop()


def test_multiple_viewers_only_render_the_single_backend_result():
    hub = FrameHub()
    engine = FakeEngine()
    manager = SynchronousVisionManager(engine)
    manager.start()
    manager.enable("cam")
    frame = packet(2)
    manager.process(frame)
    wait_until(lambda: manager.latest_result("cam") is not None)
    hub.publish(frame)
    stream = StreamService(hub, vision=manager)

    viewer_a = stream.mjpeg("cam")
    viewer_b = stream.mjpeg("cam")
    viewer_c = stream.mjpeg("cam")
    assert next(viewer_a).startswith(b"--frame")
    assert next(viewer_b).startswith(b"--frame")
    assert next(viewer_c).startswith(b"--frame")
    assert engine.processed_frame_ids == [2]
    manager.stop()


@pytest.mark.asyncio
async def test_stream_renders_a_fresh_latest_result_on_a_newer_raw_frame(monkeypatch):
    hub = FrameHub()
    processed_hub = FrameHub()
    engine = FakeEngine()
    manager = SynchronousVisionManager(engine, processed_frame_hub=processed_hub)
    manager.start()
    manager.enable("cam")
    old_packet = packet(2)
    manager.process(old_packet)
    wait_until(lambda: processed_hub.has_camera("cam"))
    hub.publish(old_packet)

    original_wait = hub.wait_for_next

    def advance_capture_before_return(*args, **kwargs):
        original_wait(*args, **kwargs)
        new_packet = packet(3)
        new_packet.source_timestamp = 2.2
        hub.publish(new_packet)
        return new_packet

    hub.wait_for_next = advance_capture_before_return
    rendered_result_ids = []

    def recording_renderer(frame, vision_result, **flags):
        del flags
        rendered_result_ids.append(vision_result.frame_id)
        return frame

    monkeypatch.setattr("src.vision.renderer.render_vision", recording_renderer)
    stream = StreamService(hub, vision=manager, processed_frame_hub=processed_hub)

    async def connected():
        return False

    generator = stream.mjpeg_async("cam", connected)
    assert (await anext(generator)).startswith(b"--frame")
    await generator.aclose()

    assert manager.latest_result("cam").frame_id == 2
    assert rendered_result_ids == [2]
    manager.stop()


@pytest.mark.asyncio
async def test_repeated_overlay_reconnects_do_not_invoke_inference_again():
    hub = FrameHub()
    processed_hub = FrameHub()
    engine = FakeEngine()
    manager = SynchronousVisionManager(engine, processed_frame_hub=processed_hub)
    manager.start()
    manager.enable("cam")
    captured = packet(2)
    manager.process(captured)
    wait_until(lambda: processed_hub.has_camera("cam"))
    hub.publish(captured)
    stream = StreamService(hub, vision=manager, processed_frame_hub=processed_hub)

    async def connected():
        return False

    for index in range(60):
        generator = stream.mjpeg_async(
            "cam",
            connected,
            show_boxes=bool(index % 2),
            show_identity=bool(index % 3),
            show_fall=bool(index % 5),
        )
        assert (await anext(generator)).startswith(b"--frame")
        await generator.aclose()

    assert engine.processed_frame_ids == [2]
    manager.stop()


@pytest.mark.asyncio
async def test_overlay_stream_falls_back_to_raw_when_vision_is_disabled():
    raw_hub = FrameHub()
    processed_hub = FrameHub()
    captured = packet(2)
    raw_hub.publish(captured)
    stream = StreamService(raw_hub, vision=object(), processed_frame_hub=processed_hub)

    async def connected():
        return False

    generator = stream.mjpeg_async(
        "cam",
        connected,
        show_boxes=True,
        show_identity=True,
        show_fall=True,
    )
    assert (await anext(generator)).startswith(b"--frame")
    await generator.aclose()


@pytest.mark.asyncio
async def test_running_stream_hides_identity_immediately_after_camera_gate_is_off(monkeypatch):
    hub = FrameHub()
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    manager.set_identity_enabled("cam", True)
    captured = packet(2)
    manager.offer(captured)
    wait_until(lambda: manager.latest_result("cam") is not None)
    manager.set_identity_enabled("cam", False)
    hub.publish(captured)
    observed = []

    def recording_renderer(frame, _result, **flags):
        observed.append(flags["show_identity"])
        return frame

    monkeypatch.setattr("src.vision.renderer.render_vision", recording_renderer)
    stream = StreamService(hub, vision=manager)

    async def connected():
        return False

    generator = stream.mjpeg_async("cam", connected, show_identity=True)
    assert (await anext(generator)).startswith(b"--frame")
    await generator.aclose()
    assert observed == [False]
    manager.stop()


def test_fresh_overlay_is_accepted_and_too_stale_overlay_is_hidden():
    class Latest:
        def __init__(self, result):
            self.result = result

        def latest_result(self, _camera_id):
            return self.result

    result = FakeEngine().process(packet(2), object())
    stream = StreamService(FrameHub(), vision=Latest(result))
    current = packet(10)
    current.source_timestamp = 2.70
    assert stream._fresh_vision_result(current) is result
    current.source_timestamp = 4.0
    assert stream._fresh_vision_result(current) is None


def test_overlay_from_different_source_epoch_is_hidden():
    result = FakeEngine().process(packet(2), object())

    class Latest:
        def latest_result(self, _camera_id):
            return result

    current = packet(4)
    current.source_epoch = 1
    current.source_timestamp = 2.1
    assert StreamService(FrameHub(), vision=Latest())._fresh_vision_result(current) is None


@pytest.mark.asyncio
async def test_no_viewer_still_updates_result_and_persists_fall_event():
    event_id = f"no-viewer-{uuid4()}"
    sink = VisionEventSink(EventService(), maxsize=4)
    sink.start()
    consumer = asyncio.create_task(sink.consume())
    dispatcher = ThreadsafeVisionEventDispatcher(sink)
    dispatcher.start(asyncio.get_running_loop())
    manager = SynchronousVisionManager(FakeEngine(event_id), dispatcher)
    manager.start()
    manager.enable("cam")
    try:
        captured = packet(2)
        manager.process(captured)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with database_connection() as connection:
                row = connection.execute(
                    "SELECT id FROM events WHERE id = ?", (stable_uuid(event_id, "event"),)
                ).fetchone()
            if row is not None:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("fall event was not persisted")

        assert manager.latest_result("cam").frame_id == 2
        assert manager.get_status("cam")["processed_frames"] == 1
    finally:
        manager.stop()
        dispatcher.stop()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        sink.stop()


def test_latest_slot_is_capacity_one_and_overwrites_pending_frames():
    from src.services.synchronous_vision_manager import LatestFrameSlot

    slot = LatestFrameSlot()
    assert slot.offer(packet(2)) is False
    assert slot.offer(packet(4)) is True
    assert slot.offer(packet(6)) is True
    assert slot.pending == 1
    assert slot.max_pending == 1
    assert slot.overwritten == 2
    assert slot.take().frame_id == 6


def test_latest_slot_keeps_discontinuity_sticky_when_boundary_packet_is_overwritten():
    from dataclasses import replace

    from src.services.synchronous_vision_manager import LatestFrameSlot

    slot = LatestFrameSlot()
    assert slot.offer(replace(packet(2), discontinuity=True)) is False
    assert slot.offer(replace(packet(4), discontinuity=False)) is True

    latest = slot.take()
    assert latest.frame_id == 4
    assert latest.discontinuity is True

    assert slot.offer(replace(packet(6), discontinuity=False)) is False
    assert slot.take().discontinuity is False


def test_blocked_vision_keeps_latest_source_frame_without_backlog():
    class BlockingEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def process(self, frame_packet, session):
            self.entered.set()
            assert self.release.wait(2)
            return super().process(frame_packet, session)

    engine = BlockingEngine()
    manager = SynchronousVisionManager(engine)
    manager.start()
    manager.enable("cam")
    manager.offer(packet(2))
    assert engine.entered.wait(1)
    for frame_id in (4, 6, 8, 10):
        manager.offer(packet(frame_id))
    status = manager.get_status("cam")["realtime"]
    assert status["pending"] == 1
    assert status["max_pending"] == 1
    assert status["vision_frames_overwritten"] == 3
    engine.release.set()
    wait_until(lambda: engine.processed_frame_ids == [2, 10])
    manager.stop()


def test_source_sampling_is_independent_of_consumer_call_count():
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    for frame_id in (101, 104, 107, 110):
        manager.offer(packet(frame_id))
    wait_until(lambda: manager.get_status("cam")["realtime"]["vision_frames_processed"] > 0)
    assert all(frame_id % 2 == 0 for frame_id in manager.engine.processed_frame_ids)
    assert manager.get_status("cam")["realtime"]["vision_frames_eligible"] == 2
    manager.stop()


def test_old_epoch_pending_packet_is_discarded():
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    old = packet(2)
    old.source_epoch = 0
    new = packet(4)
    new.source_epoch = 1
    new.discontinuity = True
    manager.offer(old)
    manager.offer(new)
    wait_until(lambda: manager.latest_result("cam") is not None and manager.latest_result("cam").frame_id == 4)
    assert manager.latest_result("cam").frame_id == 4
    manager.stop()


def test_vision_exception_isolated_and_next_frame_is_processed():
    class FailingOnceEngine(FakeEngine):
        def process(self, frame_packet, session):
            if frame_packet.frame_id == 2:
                raise RuntimeError("boom")
            return super().process(frame_packet, session)

    manager = SynchronousVisionManager(FailingOnceEngine())
    manager.start()
    manager.enable("cam")
    manager.offer(packet(2))
    wait_until(lambda: manager.get_status("cam")["current_error"] == "boom")
    manager.offer(packet(4))
    wait_until(lambda: manager.latest_result("cam") is not None)
    assert manager.latest_result("cam").frame_id == 4
    manager.stop()


def test_shutdown_wakes_blocked_slot_consumer():
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    wait_until(lambda: manager.get_status("cam")["worker_threads"] == 1)
    manager.stop()
    assert manager.get_status("cam")["worker_threads"] == 0


def test_turning_identity_off_during_inference_blocks_unknown_commit_and_preserves_fall(
    tmp_path, monkeypatch
):
    from src.services import event_snapshot

    monkeypatch.setattr(event_snapshot, "SNAPSHOT_ROOT", tmp_path)

    class InFlightUnknownEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def process(self, frame_packet, session):
            self.entered.set()
            assert self.release.wait(2)
            return VisionResult(
                frame_packet.camera_id,
                frame_packet.frame_id,
                frame_packet.captured_at,
                frame_packet.captured_at,
                1.0,
                detections=[
                    VisionDetection(
                        "person",
                        0.9,
                        (0, 0, 4, 4),
                        7,
                        {
                            "identity_status": "UNKNOWN",
                            "identity_state": "LOCKED_UNKNOWN",
                            "identity_face_detected": True,
                            "identity_similarity": 0.0,
                        },
                    )
                ],
                events=[VisionEvent("fall_confirmed", 0.99, {"event_id": "fall-stays"})],
                metadata={
                    "sampled": True,
                    "observation_time": frame_packet.source_timestamp,
                    "source_epoch": frame_packet.source_epoch,
                },
            )

    class RecordingDispatcher:
        def __init__(self):
            self.event_types = []

        def dispatch(self, vision_result):
            self.event_types.extend(event.type for event in vision_result.events)

    engine = InFlightUnknownEngine()
    dispatcher = RecordingDispatcher()
    manager = SynchronousVisionManager(engine, dispatcher)
    manager.start()
    manager.enable("cam")
    manager.set_identity_enabled("cam", True)
    manager.offer(packet(2))
    assert engine.entered.wait(1)

    manager.set_identity_enabled("cam", False)
    engine.release.set()
    wait_until(lambda: manager.latest_result("cam") is not None)

    result = manager.latest_result("cam")
    assert dispatcher.event_types == ["fall_confirmed"]
    assert [event.type for event in result.events] == ["fall_confirmed"]
    assert result.detections[0].metadata == {}
    assert manager.get_status("cam")["identity_enabled"] is False
    # The fake engine has no privacy detector, so the Fall event is preserved
    # while unsafe visual evidence is deliberately omitted.
    assert len(list(tmp_path.glob("*.jpg"))) == 0
    manager.stop()


def test_identity_off_clears_pending_cache_and_latest_overlay_then_on_starts_fresh():
    manager = SynchronousVisionManager(FakeEngine())
    manager.start()
    manager.enable("cam")
    manager.set_identity_enabled("cam", True)
    session = manager._sessions["cam"]
    session.state["vision_face_cache"] = {7: {"status": "PENDING"}}
    stale = VisionResult(
        "cam",
        2,
        2.0,
        2.0,
        1.0,
        detections=[
            VisionDetection(
                "person",
                0.9,
                metadata={"identity_status": "UNKNOWN", "identity_state": "LOCKED_UNKNOWN"},
            )
        ],
        events=[VisionEvent("unknown_person", 0.9)],
    )
    manager._last_results["cam"] = stale
    generation_before = session.state["vision_identity_generation"]

    manager.set_identity_enabled("cam", False)
    assert "vision_face_cache" not in session.state
    assert stale.events == []
    assert stale.detections[0].metadata == {}
    assert session.state["vision_identity_generation"] == generation_before + 1

    manager.set_identity_enabled("cam", True)
    assert "vision_face_cache" not in session.state
    assert session.state["vision_identity_generation"] == generation_before + 2
    manager.stop()


def test_stale_identity_generation_strips_unknown_but_preserves_fall():
    result = VisionResult(
        "cam",
        2,
        2.0,
        2.0,
        1.0,
        events=[
            VisionEvent("unknown_person", 0.99),
            VisionEvent("fall_confirmed", 0.98),
        ],
    )

    SynchronousVisionManager._strip_identity(result)

    assert [event.type for event in result.events] == ["fall_confirmed"]


@pytest.mark.parametrize("identity_enabled", [False, True])
def test_fall_dispatch_is_independent_of_identity_state(identity_enabled):
    class RecordingDispatcher:
        event_types = []

        def dispatch(self, vision_result):
            self.event_types.extend(event.type for event in vision_result.events)

    dispatcher = RecordingDispatcher()
    manager = SynchronousVisionManager(FakeEngine("fall-independent"), dispatcher)
    manager.start()
    manager.enable("cam")
    manager.set_identity_enabled("cam", identity_enabled)
    manager.offer(packet(2))
    wait_until(lambda: manager.latest_result("cam") is not None)

    assert dispatcher.event_types == ["fall_confirmed"]
    manager.stop()


def test_slow_exact_frame_snapshot_does_not_block_next_vision_frame(monkeypatch):
    snapshot_entered = threading.Event()
    release_snapshot = threading.Event()
    snapshotted_pixels = []

    def slow_snapshot(frame_packet, _result, privacy_face_detector=None):
        del privacy_face_detector
        snapshot_entered.set()
        assert release_snapshot.wait(2)
        snapshotted_pixels.append(int(frame_packet.frame[0, 0, 0]))

    class OneEventEngine(FakeEngine):
        def process(self, frame_packet, session):
            self.event_id = "exact-frame" if frame_packet.frame_id == 2 else None
            return super().process(frame_packet, session)

    class RecordingDispatcher:
        def __init__(self):
            self.frames = []

        def dispatch(self, result):
            self.frames.append(result.frame_id)
            return True

    monkeypatch.setattr(
        "src.services.synchronous_vision_manager.attach_event_snapshots", slow_snapshot
    )
    dispatcher = RecordingDispatcher()
    manager = SynchronousVisionManager(OneEventEngine(), dispatcher)
    manager.start()
    manager.enable("cam")
    first = packet(2)
    first.frame.fill(17)
    manager.offer(first)
    assert snapshot_entered.wait(1)
    first.frame.fill(99)
    manager.offer(packet(4))
    wait_until(lambda: manager.latest_result("cam").frame_id == 4)
    assert dispatcher.frames == []
    release_snapshot.set()
    wait_until(lambda: dispatcher.frames == [2])
    assert snapshotted_pixels == [17]
    manager.stop()


def test_event_work_queue_is_bounded_and_saturation_preserves_core_event():
    class RecordingDispatcher:
        def __init__(self):
            self.frames = []

        def dispatch(self, result):
            self.frames.append(result.frame_id)
            return True

    dispatcher = RecordingDispatcher()
    manager = SynchronousVisionManager(FakeEngine(), dispatcher)
    for frame_id in range(0, manager.EVENT_QUEUE_CAPACITY * 2, 2):
        captured = packet(frame_id)
        result = FakeEngine("queued").process(captured, object())
        manager._enqueue_event_work(captured, result)
    overflow = packet(100)
    manager._enqueue_event_work(overflow, FakeEngine("overflow").process(overflow, object()))
    assert manager._event_queue.qsize() == manager.EVENT_QUEUE_CAPACITY
    assert dispatcher.frames == [100]
