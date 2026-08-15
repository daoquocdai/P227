import hashlib
import logging
import threading
from collections.abc import Callable

from src.models.vision import VisionResult
from src.services.frame_hub import FrameHub
from src.services.media_paths import SNAPSHOT_ROOT, valid_snapshot_name
from src.vision.engine import VisionEngine
from src.vision.session import VisionSession

logger = logging.getLogger(__name__)


class VisionWorker:
    """Run one ordered consumer per camera without owning capture.

    Camera threads isolate ordering and mutable session/tracker state. Heavy
    immutable model state remains owned by the shared engine.
    """

    def __init__(
        self,
        frame_hub: FrameHub,
        engine: VisionEngine,
        on_result: Callable[[VisionResult], None] | None = None,
        on_error: Callable[[str, int, Exception], None] | None = None,
        sample_buffer=None,
    ) -> None:
        self.frame_hub = frame_hub
        self.engine = engine
        self.on_result = on_result
        self.on_error = on_error
        self.sample_buffer = sample_buffer
        self._lock = threading.RLock()
        self._enabled: set[str] = set()
        self._sessions: dict[str, VisionSession] = {}
        self._stop_event = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._engine_started = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._engine_started and not self._stop_event.is_set()

    @property
    def thread_count(self) -> int:
        with self._lock:
            return sum(thread.is_alive() for thread in self._threads.values())

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self.engine.start()
            self._engine_started = True
            for camera_id in self._enabled:
                self._start_camera_thread(camera_id)

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=5)
        with self._lock:
            if self._engine_started:
                self.engine.stop()
                self._engine_started = False
            self._threads.clear()

    def enable(self, camera_id: str) -> VisionSession:
        with self._lock:
            self._enabled.add(camera_id)
            session = self._sessions.setdefault(camera_id, VisionSession(camera_id=camera_id))
        if self.sample_buffer is not None:
            self.sample_buffer.enable(camera_id)
        try:
            self.engine.prepare_camera(camera_id, session)
        except Exception as exc:
            logger.exception("Vision camera preparation failed: camera=%s", camera_id)
            if self.on_error:
                self.on_error(camera_id, -1, exc)
        with self._lock:
            if self._engine_started:
                self._start_camera_thread(camera_id)
        return session

    def disable(self, camera_id: str, clear_session: bool = True) -> None:
        if self.sample_buffer is not None:
            self.sample_buffer.disable(camera_id)
        with self._lock:
            self._enabled.discard(camera_id)
            thread = self._threads.pop(camera_id, None)
            if clear_session:
                self._sessions.pop(camera_id, None)
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=5)
        if thread is not None and thread.is_alive():
            logger.error("Vision camera worker did not stop before resource release: camera=%s", camera_id)
            return
        self.engine.release_camera(camera_id)

    def is_enabled(self, camera_id: str) -> bool:
        with self._lock:
            return camera_id in self._enabled

    def get_session(self, camera_id: str) -> VisionSession | None:
        with self._lock:
            return self._sessions.get(camera_id)

    def _start_camera_thread(self, camera_id: str) -> None:
        existing = self._threads.get(camera_id)
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(
            target=self._run_camera,
            args=(camera_id,),
            name=f"vision-worker-{camera_id}",
            daemon=True,
        )
        self._threads[camera_id] = thread
        thread.start()

    def _run_camera(self, camera_id: str) -> None:
        while not self._stop_event.is_set() and self.is_enabled(camera_id):
            source = self.frame_hub if self.sample_buffer is None else self.sample_buffer
            current_version = source.version
            packet = (
                self.frame_hub.get_latest(camera_id)
                if self.sample_buffer is None
                else self.sample_buffer.get_nowait(camera_id)
            )
            session = self.get_session(camera_id)
            if packet is None or session is None or not self.is_enabled(camera_id):
                source.wait_for_update(after_version=current_version, timeout=0.5)
                continue
            if packet.frame_id <= session.last_processed_frame_id:
                source.wait_for_update(after_version=current_version, timeout=0.5)
                continue

            previous_epoch = session.state.get("vision_source_epoch")
            if packet.discontinuity or (
                previous_epoch is not None and previous_epoch != packet.source_epoch
            ):
                session.state.clear()
            session.state["vision_source_epoch"] = packet.source_epoch

            session.note_frame(packet.frame_id)
            try:
                result = self.engine.process(packet, session)
            except Exception as exc:
                session.mark_processed(packet.frame_id)
                logger.exception("Vision error: camera=%s frame=%s", camera_id, packet.frame_id)
                if self.on_error and self.is_enabled(camera_id):
                    self.on_error(camera_id, packet.frame_id, exc)
                continue

            session.mark_processed(packet.frame_id)
            if self.sample_buffer is not None:
                self.sample_buffer.note_result(packet, result.metadata)
            self._attach_event_snapshot(packet, result)
            if self.on_result and self.is_enabled(camera_id):
                self.on_result(result)

    @staticmethod
    def _attach_event_snapshot(packet, result: VisionResult) -> None:
        """Persist the exact processed frame before the event crosses into asyncio."""
        if not result.events or result.metadata.get("engine") != "canonical":
            return
        if all(valid_snapshot_name(event.metadata.get("snapshot_path")) for event in result.events):
            return
        try:
            import cv2

            ok, encoded = cv2.imencode(".jpg", packet.frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise RuntimeError("OpenCV could not encode the event snapshot")
            identity = f"{packet.camera_id}:{packet.frame_id}:{packet.captured_at}".encode()
            digest = hashlib.sha256(identity).hexdigest()[:16]
            safe_camera = "".join(
                char if char.isalnum() or char in "-_" else "-" for char in packet.camera_id
            )
            filename = f"vision-{safe_camera}-{packet.frame_id}-{digest}.jpg"
            SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
            destination = SNAPSHOT_ROOT / filename
            temporary = destination.with_suffix(".jpg.tmp")
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(destination)
            for event in result.events:
                event.metadata["snapshot_path"] = filename
        except Exception:  # noqa: BLE001 - snapshot failure must not stop Vision or event delivery
            logger.exception(
                "Could not persist Vision event snapshot camera=%s frame=%s",
                packet.camera_id,
                packet.frame_id,
            )
