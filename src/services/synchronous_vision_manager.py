import logging
import threading
import time
from dataclasses import asdict, replace

from src.services.event_snapshot import attach_event_snapshots
from src.services.frame_hub import FrameHub
from src.services.vision_product_policy import VisionProductPolicy
from src.vision.session import VisionSession

logger = logging.getLogger(__name__)


class LatestFrameSlot:
    """A bounded, latest-wins handoff with exactly one pending packet."""

    def __init__(self):
        self._condition = threading.Condition()
        self._packet = None
        self._closed = False
        self.overwritten = 0
        self.max_pending = 0

    def offer(self, packet) -> bool:
        with self._condition:
            if self._closed:
                return False
            if self._packet is not None and self._packet.discontinuity:
                # A latest-wins overwrite must not erase the source boundary.
                # Carry it to the newest packet until the worker consumes it.
                packet = replace(packet, discontinuity=True)
            overwritten = self._packet is not None
            if overwritten:
                self.overwritten += 1
            self._packet = packet
            self.max_pending = 1
            self._condition.notify()
            return overwritten

    def take(self, timeout=0.5):
        with self._condition:
            if self._packet is None and not self._closed:
                self._condition.wait(timeout)
            packet = self._packet
            self._packet = None
            return packet

    def clear(self):
        with self._condition:
            self._packet = None

    def close(self):
        with self._condition:
            self._closed = True
            self._packet = None
            self._condition.notify_all()

    @property
    def pending(self):
        with self._condition:
            return int(self._packet is not None)


