import asyncio
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest
from sda_vision import (
    IdentityGalleryEntry,
    IdentityGallerySnapshot,
    VisionFrameResult,
    VisionSourceFrame,
)
from sda_vision import (
    VisionDetection as SdaDetection,
)
from sda_vision import (
    VisionEvent as SdaEvent,
)

from src.database import database_connection
from src.integrations.sda_vision import (
    SdaEventMediaWorker,
    SdaSessionRegistry,
    map_source_frame,
    map_vision_result,
)
from src.services.event_service import EventService, VisionEventSink
from src.services.frame_hub import FrameHub
from src.services.vision_event_dispatcher import ThreadsafeVisionEventDispatcher
from src.services.vision_product_policy import VisionProductPolicy


def sda_result(
    *,
    sequence=7,
    epoch=2,
    events=(),
    identity_state="LOCKED_KNOWN",
    identity_status="KNOWN",
    identity_name="Mai",
    identity_confidence=0.91,
    identity_face_verified=True,
    association_id=3,
):
    return VisionFrameResult(
        camera_id="cam",
        frame_sequence=sequence,
        source_frame_index=6,
        source_epoch=epoch,
        source_time_s=0.2,
        captured_wall_time=datetime.now(UTC),
        current_action="Khong nga",
        fall_state="CLEAR",
        fall_confidence=None,
        detections=(
            SdaDetection(
                "person",
                0.9,
                (10, 20, 100, 200),
                identity_state=identity_state,
                identity_status=identity_status,
                identity_name=identity_name,
                identity_confidence=identity_confidence,
                identity_person_id="person-1",
                identity_face_verified=identity_face_verified,
                face_bbox=(30, 40, 60, 80) if identity_face_verified else None,
                association_id=association_id,
            ),
        ),
        generated_events=events,
        stage_metrics={"effective_fps": 15.0, "total_vision_ms": 48.0},
    )


def test_source_frame_maps_without_copy_or_credential_exposure():
    frame = np.zeros((4, 5, 3), dtype=np.uint8)
    packet = map_source_frame(VisionSourceFrame("cam", 8, 7, 3, 0.25, None, frame))
    assert packet.frame is frame
    assert (packet.frame_id, packet.source_epoch, packet.source_frame_index) == (8, 3, 7)
    assert packet.discontinuity is False


def test_result_adapter_keeps_source_space_bbox_and_exact_face_correlation():
    mapped = map_vision_result(sda_result(), camera_location="Kitchen", identity_enabled=True)
    detection = mapped.detections[0]
    assert detection.bbox_xyxy == (10, 20, 100, 200)
    assert detection.metadata["bbox_coordinate_space"] == "source_pixels"
    assert detection.metadata["identity_face_bbox_xyxy"] == (30, 40, 60, 80)
    assert detection.metadata["identity_face_bbox_frame_id"] == mapped.frame_id
    assert detection.metadata["identity_face_verified"] is True
    assert mapped.metadata["geometry"]["scale"] == 1.0
    assert detection.metadata["identity_person_id"] == "person-1"


def test_registry_broadcasts_latest_gallery_to_active_sessions():
    class Session:
        def __init__(self):
            self.snapshots = []

        def update_identity_gallery(self, snapshot):
            self.snapshots.append(snapshot)

    settings = SimpleNamespace(vision_identity_enabled=False)
    registry = SdaSessionRegistry(FrameHub(), settings=settings)
    session = Session()
    registry._records["cam"] = SimpleNamespace(session=session)
    snapshot = IdentityGallerySnapshot(4, (IdentityGalleryEntry("person-1", "Mai", np.ones(4)),))
    result = registry.update_identity_gallery(snapshot)
    assert session.snapshots == [snapshot]
    assert registry._identity_gallery is snapshot
    assert result["sessions"] == 1


def test_identity_off_strips_identity_facts_and_events():
    event = SdaEvent("UNKNOWN_PERSON", 0.8, 7, 0.2, identity_state="LOCKED_UNKNOWN")
    mapped = map_vision_result(sda_result(events=(event,)), camera_location="Kitchen", identity_enabled=False)
    assert mapped.events == []
    assert "identity_state" not in mapped.detections[0].metadata


