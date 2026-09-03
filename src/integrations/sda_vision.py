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


def map_vision_result(
    result,
    *,
    camera_location: str,
    source_width: int | None = None,
    source_height: int | None = None,
) -> VisionResult:
    detections = []
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

    events = []
    for item in result.generated_events:
        normalized = item.event_type.strip().lower()
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
        if item.identity_state is not None or item.identity_name is not None:
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
            "bbox_source_width": source_width,
            "bbox_source_height": source_height,
            "geometry": {"scale": 1.0, "pad_x": 0.0, "pad_y": 0.0},
            "current_action": result.current_action,
            "action_class_id": result.action_class_id,
            "action_class_name": result.action_class_name,
            "action_label": result.action_label,
            "action_confidence": result.action_confidence,
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
    source_bootstrap_thread: threading.Thread | None = None
    vision_thread: threading.Thread | None = None
    camera_status: str = "connecting"
    camera_error: str | None = None
    vision_error: str | None = None
    frame_id: int = -1
    last_frame_at: float | None = None
    source_frames_read: int = 0
    frames_published: int = 0
    processed_frames: int = 0
    vision_frames_dropped: int = 0
    latest_result: VisionResult | None = None
    capture_times: deque = field(default_factory=lambda: deque(maxlen=60))
    stop_requested: bool = False
    browser_owned: bool = False
    browser_publisher_id: str | None = None


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
        self._next_epoch: dict[str, int] = {}
        self._identity_gallery = IdentityGallerySnapshot(0)
        self._gallery_update_ms = 0.0

    def start(self):
        self._events.start()

    def start_session(self, camera_id: str, source, *, loop_video=False, location=None):
        with self._lock:
            existing = self._records.get(camera_id)
            if existing and self._camera_record_is_running(existing):
                raise RuntimeError(f"Camera {camera_id} already running")
            inference = self._vision_desired.get(camera_id, True)
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
            identity_enabled=True,
            device=self.settings.vision_device,
            vision_fps=self.settings.vision_fps,
            num_poses=getattr(self.settings, "vision_num_poses", 1),
            input_width=getattr(self.settings, "vision_input_width", 1280),
            input_height=getattr(self.settings, "vision_input_height", 720),
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
        record = _SessionRecord(camera_id, str(source), location or camera_id, session)
        thread = threading.Thread(
            target=self._bootstrap_source, args=(camera_id, record), name=f"sda-source-start-{camera_id}", daemon=True
        )
        record.source_bootstrap_thread = thread
        with self._lock:
            self._records[camera_id] = record
        thread.start()
        return self.camera_status(camera_id)

    def start_browser_session(self, camera_id: str, *, location=None):
        with self._lock:
            existing = self._records.get(camera_id)
            if existing and self._camera_record_is_running(existing):
                raise RuntimeError(f"Camera {camera_id} already running")
            inference = self._vision_desired.get(camera_id, True)
            initial_epoch = self._next_epoch.get(camera_id, 0)
            identity_gallery = self._identity_gallery
        config = VisionSessionConfig(
            source="browser-webcam",
            source_mode="external",
            camera_id=camera_id,
            camera_location=location or camera_id,
            source_epoch=initial_epoch,
            inference_enabled=inference,
            identity_enabled=True,
            device=self.settings.vision_device,
            vision_fps=self.settings.vision_fps,
            num_poses=getattr(self.settings, "vision_num_poses", 1),
            input_width=getattr(self.settings, "vision_input_width", 1280),
            input_height=getattr(self.settings, "vision_input_height", 720),
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
        record = _SessionRecord(
            camera_id,
            "browser-webcam",
            location or camera_id,
            VisionSession(config, callbacks),
            browser_owned=True,
        )
        with self._lock:
            self._records[camera_id] = record
        return self.camera_status(camera_id)

    def browser_connect(self, camera_id: str) -> str:
        with self._lock:
            record = self._records.get(camera_id)
            if record is None or not record.browser_owned or record.stop_requested:
                raise RuntimeError("Browser webcam camera is not waiting for a publisher")
            if record.browser_publisher_id is not None:
                raise RuntimeError("Browser webcam already has an active publisher")
            epoch = self._next_epoch.get(camera_id, 0)
            self._next_epoch[camera_id] = epoch + 1
            publisher_id = str(uuid4())
            record.browser_publisher_id = publisher_id
            record.camera_status = "connecting"
            record.camera_error = None
            record.vision_error = None
            record.latest_result = None
        record.session.start_external_source(epoch)
        return publisher_id

    def submit_browser_frame(self, camera_id: str, publisher_id: str, frame) -> bool:
        with self._lock:
            record = self._records.get(camera_id)
            if record is None or record.browser_publisher_id != publisher_id or record.stop_requested:
                return False
            first_frame = record.source_frames_read == 0 or record.camera_status != "online"
        record.session.submit_external_frame(frame)
        if first_frame and self._vision_desired.get(camera_id, True):
            self._start_vision_thread(camera_id, record)
        return True

    def browser_disconnect(self, camera_id: str, publisher_id: str) -> bool:
        with self._lock:
            record = self._records.get(camera_id)
            if record is None or record.browser_publisher_id != publisher_id:
                return False
            record.browser_publisher_id = None
        record.session.request_vision_stop()
        record.session.stop_source()
        vision_thread = record.vision_thread
        if vision_thread and vision_thread.is_alive():
            vision_thread.join(timeout=2.0)
        if not (vision_thread and vision_thread.is_alive()):
            record.session.shutdown_vision()
        source_state = record.session.source_status()
        with self._lock:
            if self._records.get(camera_id) is not record or record.stop_requested:
                return True
            self._next_epoch[camera_id] = max(
                self._next_epoch.get(camera_id, 0), int(source_state.get("source_epoch", 0)) + 1
            )
            record.camera_status = "connecting"
            record.camera_error = None
            record.latest_result = None
            record.capture_times.clear()
        self._events.clear_camera(camera_id)
        self.frame_hub.remove(camera_id)
        return True

    def _bootstrap_source(self, camera_id, record):
        try:
            record.session.start_source()
        except Exception as exc:
            logger.exception("SDA source failed camera=%s", camera_id)
            with self._lock:
                if self._records.get(camera_id) is record and not record.stop_requested:
                    record.camera_status = "error"
                    record.camera_error = str(exc)
            return
        with self._lock:
            if self._records.get(camera_id) is not record:
                return
            should_stop = record.stop_requested
            should_start_vision = self._vision_desired.get(camera_id, True)
        if should_stop:
            record.session.stop_source()
        elif should_start_vision:
            self._start_vision_thread(camera_id, record)

    def _start_vision_thread(self, camera_id, record=None):
        with self._lock:
            record = record or self._records.get(camera_id)
            if record is None or record.stop_requested:
                return False
            if record.vision_thread and record.vision_thread.is_alive():
                return True
            if not record.session.source_status()["running"]:
                return False
            record.vision_error = None
            record.processed_frames = 0
            record.vision_frames_dropped = 0
            thread = threading.Thread(
                target=self._run_vision, args=(camera_id, record), name=f"sda-vision-{camera_id}", daemon=True
            )
            record.vision_thread = thread
        thread.start()
        return True

    def _run_vision(self, camera_id, record):
        try:
            record.session.run_vision()
        except Exception as exc:
            logger.exception("SDA Vision failed camera=%s", camera_id)
            with self._lock:
                if self._records.get(camera_id) is record:
                    record.vision_error = str(exc)
        finally:
            record.session.shutdown_vision()
            with self._lock:
                if self._records.get(camera_id) is not record:
                    return
                if record.vision_thread is threading.current_thread():
                    record.vision_thread = None
                restart = (
                    not record.stop_requested
                    and self._vision_desired.get(camera_id, True)
                    and record.vision_error is None
                    and record.session.source_status()["running"]
                )
            if restart:
                self._start_vision_thread(camera_id, record)

    def _on_source(self, camera_id, source_frame):
        packet = map_source_frame(source_frame)
        self.frame_hub.publish(packet)
        now = packet.captured_at
        with self._lock:
            record = self._records.get(camera_id)
            if record is None:
                return
            record.camera_status = "online"
            record.camera_error = None
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
            height, width = exact_frame.shape[:2]
            mapped = map_vision_result(
                sda_result,
                camera_location=record.location,
                source_width=width,
                source_height=height,
            )
            if record.latest_result is None or (mapped.metadata["source_epoch"], mapped.frame_id) >= (
                record.latest_result.metadata.get("source_epoch", 0),
                record.latest_result.frame_id,
            ):
                record.latest_result = mapped
            record.processed_frames += 1
            record.vision_frames_dropped = int(
                mapped.metadata.get("stage_metrics", {}).get("capture_frames_dropped", 0)
            )
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
        with self._lock:
            record.stop_requested = True
            record.browser_publisher_id = None
        record.session.request_vision_stop()
        record.session.stop_source()
        vision_thread = record.vision_thread
        bootstrap_thread = record.source_bootstrap_thread
        if vision_thread and vision_thread.is_alive():
            vision_thread.join(timeout=7.0)
        if bootstrap_thread and bootstrap_thread.is_alive():
            bootstrap_thread.join(timeout=7.0)
        record.session.stop_source()
        if not (vision_thread and vision_thread.is_alive()):
            record.session.shutdown_vision()
        source_state = record.session.source_status()
        with self._lock:
            if vision_thread and vision_thread.is_alive():
                record.vision_error = "SDA Vision did not stop within 7 seconds"
                logger.error("SDA Vision did not stop cleanly camera=%s", camera_id)
            record.camera_status = "offline"
            record.camera_error = None
            record.latest_result = None
            self._next_epoch[camera_id] = max(
                self._next_epoch.get(camera_id, 0), int(source_state.get("source_epoch", 0)) + 1
            )
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
                record.camera_status, record.camera_error = "error", error
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
            source = record.session.source_status()
            status = record.camera_status
            error = record.camera_error
            if source["error"]:
                status, error = "error", source["error"]
            elif source["ended"] and not record.stop_requested and not record.browser_owned:
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
            latest = None if record is None else record.latest_result
            metrics = {} if latest is None else latest.metadata.get("stage_metrics", {})
            processed = 0 if record is None else record.processed_frames
            source = None if record is None else record.session.source_status()
            error = None if record is None else record.vision_error
            vision_running = bool(record and record.vision_thread and record.vision_thread.is_alive())
            dropped = 0 if record is None else record.vision_frames_dropped
            offered = processed + dropped
            status = (
                "disabled"
                if not enabled or (record is not None and record.stop_requested)
                else (
                    "waiting_for_source"
                    if record is None or not source["running"]
                    else ("error" if error else ("running" if vision_running else "waiting_for_source"))
                )
            )
            return {
                "camera_id": camera_id,
                "enabled": enabled,
                "status": status,
                "processed_frames": processed,
                "last_processed_frame_id": None if latest is None else latest.frame_id,
                "current_error": error,
                "identity_status": self._identity_status(enabled, record),
                "identity_error": (
                    None if record is None else getattr(record.session, "face_startup_error", None)
                ),
                "realtime": {
                    "vision_frames_processed": processed,
                    "vision_frames_offered": offered,
                    "vision_frames_overwritten": dropped,
                    "vision_fps": metrics.get("effective_fps"),
                    "vision_processing_latency_ms": metrics.get("total_vision_ms"),
                    "vision_drop_ratio": dropped / offered if offered else None,
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

    @staticmethod
    def _camera_record_is_running(record):
        source = record.session.source_status()
        bootstrap = record.source_bootstrap_thread
        return bool(
            (record.browser_owned and not record.stop_requested)
            or source["running"]
            or (bootstrap and bootstrap.is_alive() and not record.stop_requested)
        )

    def camera_is_running(self, camera_id):
        with self._lock:
            record = self._records.get(camera_id)
            return bool(record and self._camera_record_is_running(record))

    def set_vision_enabled(self, camera_id, enabled):
        with self._lock:
            self._vision_desired[camera_id] = bool(enabled)
            record = self._records.get(camera_id)
            if not enabled and record:
                record.latest_result = None
            elif enabled and record:
                record.vision_error = None
        if record:
            if enabled:
                record.session.set_inference_enabled(True)
                self._start_vision_thread(camera_id, record)
            else:
                record.session.set_inference_enabled(False)
                record.session.request_vision_stop()
        self._events.clear_camera(camera_id)
        return self.vision_status(camera_id)

    @staticmethod
    def _identity_status(vision_enabled, record):
        if not vision_enabled or (record is not None and record.stop_requested):
            return "disabled"
        if record is None or not record.session.source_status()["running"]:
            return "waiting_for_source"
        if getattr(record.session, "face_startup_error", None):
            return "unavailable"
        if getattr(record.session, "identity_stage", None) is None:
            return "starting"
        return "running"

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

    def start_browser(self, camera_id, location=None):
        return self.registry.start_browser_session(camera_id, location=location)

    def connect_browser_publisher(self, camera_id):
        return self.registry.browser_connect(camera_id)

    def submit_browser_frame(self, camera_id, publisher_id, frame):
        return self.registry.submit_browser_frame(camera_id, publisher_id, frame)

    def disconnect_browser_publisher(self, camera_id, publisher_id):
        return self.registry.browser_disconnect(camera_id, publisher_id)

    def stop(self, camera_id, remove_frame=True):
        return self.registry.stop_session(camera_id, remove_frame)

    def stop_all(self):
        return self.registry.stop_all()

    def get_status(self, camera_id):
        return self.registry.camera_status(camera_id)

    def is_running(self, camera_id):
        return self.registry.camera_is_running(camera_id)

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

    def latest_result(self, camera_id):
        return self.registry.latest_result(camera_id)
