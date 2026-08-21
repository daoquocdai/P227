from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from uuid import uuid4

from sda_vision import IdentityGallerySnapshot, VisionCallbacks, VisionSession, VisionSessionConfig

from src.models.frame import FramePacket
from src.models.vision import VisionDetection, VisionEvent, VisionResult
from src.services.event_snapshot import MediaPipePrivacyFaceDetector, attach_event_snapshots
from src.services.frame_hub import FrameHub
from src.services.vision_product_policy import (
    VisionProductPolicy,
    needs_product_policy,
    unknown_product_policy_candidates,
)

logger = logging.getLogger(__name__)


def _wall_timestamp(value) -> float:
    return value.timestamp() if value is not None else time.time()


def map_source_frame(source_frame) -> FramePacket:
    return FramePacket(
        camera_id=source_frame.camera_id,
        frame_id=source_frame.frame_sequence,
        captured_at=_wall_timestamp(source_frame.captured_wall_time),
        frame=source_frame.frame,
        source_timestamp=source_frame.source_time_s,
        source_time_kind="media_timeline" if source_frame.source_frame_index is not None else "monotonic_arrival",
        source_epoch=source_frame.source_epoch,
        source_frame_index=source_frame.source_frame_index,
        discontinuity=source_frame.source_frame_index == 0,
    )


def map_vision_result(result, *, camera_location: str, identity_enabled: bool) -> VisionResult:
    detections = []
    if identity_enabled:
        for item in result.detections:
            track_id = item.association_id if isinstance(item.association_id, int) else None
            metadata = {
                "bbox_coordinate_space": "source_pixels",
                "identity_state": item.identity_state,
                "identity_status": item.identity_status,
                "identity_name": item.identity_name,
                "identity_person_id": item.identity_person_id,
                "identity_confidence": item.identity_confidence,
                "identity_similarity": item.identity_confidence,
                "identity_face_detected": item.face_bbox is not None,
                "identity_face_verified": item.identity_face_verified,
            }
            if item.face_bbox is not None:
                metadata.update(
                    identity_face_bbox_xyxy=item.face_bbox,
                    identity_face_bbox_frame_id=result.frame_sequence,
                    identity_face_bbox_coordinate_space="source_pixels",
                )
            detections.append(
                VisionDetection(
                    label=item.label,
                    confidence=float(item.confidence or 0.0),
                    bbox_xyxy=item.bbox,
                    track_id=track_id,
                    metadata=metadata,
                )
            )
    else:
        for item in result.detections:
            detections.append(
                VisionDetection(
                    label=item.label,
                    confidence=float(item.confidence or 0.0),
                    bbox_xyxy=item.bbox,
                    metadata={"bbox_coordinate_space": "source_pixels"},
                )
            )

    events = []
    for item in result.generated_events:
        normalized = item.event_type.strip().lower()
        if not identity_enabled and normalized in {"unknown_person", "person_recognized"}:
            continue
        metadata = dict(item.metadata)
        metadata.setdefault("event_id", f"sda:{uuid4()}")
        metadata.setdefault("camera_location", camera_location)
        metadata.setdefault("frame_id", item.frame_sequence)
        metadata.setdefault("source_epoch", result.source_epoch)
        metadata.setdefault("source_frame_index", result.source_frame_index)
        metadata.setdefault("observation_time", item.source_time_s)
        if item.person_bbox is not None:
            metadata.setdefault("person_bbox_xyxy", item.person_bbox)
            metadata.setdefault("person_bbox_coordinate_space", "source_pixels")
        if identity_enabled and (item.identity_state is not None or item.identity_name is not None):
            metadata.update(
                identity_state=item.identity_state,
                identity_status=("KNOWN" if item.identity_name else "UNKNOWN"),
                identity_name=item.identity_name,
                identity_person_id=item.identity_person_id,
            )
            if item.face_bbox is not None:
                metadata.update(
                    identity_face_bbox_xyxy=item.face_bbox,
                    identity_face_bbox_frame_id=item.frame_sequence,
                    identity_face_bbox_coordinate_space="source_pixels",
                )
        events.append(VisionEvent(normalized, float(item.confidence), metadata))

    captured_at = _wall_timestamp(result.captured_wall_time)
    stage_metrics = dict(result.stage_metrics)
    return VisionResult(
        camera_id=result.camera_id,
        frame_id=result.frame_sequence,
        captured_at=captured_at,
        processed_at=time.time(),
        processing_ms=float(stage_metrics.get("total_vision_ms") or 0.0),
        detections=detections,
        events=events,
        metadata={
            "camera_location": camera_location,
            "source_epoch": result.source_epoch,
            "source_frame_index": result.source_frame_index,
            "observation_time": result.source_time_s,
            "bbox_coordinate_space": "source_pixels",
            "geometry": {"scale": 1.0, "pad_x": 0.0, "pad_y": 0.0},
            "current_action": result.current_action,
            "fall_state": result.fall_state,
            "fall_confidence": result.fall_confidence,
            "fall_diagnostics": list(result.fall_diagnostics),
            "stage_metrics": stage_metrics,
        },
    )


