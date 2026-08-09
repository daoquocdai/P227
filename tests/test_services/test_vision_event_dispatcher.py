import asyncio
import time
from uuid import uuid4

import numpy as np
import pytest

from src.database import database_connection
from src.models.frame import FramePacket
from src.models.vision import VisionEvent, VisionResult
from src.runtime import LocalRuntime
from src.services.alert_broadcaster import alert_broadcaster
from src.services.event_service import EventService, VisionEventSink
from src.services.vision_event_dispatcher import (
    ThreadsafeVisionEventDispatcher,
    VisionEventAdapter,
)
from src.vision.adapters.mock import MockVisionEngine


def result(camera_id="camera-bedroom", frame_id=10, events=None):
    return VisionResult(
        camera_id=camera_id,
        frame_id=frame_id,
        captured_at=time.time(),
        processed_at=time.time(),
        processing_ms=1.25,
        events=list(events or []),
    )


async def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_empty_result_does_not_schedule_event():
    class Sink:
        maxsize = 1

    with database_connection() as connection:
        before = connection.execute("SELECT count(*) FROM events").fetchone()[0]
    dispatcher = ThreadsafeVisionEventDispatcher(Sink())
    assert dispatcher.dispatch(result()) is True
    assert dispatcher.get_status("camera-bedroom")["emitted_events"] == 0
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == before


def test_adapter_maps_internal_event_to_existing_contract_and_stable_identity():
    adapter = VisionEventAdapter()
    vision_result = result(
        camera_id="cam01",
        events=[VisionEvent(type="fall", confidence=0.95, metadata={"camera_location": "Phòng khách"})],
    )
    first = adapter.adapt(vision_result)[0]
    duplicate = adapter.adapt(vision_result)[0]

    assert first.event_type == "FALL_SUSPECTED"
    assert first.camera_id == "cam01"
    assert first.camera_location == "Phòng khách"
    assert first.confidence == 0.95
    assert first.event_id == duplicate.event_id
    assert first.snapshot_path is None


def test_adapter_rejects_unknown_taxonomy():
    with pytest.raises(ValueError, match="Unsupported Vision event type"):
        VisionEventAdapter().adapt(result(events=[VisionEvent(type="future_unknown", confidence=0.8)]))


@pytest.mark.asyncio
async def test_duplicate_delivery_persists_one_alert_and_broadcasts_sse():
    sink = VisionEventSink(EventService(), maxsize=4)
    sink.start()
    consumer = asyncio.create_task(sink.consume())
    dispatcher = ThreadsafeVisionEventDispatcher(sink)
    dispatcher.start(asyncio.get_running_loop())
    event_id = f"phase-e-{uuid4()}"
    vision_result = result(
        events=[
            VisionEvent(
                type="fall",
                confidence=0.95,
                metadata={"event_id": event_id, "camera_location": "Phòng ngủ"},
            )
        ]
    )
    subscriber = alert_broadcaster.subscribe()
    sse_message = asyncio.create_task(anext(subscriber))
    try:
        assert await asyncio.to_thread(dispatcher.dispatch, vision_result)
        assert await asyncio.to_thread(dispatcher.dispatch, vision_result)
        await wait_until(lambda: dispatcher.get_status("camera-bedroom")["emitted_events"] == 2)
        message = await asyncio.wait_for(sse_message, timeout=1)
        alerts = await EventService().list_alerts()

        assert message["type"] == "alert_created"
        assert message["alert"]["event_id"] == event_id
        assert len([alert for alert in alerts if alert["event_id"] == event_id]) == 1
    finally:
        dispatcher.stop()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        sink.stop()
        await subscriber.aclose()


@pytest.mark.asyncio
async def test_bounded_dispatch_drops_without_blocking_vision_thread():
    class PendingSink:
        maxsize = 1

        def publish_nowait(self, event):
            return asyncio.get_running_loop().create_future()

    dispatcher = ThreadsafeVisionEventDispatcher(PendingSink())
    dispatcher.start(asyncio.get_running_loop())
    event = VisionEvent(type="fall", confidence=0.95)
    try:
        assert await asyncio.to_thread(dispatcher.dispatch, result(frame_id=1, events=[event]))
        await asyncio.sleep(0)
        started = time.perf_counter()
        assert not await asyncio.to_thread(dispatcher.dispatch, result(frame_id=2, events=[event]))
        assert time.perf_counter() - started < 0.1
        assert dispatcher.get_status("camera-bedroom")["dropped_events"] == 1
    finally:
        dispatcher.stop()