def test_event_adapter_preserves_exact_source_correlation_once():
    event = SdaEvent("FALL_CONFIRMED", 0.9, 7, 0.2, person_bbox=(10, 20, 100, 200), metadata={"origin": "sda"})
    mapped = map_vision_result(sda_result(events=(event,)), camera_location="Kitchen", identity_enabled=True)
    assert len(mapped.events) == 1
    metadata = mapped.events[0].metadata
    assert metadata["frame_id"] == 7
    assert metadata["source_epoch"] == 2
    assert metadata["source_frame_index"] == 6
    assert metadata["observation_time"] == 0.2
    assert metadata["person_bbox_xyxy"] == (10, 20, 100, 200)
    assert metadata["person_bbox_coordinate_space"] == "source_pixels"
    assert metadata["origin"] == "sda"


def test_event_handoff_is_bounded_and_overflow_preserves_semantic_delivery():
    class Dispatcher:
        def __init__(self):
            self.results = []

        def dispatch(self, result):
            self.results.append(result)
            return True

    dispatcher = Dispatcher()
    worker = SdaEventMediaWorker(dispatcher, capacity=1)
    event = SdaEvent("FALL_CONFIRMED", 0.9, 7, 0.2)
    result = map_vision_result(sda_result(events=(event,)), camera_location="Kitchen", identity_enabled=True)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    assert worker.submit(packet, result) is True
    assert worker.submit(packet, result) is False
    assert dispatcher.results == [result]
    assert worker.profile()["queue_full_drops"] == 1


def test_repeated_unknown_presence_is_coalesced_and_keeps_latest_pending_frame():
    worker = SdaEventMediaWorker(capacity=2)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))

    for sequence in range(100):
        mapped = map_vision_result(
            sda_result(
                sequence=sequence,
                identity_state="LOCKED_UNKNOWN",
                identity_status="UNKNOWN",
                identity_name=None,
                identity_confidence=0.10,
            ),
            camera_location="Kitchen",
            identity_enabled=True,
        )
        assert worker.submit(packet, mapped)

    profile = worker.profile()
    assert profile["submitted_policy_candidates"] == 100
    assert profile["coalesced_policy_candidates"] == 99
    assert profile["current_queue_depth"] == 1
    assert next(iter(worker._unknown_pending.values())).result.frame_id == 99


def test_unknown_coalesces_while_inflight(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    worker = SdaEventMediaWorker()

    class BlockingPolicy:
        def apply(self, result):
            entered.set()
            assert release.wait(1)
            return result

    worker._policy = BlockingPolicy()
    monkeypatch.setattr(
        "src.integrations.sda_vision.attach_event_snapshots", lambda packet, result, detector, **kwargs: None
    )
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))

    def unknown(sequence):
        return map_vision_result(
            sda_result(
                sequence=sequence,
                identity_state="LOCKED_UNKNOWN",
                identity_status="UNKNOWN",
                identity_name=None,
                identity_confidence=0.10,
            ),
            camera_location="Kitchen",
            identity_enabled=True,
        )

    worker.start()
    assert worker.submit(packet, unknown(7))
    assert entered.wait(1)
    assert worker.submit(packet, unknown(8))
    assert worker.profile()["coalesced_policy_candidates"] == 1
    assert worker.profile()["current_queue_depth"] == 0
    release.set()
    worker.stop()


def test_new_unknown_association_and_epoch_are_independent_candidates():
    worker = SdaEventMediaWorker(capacity=4)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))

    def unknown(*, epoch, association_id):
        return map_vision_result(
            sda_result(
                epoch=epoch,
                association_id=association_id,
                identity_state="LOCKED_UNKNOWN",
                identity_status="UNKNOWN",
                identity_name=None,
                identity_confidence=0.10,
            ),
            camera_location="Kitchen",
            identity_enabled=True,
        )

    assert worker.submit(packet, unknown(epoch=2, association_id=3))
    assert worker.submit(packet, unknown(epoch=2, association_id=4))
    assert worker.submit(packet, unknown(epoch=3, association_id=3))
    assert worker.profile()["current_queue_depth"] == 3
    assert worker.profile()["coalesced_policy_candidates"] == 0


def test_fall_is_accepted_while_unknown_candidate_is_pending():
    worker = SdaEventMediaWorker(capacity=1)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    unknown = map_vision_result(
        sda_result(
            identity_state="LOCKED_UNKNOWN",
            identity_status="UNKNOWN",
            identity_name=None,
            identity_confidence=0.10,
        ),
        camera_location="Kitchen",
        identity_enabled=True,
    )
    fall = map_vision_result(
        sda_result(events=(SdaEvent("FALL_CONFIRMED", 0.9, 8, 0.3),)),
        camera_location="Kitchen",
        identity_enabled=True,
    )
    assert worker.submit(packet, unknown)
    assert worker.submit(packet, fall)
    profile = worker.profile()
    assert profile["current_queue_depth"] == 2
    assert profile["submitted_semantic_events"] == 1
    assert profile["queue_full_drops"] == 0


