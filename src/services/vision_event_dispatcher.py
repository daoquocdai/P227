import asyncio
import logging
import threading
import uuid
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from src.models.schemas import VisionEventRequest
from src.models.vision import VisionEvent, VisionResult
from src.services.event_service import VisionEventSink

logger = logging.getLogger(__name__)

EVENT_TYPE_MAP = {
    "fall": "FALL_SUSPECTED",
    "fall_suspected": "FALL_SUSPECTED",
    "fall_confirmed": "FALL_CONFIRMED",
    "unknown_person": "UNKNOWN_PERSON",
    "person_recognized": "PERSON_RECOGNIZED",
    "inactivity": "INACTIVITY_DETECTED",
    "inactivity_detected": "INACTIVITY_DETECTED",
}


class VisionEventAdapter:
    """Map semantic Vision events to the existing backend ingestion contract."""

    def adapt(self, result: VisionResult) -> list[VisionEventRequest]:
        return [self._event(result, event, index) for index, event in enumerate(result.events)]

    def _event(self, result: VisionResult, event: VisionEvent, index: int) -> VisionEventRequest:
        normalized = event.type.strip().lower()
        event_type = EVENT_TYPE_MAP.get(normalized)
        if event_type is None:
            raise ValueError(f"Unsupported Vision event type: {event.type}")

        metadata = dict(event.metadata)
        source_identity = metadata.get("event_id")
        if not source_identity:
            canonical = f"{result.camera_id}:{normalized}:{result.frame_id}:{index}"
            source_identity = f"vision:{uuid5(NAMESPACE_URL, canonical)}"

        camera_location = str(
            metadata.get("camera_location")
            or result.metadata.get("camera_location")
            or result.camera_id
        )
        domain_metadata = dict(metadata)
        domain_metadata.update(
            {
                "source_frame_id": result.frame_id,
                "internal_event_type": event.type,
                "vision_processing_ms": result.processing_ms,
            }
        )
        return VisionEventRequest(
            event_id=str(source_identity),
            camera_id=result.camera_id,
            camera_location=camera_location,
            event_type=event_type,
            occurred_at=datetime.fromtimestamp(result.captured_at, UTC),
            confidence=event.confidence,
            track_id=str(metadata["track_id"]) if metadata.get("track_id") is not None else None,
            identity_status=metadata.get("identity_status", "UNKNOWN"),
            identity_name=metadata.get("identity_name"),
            snapshot_path=metadata.get("snapshot_path"),
            immobile_seconds=metadata.get("immobile_seconds"),
            metadata=domain_metadata,
        )


class ThreadsafeVisionEventDispatcher:
    """Bounded, non-blocking handoff from VisionWorker to the FastAPI loop."""

    def __init__(self, sink: VisionEventSink, adapter: VisionEventAdapter | None = None) -> None:
        self._sink = sink
        self._adapter = adapter or VisionEventAdapter()
        self._slots = threading.BoundedSemaphore(sink.maxsize)
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._accepting = False
        self._stats: dict[str, dict] = {}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._accepting = True

    def stop(self) -> None:
        with self._lock:
            self._accepting = False
            self._loop = None

    def dispatch(self, result: VisionResult) -> bool:
        if not result.events:
            return True
        try:
            events = self._adapter.adapt(result)
        except Exception as exc:  # noqa: BLE001 - reject invalid adapter output at the boundary
            self._record_error(result.camera_id, exc)
            logger.warning("Vision event rejected camera=%s error=%s", result.camera_id, exc)
            return False

        accepted = True
        for event in events:
            if not self._schedule(event):
                accepted = False
        return accepted

    def get_status(self, camera_id: str) -> dict:
        with self._lock:
            values = self._stats.get(camera_id, {})
            return {
                "emitted_events": values.get("emitted_events", 0),
                "dropped_events": values.get("dropped_events", 0),
                "dispatch_errors": values.get("dispatch_errors", 0),
                "last_event_error": values.get("last_event_error"),
            }

    def _schedule(self, event: VisionEventRequest) -> bool:
        with self._lock:
            loop = self._loop
            accepting = self._accepting
        if not accepting or loop is None or loop.is_closed():
            self._record_drop(event.camera_id, "dispatcher is not accepting events")
            return False
        if not self._slots.acquire(blocking=False):
            self._record_drop(event.camera_id, "event dispatch capacity is full")
            return False
        try:
            loop.call_soon_threadsafe(self._enqueue_on_loop, event)
            return True
        except RuntimeError as exc:
            self._slots.release()
            self._record_error(event.camera_id, exc)
            return False

    def _enqueue_on_loop(self, event: VisionEventRequest) -> None:
        with self._lock:
            accepting = self._accepting
        if not accepting:
            self._slots.release()
            self._record_drop(event.camera_id, "dispatcher stopped before enqueue")
            return
        try:
            delivery = self._sink.publish_nowait(event)
        except (asyncio.QueueFull, RuntimeError) as exc:
            self._slots.release()
            self._record_drop(event.camera_id, str(exc))
            return
        delivery.add_done_callback(lambda future: self._delivery_done(event, future))

    def _delivery_done(self, event: VisionEventRequest, future: asyncio.Future) -> None:
        self._slots.release()
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - persistence failures are isolated from Vision
            self._record_error(event.camera_id, exc)
            logger.error("Vision event delivery failed camera=%s event=%s error=%s", event.camera_id, event.event_id, exc)
            return
        with self._lock:
            stats = self._stats.setdefault(event.camera_id, {})
            stats["emitted_events"] = stats.get("emitted_events", 0) + 1
        logger.info("Vision business event emitted camera=%s type=%s event=%s", event.camera_id, event.event_type, event.event_id)

    def _record_drop(self, camera_id: str, message: str) -> None:
        with self._lock:
            stats = self._stats.setdefault(camera_id, {})
            stats["dropped_events"] = stats.get("dropped_events", 0) + 1
            stats["last_event_error"] = message
        logger.warning("Vision event dropped camera=%s error=%s", camera_id, message)

    def _record_error(self, camera_id: str, exc: Exception) -> None:
        with self._lock:
            stats = self._stats.setdefault(camera_id, {})
            stats["dispatch_errors"] = stats.get("dispatch_errors", 0) + 1
            stats["last_event_error"] = str(exc)