@dataclass(slots=True)
class _EventMediaItem:
    packet: FramePacket
    result: VisionResult
    candidate_key: tuple[str, int, int] | None = None


class SdaEventMediaWorker:
    """Bounded handoff for policy, privacy JPEG, and event persistence."""

    def __init__(self, dispatcher=None, capacity: int = 32, *, allow_unblurred_event_snapshot: bool = False):
        self._dispatcher = dispatcher
        self._policy = VisionProductPolicy()
        self._allow_unblurred_event_snapshot = allow_unblurred_event_snapshot
        try:
            self._privacy_face_detector = MediaPipePrivacyFaceDetector()
        except Exception:
            logger.exception("Could not initialize snapshot-only CPU privacy face detector")
            self._privacy_face_detector = None
        self._capacity = capacity
        self._work_available = threading.Condition()
        self._semantic_queue: deque[_EventMediaItem] = deque()
        self._unknown_pending: OrderedDict[tuple[str, int, int], _EventMediaItem] = OrderedDict()
        self._unknown_inflight: set[tuple[str, int, int]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._profile_lock = threading.Lock()
        self._profile_samples: deque[tuple[float, float]] = deque(maxlen=512)
        self._snapshot_samples: deque[tuple[float, float]] = deque(maxlen=512)
        self._submitted = 0
        self._product_policy_candidates = 0
        self._product_policy_events_created = 0
        self._no_event_after_policy = 0
        self._max_queue_depth = 0
        self._submitted_semantic_events = 0
        self._submitted_policy_candidates = 0
        self._coalesced_policy_candidates = 0
        self._processed_policy_candidates = 0
        self._queue_full_drops = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sda-event-media", daemon=True)
        self._thread.start()

    def submit(self, packet: FramePacket, result: VisionResult) -> bool:
        if not needs_product_policy(result):
            return True
        candidates = unknown_product_policy_candidates(result)
        candidate_key = None
        if not result.events and len(candidates) == 1:
            candidate_key = (
                result.camera_id,
                int(result.metadata.get("source_epoch", 0)),
                candidates[0].track_id,
            )
        item = _EventMediaItem(
            FramePacket(
                packet.camera_id,
                packet.frame_id,
                packet.captured_at,
                packet.frame,
                packet.source_timestamp,
                packet.source_time_kind,
                packet.source_epoch,
                packet.source_frame_index,
                packet.discontinuity,
            ),
            result,
            candidate_key,
        )
        with self._work_available:
            if candidate_key is not None:
                with self._profile_lock:
                    self._submitted_policy_candidates += 1
                    self._product_policy_candidates += len(candidates)
                if candidate_key in self._unknown_inflight:
                    with self._profile_lock:
                        self._coalesced_policy_candidates += 1
                    return True
                if candidate_key in self._unknown_pending:
                    self._unknown_pending[candidate_key] = item
                    self._unknown_pending.move_to_end(candidate_key)
                    with self._profile_lock:
                        self._coalesced_policy_candidates += 1
                    return True
                if len(self._unknown_pending) >= self._capacity:
                    with self._profile_lock:
                        self._queue_full_drops += 1
                    return False
                self._unknown_pending[candidate_key] = item
            else:
                if len(self._semantic_queue) >= self._capacity:
                    with self._profile_lock:
                        self._queue_full_drops += 1
                    logger.error(
                        "SDA semantic event-media queue full; delivering event without snapshot camera=%s frame=%s",
                        result.camera_id,
                        result.frame_id,
                    )
                    if self._dispatcher is not None:
                        self._dispatcher.dispatch(result)
                    return False
                self._semantic_queue.append(item)
                with self._profile_lock:
                    self._submitted_semantic_events += len(result.events)
                    self._product_policy_candidates += len(candidates)
            depth = len(self._semantic_queue) + len(self._unknown_pending)
            with self._profile_lock:
                self._submitted += 1
                self._max_queue_depth = max(self._max_queue_depth, depth)
            self._work_available.notify()
            return True

    def clear_camera(self, camera_id: str):
        self._policy.clear_camera(camera_id)
        with self._work_available:
            for key in [key for key in self._unknown_pending if key[0] == camera_id]:
                self._unknown_pending.pop(key, None)

    def stop(self):
        self._stop.set()
        with self._work_available:
            self._work_available.notify_all()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
        detector = self._privacy_face_detector
        if detector is not None:
            try:
                detector.close()
            except Exception:
                logger.exception("Could not close snapshot-only CPU privacy face detector")
            self._privacy_face_detector = None

    def _run(self):
        while True:
            with self._work_available:
                self._work_available.wait_for(
                    lambda: self._stop.is_set() or self._semantic_queue or self._unknown_pending,
                    timeout=0.2,
                )
                if self._semantic_queue:
                    item = self._semantic_queue.popleft()
                elif self._unknown_pending:
                    key, item = self._unknown_pending.popitem(last=False)
                    self._unknown_inflight.add(key)
                elif self._stop.is_set():
                    break
                else:
                    continue
            try:
                started = time.perf_counter()
                if item.candidate_key is not None:
                    with self._profile_lock:
                        self._processed_policy_candidates += 1
                event_count_before_policy = len(item.result.events)
                result = self._policy.apply(item.result)
                events_created = max(0, len(result.events) - event_count_before_policy)
                if not result.events:
                    with self._profile_lock:
                        self._product_policy_events_created += events_created
                        self._no_event_after_policy += 1
                        self._profile_samples.append((time.monotonic(), (time.perf_counter() - started) * 1000.0))
                    continue
                snapshot_started = time.perf_counter()
                attach_event_snapshots(
                    item.packet,
                    result,
                    self._privacy_face_detector,
                    allow_unblurred_event_snapshot=self._allow_unblurred_event_snapshot,
                )
                snapshot_elapsed_ms = (time.perf_counter() - snapshot_started) * 1000.0
                if self._dispatcher is not None:
                    self._dispatcher.dispatch(result)
                with self._profile_lock:
                    self._product_policy_events_created += events_created
                    self._snapshot_samples.append((time.monotonic(), snapshot_elapsed_ms))
                    self._profile_samples.append((time.monotonic(), (time.perf_counter() - started) * 1000.0))
            except Exception:
                logger.exception(
                    "SDA downstream event processing failed camera=%s frame=%s",
                    item.result.camera_id,
                    item.result.frame_id,
                )
                if self._dispatcher is not None:
                    self._dispatcher.dispatch(item.result)
            finally:
                if item.candidate_key is not None:
                    with self._work_available:
                        self._unknown_inflight.discard(item.candidate_key)

    def profile(self) -> dict:
        with self._profile_lock:
            return {
                "submitted": self._submitted,
                "event_media_submitted": self._submitted,
                "product_policy_candidates": self._product_policy_candidates,
                "product_policy_events_created": self._product_policy_events_created,
                "event_media_no_event_after_policy": self._no_event_after_policy,
                "submitted_semantic_events": self._submitted_semantic_events,
                "submitted_policy_candidates": self._submitted_policy_candidates,
                "coalesced_policy_candidates": self._coalesced_policy_candidates,
                "processed_policy_candidates": self._processed_policy_candidates,
                "queue_full_drops": self._queue_full_drops,
                "max_queue_depth": self._max_queue_depth,
                "samples": list(self._profile_samples),
                "snapshot_samples": list(self._snapshot_samples),
                "current_queue_depth": len(self._semantic_queue) + len(self._unknown_pending),
            }


@dataclass
class _SessionRecord:
    camera_id: str
    source: str
    location: str
    session: VisionSession
    thread: threading.Thread
    status: str = "connecting"
    error: str | None = None
    frame_id: int = -1
    last_frame_at: float | None = None
    source_frames_read: int = 0
    frames_published: int = 0
    processed_frames: int = 0
    latest_result: VisionResult | None = None
    capture_times: deque = field(default_factory=lambda: deque(maxlen=60))
    stop_requested: bool = False


class SdaSessionRegistry:
    def __init__(self, frame_hub: FrameHub, *, settings, event_dispatcher=None):
        self.frame_hub = frame_hub
        self.settings = settings
        self._events = SdaEventMediaWorker(
            event_dispatcher,
            allow_unblurred_event_snapshot=getattr(settings, "vision_allow_unblurred_event_snapshot", False),
        )
        self._lock = threading.RLock()
        self._records: dict[str, _SessionRecord] = {}
        self._vision_desired: dict[str, bool] = {}
        self._identity_desired: dict[str, bool] = {}
        self._next_epoch: dict[str, int] = {}
        self._identity_gallery = IdentityGallerySnapshot(0)
        self._gallery_update_ms = 0.0

    def start(self):
        self._events.start()

    def start_session(self, camera_id: str, source, *, loop_video=False, location=None):
        with self._lock:
            existing = self._records.get(camera_id)
            if existing and existing.thread.is_alive():
                raise RuntimeError(f"Camera {camera_id} already running")
            inference = self._vision_desired.get(camera_id, True)
            identity = self._identity_desired.get(camera_id, self.settings.vision_identity_enabled)
            initial_epoch = self._next_epoch.get(camera_id, 0)
            self._next_epoch[camera_id] = initial_epoch + 1
            identity_gallery = self._identity_gallery
        config = VisionSessionConfig(
            source=str(source),
            camera_id=camera_id,
            camera_location=location or camera_id,
            source_epoch=initial_epoch,
            loop_video=bool(loop_video),
            inference_enabled=inference,
            identity_enabled=identity,
            device=self.settings.vision_device,
            vision_fps=self.settings.vision_fps,
            identity_process_priority=getattr(self.settings, "vision_identity_process_priority", "normal"),
            identity_cpu_affinity=getattr(self.settings, "vision_identity_cpu_affinity", None),
            preview="none",
            log_level=self.settings.log_level.lower(),
            identity_gallery_mode="supplied",
            identity_gallery_snapshot=identity_gallery,
        )
        callbacks = VisionCallbacks(
            on_source_frame=lambda frame: self._on_source(camera_id, frame),
            on_result_frame=lambda frame, result: self._on_result(camera_id, frame, result),
        )
        session = VisionSession(config, callbacks)
        thread = threading.Thread(
            target=self._run_session, args=(camera_id,), name=f"sda-session-{camera_id}", daemon=True
        )
        record = _SessionRecord(camera_id, str(source), location or camera_id, session, thread)
        with self._lock:
            self._records[camera_id] = record
        thread.start()
        return self.camera_status(camera_id)

    def _run_session(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
        if record is None:
            return
        try:
            record.session.run()
            with self._lock:
                if self._records.get(camera_id) is record:
                    record.status = "offline" if record.stop_requested else "ended"
        except Exception as exc:
            logger.exception("SDA session failed camera=%s", camera_id)
            with self._lock:
                if self._records.get(camera_id) is record:
                    record.status = "error"
                    record.error = str(exc)

    def _on_source(self, camera_id, source_frame):
        packet = map_source_frame(source_frame)
        self.frame_hub.publish(packet)
        now = packet.captured_at
        with self._lock:
            record = self._records.get(camera_id)
            if record is None:
                return
            record.status = "online"
            record.error = None
            record.frame_id = packet.frame_id
            record.last_frame_at = now
            record.source_frames_read += 1
            record.frames_published += 1
            record.capture_times.append(now)

    def _on_result(self, camera_id, exact_frame, sda_result):
        with self._lock:
            record = self._records.get(camera_id)
            if record is None:
                return
            identity_enabled = self._identity_desired.get(camera_id, record.session.identity_enabled)
            mapped = map_vision_result(sda_result, camera_location=record.location, identity_enabled=identity_enabled)
            if record.latest_result is None or (mapped.metadata["source_epoch"], mapped.frame_id) >= (
                record.latest_result.metadata.get("source_epoch", 0),
                record.latest_result.frame_id,
            ):
                record.latest_result = mapped
            record.processed_frames += 1
        if needs_product_policy(mapped):
            packet = FramePacket(
                camera_id,
                mapped.frame_id,
                mapped.captured_at,
                exact_frame,
                mapped.metadata["observation_time"],
                "media_timeline",
                mapped.metadata["source_epoch"],
                mapped.metadata["source_frame_index"],
            )
            self._events.submit(packet, mapped)

    def stop_session(self, camera_id: str, remove_frame=True):
        with self._lock:
            record = self._records.get(camera_id)
        if record is None:
            return self.camera_status(camera_id)
        record.stop_requested = True
        record.session.request_stop()
        if record.thread.is_alive():
            record.thread.join(timeout=7.0)
        with self._lock:
            if record.thread.is_alive():
                record.status = "error"
                record.error = "SDA session did not stop within 7 seconds"
                logger.error("SDA session did not stop cleanly camera=%s", camera_id)
            else:
                record.status = "offline"
            record.latest_result = None
        self._events.clear_camera(camera_id)
        if remove_frame:
            self.frame_hub.remove(camera_id)
        return self.camera_status(camera_id)

    def stop_all(self):
        with self._lock:
            ids = list(self._records)
        for camera_id in ids:
            self.stop_session(camera_id)
        self._events.stop()

    def set_unavailable(self, camera_id, error):
        with self._lock:
            record = self._records.get(camera_id)
            if record is not None:
                record.status, record.error = "error", error
        return {
            "camera_id": camera_id,
            "status": "error",
            "error": error,
            "frame_id": -1,
            "last_frame_at": None,
            "capture_fps": 0.0,
            "source_frames_read": 0,
            "frames_published": 0,
        }

    def camera_status(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
            if record is None:
                return None
            source = getattr(record.session, "frame_source", None)
            source_error = getattr(source, "error", None)
            source_ended = bool(getattr(source, "ended", False))
            status = record.status
            error = record.error
            if source_error:
                status, error = "error", source_error
            elif source_ended and not record.stop_requested and not record.thread.is_alive():
                status = "ended"
            times = list(record.capture_times)
            span = times[-1] - times[0] if len(times) > 1 else 0.0
            fps = (len(times) - 1) / span if span > 0 else 0.0
            return {
                "camera_id": camera_id,
                "status": status,
                "frame_id": record.frame_id,
                "last_frame_at": record.last_frame_at,
                "error": error,
                "capture_fps": fps,
                "source_frames_read": record.source_frames_read,
                "frames_published": record.frames_published,
            }

    def vision_status(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
            enabled = self._vision_desired.get(camera_id, True)
            identity = self._identity_desired.get(camera_id, self.settings.vision_identity_enabled)
            latest = None if record is None else record.latest_result
            metrics = {} if latest is None else latest.metadata.get("stage_metrics", {})
            processed = 0 if record is None else record.processed_frames
            source = None if record is None else getattr(record.session, "frame_source", None)
            error = None if record is None else (record.error or getattr(source, "error", None))
            status = (
                "disabled"
                if not enabled
                else (
                    "waiting_for_source"
                    if record is None or record.status in {"offline", "ended"}
                    else ("error" if error else "running")
                )
            )
            return {
                "camera_id": camera_id,
                "enabled": enabled,
                "status": status,
                "processed_frames": processed,
                "last_processed_frame_id": None if latest is None else latest.frame_id,
                "current_error": error,
                "identity_enabled": identity,
                "realtime": {
                    "vision_frames_processed": processed,
                    "vision_frames_offered": 0 if record is None else record.source_frames_read,
                    "vision_frames_overwritten": 0,
                    "vision_fps": metrics.get("effective_fps"),
                    "vision_processing_latency_ms": metrics.get("total_vision_ms"),
                    "vision_drop_ratio": None,
                    "pending": 0,
                    "max_pending": 1,
                    **metrics,
                },
                "hardware": (
                    {}
                    if record is None or not hasattr(record.session, "hardware_diagnostics")
                    else record.session.hardware_diagnostics()
                ),
            }

    def is_running(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
            return bool(record and record.thread.is_alive() and record.status not in {"ended", "error", "offline"})

    def set_vision_enabled(self, camera_id, enabled):
        with self._lock:
            self._vision_desired[camera_id] = bool(enabled)
            record = self._records.get(camera_id)
            if not enabled and record:
                record.latest_result = None
        if record:
            record.session.set_inference_enabled(bool(enabled))
        self._events.clear_camera(camera_id)
        return self.vision_status(camera_id)

    def set_identity_enabled(self, camera_id, enabled):
        with self._lock:
            self._identity_desired[camera_id] = bool(enabled)
            record = self._records.get(camera_id)
            if not enabled and record:
                record.latest_result = None
        if record:
            record.session.set_identity_enabled(bool(enabled))
        self._events.clear_camera(camera_id)
        return self.vision_status(camera_id)

    def identity_enabled(self, camera_id):
        with self._lock:
            return self._identity_desired.get(camera_id, self.settings.vision_identity_enabled)

    def update_identity_gallery(self, snapshot: IdentityGallerySnapshot):
        started = time.perf_counter()
        with self._lock:
            self._identity_gallery = snapshot
            sessions = [record.session for record in self._records.values()]
        for session in sessions:
            session.update_identity_gallery(snapshot)
        self._gallery_update_ms = (time.perf_counter() - started) * 1000.0
        return {
            "version": snapshot.version,
            "entries": len(snapshot.entries),
            "sessions": len(sessions),
            "update_ms": self._gallery_update_ms,
        }

    def latest_result(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
            return None if record is None else record.latest_result


class SdaCameraFacade:
    def __init__(self, registry):
        self.registry = registry

    def start(self, camera_id, source, loop_video=True, location=None):
        return self.registry.start_session(camera_id, source, loop_video=loop_video, location=location)

    def stop(self, camera_id, remove_frame=True):
        return self.registry.stop_session(camera_id, remove_frame)

    def stop_all(self):
        return self.registry.stop_all()

    def get_status(self, camera_id):
        return self.registry.camera_status(camera_id)

    def is_running(self, camera_id):
        return self.registry.is_running(camera_id)

    def set_unavailable(self, camera_id, error):
        return self.registry.set_unavailable(camera_id, error)


class SdaVisionFacade:
    def __init__(self, registry):
        self.registry = registry

    def start(self):
        return self.registry.start()

    def stop(self):
        return None

    def enable(self, camera_id):
        return self.registry.set_vision_enabled(camera_id, True)

    def disable(self, camera_id):
        return self.registry.set_vision_enabled(camera_id, False)

    def get_status(self, camera_id):
        return self.registry.vision_status(camera_id)

    def set_identity_enabled(self, camera_id, enabled):
        return self.registry.set_identity_enabled(camera_id, enabled)

    def is_identity_enabled(self, camera_id):
        return self.registry.identity_enabled(camera_id)

    def latest_result(self, camera_id):
        return self.registry.latest_result(camera_id)