def test_one_sda_event_is_dispatched_once_off_the_callback_thread(monkeypatch):
    class Dispatcher:
        def __init__(self):
            self.results = []

        def dispatch(self, result):
            self.results.append(result)
            return True

    dispatcher = Dispatcher()
    worker = SdaEventMediaWorker(dispatcher)
    worker._policy = SimpleNamespace(apply=lambda result: result)
    monkeypatch.setattr(
        "src.integrations.sda_vision.attach_event_snapshots", lambda packet, result, detector, **kwargs: None
    )
    event = SdaEvent("FALL_CONFIRMED", 0.9, 7, 0.2)
    result = map_vision_result(sda_result(events=(event,)), camera_location="Kitchen", identity_enabled=True)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    worker.start()
    assert worker.submit(packet, result)
    deadline = time.monotonic() + 1
    while not dispatcher.results and time.monotonic() < deadline:
        time.sleep(0.001)
    worker.stop()
    assert dispatcher.results == [result]


def test_snapshot_failure_never_suppresses_semantic_event(monkeypatch):
    dispatched = []
    worker = SdaEventMediaWorker(SimpleNamespace(dispatch=lambda result: dispatched.append(result)))
    worker._policy = SimpleNamespace(apply=lambda result: result)

    def fail_snapshot(packet, result, detector, **kwargs):
        raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr("src.integrations.sda_vision.attach_event_snapshots", fail_snapshot)
    event = SdaEvent("FALL_CONFIRMED", 0.9, 7, 0.2)
    result = map_vision_result(sda_result(events=(event,)), camera_location="Kitchen", identity_enabled=True)
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    worker.start()
    assert worker.submit(packet, result)
    _wait_for(lambda: bool(dispatched))
    worker.stop()
    assert dispatched == [result]


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert predicate()


def test_inconclusive_and_known_detections_do_not_enter_event_media_worker():
    worker = SdaEventMediaWorker()
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    for state, verified in (("UNVERIFIED", False), ("UNKNOWN", False), ("LOCKED_KNOWN", True)):
        mapped = map_vision_result(
            sda_result(identity_state=state, identity_face_verified=verified),
            camera_location="Kitchen",
            identity_enabled=True,
        )
        assert worker.submit(packet, mapped) is True
    assert worker.profile()["event_media_submitted"] == 0


def test_threshold_rejected_unknown_runs_policy_without_snapshot_or_dispatch(monkeypatch):
    dispatched = []
    snapshots = []
    worker = SdaEventMediaWorker(SimpleNamespace(dispatch=lambda result: dispatched.append(result)))
    worker._policy = VisionProductPolicy(clock=lambda: 100.0)
    monkeypatch.setattr(
        "src.integrations.sda_vision.attach_event_snapshots",
        lambda packet, result, detector, **kwargs: snapshots.append(result),
    )
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))
    mapped = map_vision_result(
        sda_result(
            identity_state="LOCKED_UNKNOWN",
            identity_status="UNKNOWN",
            identity_name=None,
            identity_confidence=0.30,
        ),
        camera_location="Kitchen",
        identity_enabled=True,
    )
    worker.start()
    assert worker.submit(packet, mapped)
    _wait_for(lambda: worker.profile()["event_media_no_event_after_policy"] == 1)
    worker.stop()
    assert dispatched == []
    assert snapshots == []


