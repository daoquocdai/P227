import logging
import threading
import time
from dataclasses import asdict

from src.models.vision import VisionResult
from src.services.frame_hub import FrameHub
from src.vision.engine import VisionEngine
from src.vision.worker import VisionWorker

logger = logging.getLogger(__name__)


class VisionManager:
    """In-memory lifecycle and status facade for the local Vision worker."""

    def __init__(
        self,
        frame_hub: FrameHub,
        engine: VisionEngine,
        event_dispatcher=None,
        sample_buffer=None,
    ) -> None:
        self._lock = threading.RLock()
        self._frame_hub = frame_hub
        self._last_results: dict[str, VisionResult] = {}
        self._current_errors: dict[str, str] = {}
        self._last_errors: dict[str, dict] = {}
        self._event_dispatcher = event_dispatcher
        self._sample_buffer = sample_buffer
        self._event_handler_errors: dict[str, int] = {}
        self._last_event_handler_errors: dict[str, str] = {}
        self.worker = VisionWorker(
            frame_hub=frame_hub,
            engine=engine,
            on_result=self._handle_result,
            on_error=self._handle_error,
            sample_buffer=sample_buffer,
        )

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    def enable(self, camera_id: str) -> dict:
        with self._lock:
            self._current_errors.pop(camera_id, None)
            self._last_results.pop(camera_id, None)
        self.worker.enable(camera_id)
        return self.get_status(camera_id)

    def disable(self, camera_id: str) -> dict:
        # Clearing the session intentionally resets all temporal state before
        # the camera can be enabled again.
        self.worker.disable(camera_id, clear_session=True)
        with self._lock:
            self._current_errors.pop(camera_id, None)
            self._last_results.pop(camera_id, None)
        return self.get_status(camera_id)

    def get_status(self, camera_id: str) -> dict:
        enabled = self.worker.is_enabled(camera_id)
        session = self.worker.get_session(camera_id)
        with self._lock:
            current_error = self._current_errors.get(camera_id)
            last_error = self._last_errors.get(camera_id)
            result = self._last_results.get(camera_id)

        if not enabled:
            status = "disabled"
        elif current_error:
            status = "error"
        elif not self._frame_hub.has_camera(camera_id) or result is None:
            status = "waiting_for_source"
        else:
            status = "running"

        dispatch_status = (
            {
                "emitted_events": 0,
                "dropped_events": 0,
                "dispatch_errors": 0,
                "last_event_error": None,
            }
            if self._event_dispatcher is None
            else self._event_dispatcher.get_status(camera_id)
        )
        with self._lock:
            handler_errors = self._event_handler_errors.get(camera_id, 0)
            handler_last_error = self._last_event_handler_errors.get(camera_id)
        dispatch_status["dispatch_errors"] += handler_errors
        if handler_last_error is not None:
            dispatch_status["last_event_error"] = handler_last_error

        return {
            "camera_id": camera_id,
            "enabled": enabled,
            "status": status,
            "processed_frames": 0 if session is None else session.processed_frames,
            "dropped_frames": 0 if session is None else session.dropped_frames,
            "last_processed_frame_id": -1 if session is None else session.last_processed_frame_id,
            "worker_threads": self.worker.thread_count,
            "last_result": None if result is None else asdict(result),
            "current_error": current_error,
            "last_error": last_error,
            "event_dispatch": dispatch_status,
            "temporal": self._temporal_status(camera_id),
        }

    def _temporal_status(self, camera_id: str) -> dict:
        if self._sample_buffer is not None:
            return self._sample_buffer.get_status(camera_id)
        return {
            "target_sample_rate": None,
            "target_input_rate": None,
            "effective_sample_rate": 0.0,
            "service_rate": 0.0,
            "buffer_depth": 0,
            "buffer_capacity": 0,
            "temporal_drop_count": 0,
            "input_drop_count": 0,
            "overload_count": 0,
            "epoch_temporal_drop_count": 0,
            "epoch_input_drop_count": 0,
            "epoch_overload_count": 0,
            "window_source_time_span": None,
            "temporal_fidelity": "unavailable",
            "degraded_reason": "temporal_sampling_not_configured",
            "last_discontinuity": None,
            "source_epoch": None,
            "source_time_kind": None,
        }

    def _handle_result(self, result: VisionResult) -> None:
        if not self.worker.is_enabled(result.camera_id):
            return
        with self._lock:
            self._last_results[result.camera_id] = result
            self._current_errors.pop(result.camera_id, None)
        session = self.worker.get_session(result.camera_id)
        logger.debug(
            "Vision processed camera=%s frame=%s processing_ms=%.2f dropped_frames=%s",
            result.camera_id,
            result.frame_id,
            result.processing_ms,
            0 if session is None else session.dropped_frames,
        )
        if self._event_dispatcher is not None:
            try:
                self._event_dispatcher.dispatch(result)
            except Exception as exc:
                with self._lock:
                    self._event_handler_errors[result.camera_id] = (
                        self._event_handler_errors.get(result.camera_id, 0) + 1
                    )
                    self._last_event_handler_errors[result.camera_id] = str(exc)
                logger.exception("Unexpected Vision event handler failure camera=%s", result.camera_id)

    def _handle_error(self, camera_id: str, frame_id: int, exc: Exception) -> None:
        if not self.worker.is_enabled(camera_id):
            return
        error = str(exc)
        with self._lock:
            self._current_errors[camera_id] = error
            self._last_errors[camera_id] = {
                "message": error,
                "frame_id": frame_id,
                "occurred_at": time.time(),
            }