@pytest.mark.asyncio
async def test_repository_failure_isolated_from_camera_vision_and_mjpeg(monkeypatch):
    class FailingService:
        async def create(self, event):
            raise RuntimeError("database unavailable")

    class Capture:
        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.01)
            return True, np.zeros((8, 8, 3), dtype=np.uint8)

        def get(self, prop):
            return 30.0

        def release(self):
            pass

    sink = VisionEventSink(FailingService(), maxsize=4)
    sink.start()
    consumer = asyncio.create_task(sink.consume())
    dispatcher = ThreadsafeVisionEventDispatcher(sink)
    dispatcher.start(asyncio.get_running_loop())
    runtime = LocalRuntime(
        vision_engine=MockVisionEngine(emit_event_on_frame_ids={0}),
        event_dispatcher=dispatcher,
    )
    monkeypatch.setattr(runtime.camera, "_open_capture", lambda source: Capture())
    runtime.start()
    try:
        runtime.vision.enable("cam01")
        runtime.camera.start("cam01", 0)
        await wait_until(lambda: dispatcher.get_status("cam01")["dispatch_errors"] == 1)
        await wait_until(lambda: runtime.vision.get_status("cam01")["processed_frames"] > 1)

        assert runtime.vision.get_status("cam01")["status"] == "running"
        assert runtime.vision.get_status("cam01")["current_error"] is None
        assert runtime.camera.get_status("cam01")["status"] == "online"
        assert runtime.vision.worker.is_running
        assert next(runtime.stream.mjpeg("cam01")).startswith(b"--frame\r\nContent-Type: image/jpeg")
    finally:
        runtime.stop()
        dispatcher.stop()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        sink.stop()


def test_two_camera_events_do_not_mix_identity():
    adapter = VisionEventAdapter()
    event = VisionEvent(type="fall", confidence=0.9)
    cam01 = adapter.adapt(result(camera_id="cam01", events=[event]))[0]
    cam02 = adapter.adapt(result(camera_id="cam02", events=[event]))[0]

    assert cam01.camera_id == "cam01"
    assert cam02.camera_id == "cam02"
    assert cam01.event_id != cam02.event_id


def test_disabled_vision_produces_no_result_or_event():
    class RecordingDispatcher:
        def __init__(self):
            self.results = []

        def dispatch(self, vision_result):
            self.results.append(vision_result)
            return True

        def get_status(self, camera_id):
            return {"emitted_events": 0, "dropped_events": 0, "dispatch_errors": 0, "last_event_error": None}

    dispatcher = RecordingDispatcher()
    runtime = LocalRuntime(
        vision_engine=MockVisionEngine(emit_event_on_frame_ids={1}),
        event_dispatcher=dispatcher,
    )
    runtime.start()
    try:
        runtime.frame_hub.publish(FramePacket("cam01", 1, time.time(), np.zeros((8, 8, 3), dtype=np.uint8)))
        time.sleep(0.1)
        assert runtime.vision.get_status("cam01")["status"] == "disabled"
        assert dispatcher.results == []
    finally:
        runtime.stop()


def test_unexpected_dispatch_callback_error_does_not_kill_vision_worker():
    class BrokenDispatcher:
        def dispatch(self, vision_result):
            raise RuntimeError("callback bug")

        def get_status(self, camera_id):
            return {"emitted_events": 0, "dropped_events": 0, "dispatch_errors": 0, "last_event_error": None}

    runtime = LocalRuntime(
        vision_engine=MockVisionEngine(emit_event_on_frame_ids={1}),
        event_dispatcher=BrokenDispatcher(),
    )
    runtime.start()
    try:
        runtime.vision.enable("cam01")
        runtime.frame_hub.publish(FramePacket("cam01", 1, time.time(), np.zeros((8, 8, 3), dtype=np.uint8)))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and runtime.vision.get_status("cam01")["processed_frames"] == 0:
            time.sleep(0.01)

        status = runtime.vision.get_status("cam01")
        assert status["status"] == "running"
        assert status["current_error"] is None
        assert status["event_dispatch"]["dispatch_errors"] == 1
        assert status["event_dispatch"]["last_event_error"] == "callback bug"
        assert runtime.vision.worker.is_running
    finally:
        runtime.stop()