def test_unknown_cooldown_suppresses_second_alert(monkeypatch):
    dispatched = []
    snapshots = []
    worker = SdaEventMediaWorker(SimpleNamespace(dispatch=lambda result: dispatched.append(result)))
    worker._policy = VisionProductPolicy(clock=lambda: 100.0)
    monkeypatch.setattr(
        "src.integrations.sda_vision.attach_event_snapshots",
        lambda packet, result, detector, **kwargs: snapshots.append(result),
    )
    packet = map_source_frame(VisionSourceFrame("cam", 7, 6, 2, 0.2, None, np.zeros((2, 2, 3), np.uint8)))

    def unknown_result(sequence):
        return map_vision_result(
            sda_result(
                sequence=sequence,
                identity_state="LOCKED_UNKNOWN",
                identity_status="UNKNOWN",
                identity_name=None,
                identity_confidence=0.10,
            ),
            camera_location="Kitchen",
            identity_enabled=True,
        )

    worker.start()
    assert worker.submit(packet, unknown_result(7))
    _wait_for(lambda: len(dispatched) == 1)
    assert worker.submit(packet, unknown_result(8))
    _wait_for(lambda: worker.profile()["event_media_no_event_after_policy"] == 1)
    worker.stop()
    assert len(dispatched) == 1
    assert len(snapshots) == 1
    assert dispatched[0].events[0].type == "unknown_person"


@pytest.mark.asyncio
async def test_registry_locked_unknown_without_sda_event_persists_event_and_alert(monkeypatch):
    service = EventService()
    sink = VisionEventSink(service)
    dispatcher = ThreadsafeVisionEventDispatcher(sink)
    sink.start()
    dispatcher.start(asyncio.get_running_loop())
    consumer = asyncio.create_task(sink.consume())
    registry = SdaSessionRegistry(
        FrameHub(), settings=SimpleNamespace(vision_identity_enabled=True), event_dispatcher=dispatcher
    )
    registry._records["cam"] = SimpleNamespace(
        session=SimpleNamespace(identity_enabled=True),
        location="Kitchen",
        latest_result=None,
        processed_frames=0,
    )
    monkeypatch.setattr(
        "src.integrations.sda_vision.attach_event_snapshots", lambda packet, result, detector, **kwargs: None
    )
    registry.start()
    try:
        result = sda_result(
            identity_state="LOCKED_UNKNOWN",
            identity_status="UNKNOWN",
            identity_name=None,
            identity_confidence=0.10,
        )
        registry._on_result("cam", np.zeros((2, 2, 3), np.uint8), result)
        deadline = time.monotonic() + 2
        while dispatcher.get_status("cam")["emitted_events"] != 1 and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        assert dispatcher.get_status("cam")["emitted_events"] == 1
        with database_connection() as connection:
            event_row = connection.execute(
                "SELECT metadata_json FROM events WHERE event_type = 'person_detected'"
            ).fetchone()
            assert event_row is not None
            assert '"source_event_type": "UNKNOWN_PERSON"' in event_row["metadata_json"]
            assert connection.execute("SELECT 1 FROM alerts").fetchone()
        assert registry._events.profile()["product_policy_events_created"] == 1
    finally:
        registry._events.stop()
        dispatcher.stop()
        sink.stop()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer


def test_registry_separates_source_rate_from_result_rate_and_restart_epoch(monkeypatch):
    observed_epochs = []

    class FakeSession:
        def __init__(self, config, callbacks):
            self.config, self.callbacks = config, callbacks
            self.identity_enabled = config.identity_enabled
            self._stop_requested = False

        def run(self):
            observed_epochs.append(self.config.source_epoch)
            for index in range(30):
                frame = np.full((2, 2, 3), index, np.uint8)
                self.callbacks.on_source_frame(
                    VisionSourceFrame("cam", index + 1, index, self.config.source_epoch, index / 30, None, frame)
                )
                if index % 2:
                    self.callbacks.on_result_frame(
                        frame, sda_result(sequence=index + 1, epoch=self.config.source_epoch)
                    )

        def request_stop(self):
            self._stop_requested = True

        def shutdown(self):
            self._stop_requested = True

        def set_inference_enabled(self, enabled):
            pass

        def set_identity_enabled(self, enabled):
            self.identity_enabled = enabled

    monkeypatch.setattr("src.integrations.sda_vision.VisionSession", FakeSession)
    settings = SimpleNamespace(vision_identity_enabled=False, vision_device="cpu", vision_fps=15.0, log_level="ERROR")
    registry = SdaSessionRegistry(FrameHub(), settings=settings)
    registry.start_session("cam", "0", location="Kitchen")
    registry._records["cam"].thread.join(1)
    assert registry.camera_status("cam")["frames_published"] == 30
    assert registry.vision_status("cam")["processed_frames"] == 15
    assert registry.latest_result("cam").frame_id == 30
    registry.stop_session("cam")
    registry.start_session("cam", "0", location="Kitchen")
    registry._records["cam"].thread.join(1)
    assert observed_epochs == [0, 1]
    registry.stop_all()