class SynchronousVisionManager:
    """Compatibility facade for asynchronous, per-camera latest-frame Vision."""

    def __init__(self, engine, event_dispatcher=None, product_policy=None, processed_frame_hub=None):
        self.engine = engine
        self.event_dispatcher = event_dispatcher
        self.product_policy = product_policy or VisionProductPolicy()
        self.processed_frame_hub = processed_frame_hub or FrameHub()
        self._lock = threading.RLock()
        self._identity_lock = threading.RLock()
        self._feature_locks: dict[str, threading.RLock] = {}
        self._enabled: set[str] = set()
        self._sessions: dict[str, VisionSession] = {}
        self._last_results = {}
        self._current_errors = {}
        self._slots: dict[str, LatestFrameSlot] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._metrics: dict[str, dict] = {}
        self._latest_epoch: dict[str, int] = {}
        self._started = False

    def start(self):
        self.engine.start()
        with self._lock:
            self._started = True
            for camera_id in self._enabled:
                self._start_thread(camera_id)

    def stop(self):
        with self._lock:
            self._started = False
            slots = list(self._slots.values())
            threads = list(self._threads.values())
        for slot in slots:
            slot.close()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=5)
        self.engine.stop()
        with self._lock:
            self._threads.clear()

    def enable(self, camera_id):
        with self._lock:
            self._enabled.add(camera_id)
            session = self._sessions.setdefault(camera_id, VisionSession(camera_id))
            self._current_errors.pop(camera_id, None)
        self.engine.prepare_camera(camera_id, session)
        with self._lock:
            if self._started:
                self._start_thread(camera_id)
        return self.get_status(camera_id)

    def disable(self, camera_id):
        with self._lock:
            self._enabled.discard(camera_id)
            slot = self._slots.pop(camera_id, None)
            thread = self._threads.pop(camera_id, None)
        if slot is not None:
            slot.close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._sessions.pop(camera_id, None)
            self._last_results.pop(camera_id, None)
            self._current_errors.pop(camera_id, None)
            self._latest_epoch.pop(camera_id, None)
        self.processed_frame_hub.remove(camera_id)
        self.engine.release_camera(camera_id)
        return self.get_status(camera_id)

    def process(self, packet):
        """Offer a captured packet without waiting for inference."""
        return self.offer(packet)

    def offer(self, packet):
        source_index = packet.source_frame_index
        if source_index is None:
            source_index = packet.frame_id
        # Canonical runtime samples zero-based even source frames. Filtering
        # here is equivalent and prevents known-ineligible frames occupying the slot.
        eligible = source_index % 2 == 0
        with self._lock:
            if packet.camera_id not in self._enabled or not self._started:
                return None
            metrics = self._metric(packet.camera_id)
            metrics["vision_frames_seen"] += 1
            if not eligible:
                return None
            metrics["vision_frames_eligible"] += 1
            metrics["vision_frames_offered"] += 1
            metrics["latest_offered_source_time"] = packet.source_timestamp or 0.0
            previous_epoch = self._latest_epoch.get(packet.camera_id)
            self._latest_epoch[packet.camera_id] = packet.source_epoch
            slot = self._slots[packet.camera_id]
            if previous_epoch is not None and previous_epoch != packet.source_epoch:
                slot.clear()
        if slot.offer(packet):
            with self._lock:
                self._metric(packet.camera_id)["vision_frames_overwritten"] += 1
        return None

    def latest_result(self, camera_id):
        with self._lock:
            return self._last_results.get(camera_id)

    def is_identity_enabled(self, camera_id):
        with self._lock:
            session = self._sessions.get(camera_id)
            return bool(session and session.state.get("vision_identity_enabled", False))

    def set_identity_enabled(self, camera_id, enabled):
        enabled = bool(enabled)
        with self._identity_lock:
            if enabled:
                self.engine.set_identity_enabled(True)
        feature_lock = self._feature_lock(camera_id)
        with feature_lock:
            with self._lock:
                session = self._sessions.setdefault(camera_id, VisionSession(camera_id))
                previous = bool(session.state.get("vision_identity_enabled", False))
                session.state["vision_identity_enabled"] = enabled
                session.state["vision_identity_generation"] = int(
                    session.state.get("vision_identity_generation", 0)
                ) + 1
                session.state.pop("vision_face_cache", None)
                latest = self._last_results.get(camera_id)
                if not enabled and latest is not None:
                    self._strip_identity(latest)
            if previous != enabled:
                self.product_policy.clear_camera(camera_id)
                logger.info(
                    "Unknown-person detection changed camera=%s enabled=%s; pending state cleared",
                    camera_id,
                    enabled,
                )

    def get_status(self, camera_id):
        with self._lock:
            enabled = camera_id in self._enabled
            session = self._sessions.get(camera_id)
            result = self._last_results.get(camera_id)
            error = self._current_errors.get(camera_id)
            thread = self._threads.get(camera_id)
            slot = self._slots.get(camera_id)
            metrics = dict(self._metric(camera_id))
        offered = metrics["vision_frames_offered"]
        overwritten = metrics["vision_frames_overwritten"]
        metrics.update(
            pending=0 if slot is None else slot.pending,
            max_pending=0 if slot is None else slot.max_pending,
            vision_drop_ratio=(overwritten / offered if offered else 0.0),
            vision_fps=self._vision_fps(metrics),
        )
        if result is not None:
            metrics["vision_result_staleness"] = max(
                0.0,
                metrics["latest_offered_source_time"]
                - (result.metadata.get("observation_time", result.captured_at) or 0.0),
            )
        return {
            "camera_id": camera_id,
            "enabled": enabled,
            "status": "disabled" if not enabled else "error" if error else "running" if result else "waiting_for_source",
            "processed_frames": 0 if session is None else session.processed_frames,
            "dropped_frames": 0 if session is None else session.dropped_frames,
            "last_processed_frame_id": -1 if session is None else session.last_processed_frame_id,
            "worker_threads": int(bool(thread and thread.is_alive())),
            "last_result": None if result is None else asdict(result),
            "current_error": error,
            "identity_enabled": bool(session and session.state.get("vision_identity_enabled", False)),
            "temporal": {"clock": "frame_packet.source_timestamp", "pre_vision_sampler": None, "pre_vision_queue": None},
            "realtime": metrics,
            "observed_at": time.time(),
        }

    def _metric(self, camera_id):
        return self._metrics.setdefault(camera_id, {
            "vision_frames_seen": 0,
            "vision_frames_eligible": 0,
            "vision_frames_offered": 0,
            "vision_frames_overwritten": 0,
            "vision_frames_processed": 0,
            "vision_processing_latency_ms": 0.0,
            "vision_result_staleness": 0.0,
            "latest_offered_source_time": 0.0,
            "first_processed_at": None,
            "last_processed_at": None,
        })

    @staticmethod
    def _vision_fps(metrics):
        first = metrics["first_processed_at"]
        last = metrics["last_processed_at"]
        count = metrics["vision_frames_processed"]
        return (count - 1) / (last - first) if count > 1 and last > first else 0.0

    def _start_thread(self, camera_id):
        current = self._threads.get(camera_id)
        if current is not None and current.is_alive():
            return
        slot = LatestFrameSlot()
        self._slots[camera_id] = slot
        thread = threading.Thread(target=self._run, args=(camera_id, slot), name=f"vision-{camera_id}", daemon=True)
        self._threads[camera_id] = thread
        thread.start()

    def _feature_lock(self, camera_id):
        with self._lock:
            return self._feature_locks.setdefault(camera_id, threading.RLock())

    @staticmethod
    def _strip_identity(result):
        result.events[:] = [event for event in result.events if event.type != "unknown_person"]
        for detection in result.detections:
            for key in [key for key in detection.metadata if key.startswith("identity_")]:
                detection.metadata.pop(key, None)

    def _run(self, camera_id, slot):
        while True:
            with self._lock:
                running = self._started and camera_id in self._enabled
            if not running:
                return
            packet = slot.take()
            if packet is None:
                continue
            with self._lock:
                session = self._sessions.get(camera_id)
            if session is None:
                continue
            session.note_frame(packet.frame_id)
            started = time.perf_counter()
            try:
                result = self.engine.process(packet, session)
                session.mark_processed(packet.frame_id)
                with self._lock:
                    current_epoch = self._latest_epoch.get(camera_id)
                if current_epoch != packet.source_epoch:
                    continue
                # This is the product commit boundary. Toggle OFF and unknown
                # event/snapshot/notification commit are serialized per camera,
                # while heavy inference remains lock-free.
                with self._feature_lock(camera_id):
                    if not bool(session.state.get("vision_identity_enabled", False)):
                        self._strip_identity(result)
                    self.product_policy.apply(result)
                    if not bool(session.state.get("vision_identity_enabled", False)):
                        self._strip_identity(result)
                    attach_event_snapshots(
                        packet,
                        result,
                        privacy_face_detector=getattr(
                            self.engine, "detect_faces_for_privacy", None
                        ),
                    )
                    packet.vision_result = result
                    self.processed_frame_hub.publish(packet)
                    if result.events and self.event_dispatcher is not None:
                        try:
                            self.event_dispatcher.dispatch(result)
                        except Exception:  # noqa: BLE001 - event transport must not kill Vision
                            logger.exception(
                                "Vision event dispatch failed camera=%s frame=%s",
                                camera_id,
                                packet.frame_id,
                            )
            except Exception as exc:  # noqa: BLE001 - isolate native/model frame failures from capture
                session.mark_processed(packet.frame_id)
                with self._lock:
                    self._current_errors[camera_id] = str(exc)
                logger.exception("Vision failed camera=%s frame=%s", camera_id, packet.frame_id)
                continue
            latency_ms = (time.perf_counter() - started) * 1000
            with self._lock:
                metrics = self._metric(camera_id)
                metrics["vision_frames_processed"] += 1
                metrics["vision_processing_latency_ms"] = latency_ms
                completed_at = time.monotonic()
                if metrics["first_processed_at"] is None:
                    metrics["first_processed_at"] = completed_at
                metrics["last_processed_at"] = completed_at
                metrics["vision_result_staleness"] = max(
                    0.0,
                    metrics["latest_offered_source_time"]
                    - (result.metadata.get("observation_time", packet.source_timestamp) or 0.0),
                )
                if result.metadata.get("sampled", True):
                    self._last_results[camera_id] = result
                self._current_errors.pop(camera_id, None)
