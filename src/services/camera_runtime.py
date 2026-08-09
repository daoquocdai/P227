import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2

from src.models.frame import FramePacket
from src.services.frame_hub import FrameHub

logger = logging.getLogger(__name__)


@dataclass
class CameraRuntimeState:
    camera_id: str

    status: str = "offline"

    source: str | int | None = None

    frame_id: int = -1
    last_frame_at: float | None = None

    error: str | None = None

    def to_dict(self):
        state = asdict(self)
        # Source URIs may contain RTSP credentials and are never part of the
        # public runtime status contract.
        state.pop("source", None)
        return state


class CameraRuntime:

    def __init__(
        self,
        frame_hub: FrameHub,
        reconnect_delay: float = 1.0
    ):
        self.frame_hub = frame_hub

        self.reconnect_delay = reconnect_delay

        self._lock = threading.RLock()

        self._threads = {}
        self._stop_events = {}
        self._states = {}
        self._captures = {}

    def start(
        self,
        camera_id: str,
        source: str | int,
        loop_video: bool = True,
    ):

        with self._lock:

            existing = self._threads.get(camera_id)

            if existing and existing.is_alive():
                raise RuntimeError(
                    f"Camera {camera_id} already running"
                )

            source = self._normalize_source(source)

            stop_event = threading.Event()

            self._stop_events[camera_id] = stop_event

            self._states[camera_id] = CameraRuntimeState(
                camera_id=camera_id,
                status="connecting",
                source=source,
            )

            thread = threading.Thread(
                target=self._capture_loop,
                args=(
                    camera_id,
                    source,
                    loop_video,
                    stop_event,
                ),
                name=f"camera-{camera_id}",
                daemon=True,
            )

            self._threads[camera_id] = thread

            thread.start()

            return self._states[camera_id].to_dict()

    def stop(
        self,
        camera_id: str,
        remove_frame: bool = True,
    ):

        with self._lock:
            event = self._stop_events.get(camera_id)
            thread = self._threads.get(camera_id)

        if event:
            event.set()

        with self._lock:
            capture = self._captures.get(camera_id)
        if capture is not None:
            capture.release()

        if thread and thread.is_alive():
            thread.join(timeout=3)

        with self._lock:

            state = self._states.get(camera_id)

            if state:
                state.status = "offline"

            self._threads.pop(camera_id, None)
            self._stop_events.pop(camera_id, None)
            self._captures.pop(camera_id, None)

        if remove_frame:
            self.frame_hub.remove(camera_id)

        return self.get_status(camera_id)

    def stop_all(self):

        with self._lock:
            ids = list(self._threads.keys())

        for camera_id in ids:
            self.stop(camera_id)

    def get_status(self, camera_id: str):

        with self._lock:

            state = self._states.get(camera_id)

            if state is None:
                return None

            return state.to_dict()

    def is_running(self, camera_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(camera_id)
            return bool(thread and thread.is_alive())

    @staticmethod
    def _normalize_source(source):

        if isinstance(source, int):
            return source

        value = str(source).strip()

        # "0" / "1" → webcam index
        if value.isdigit() and not Path(value).exists():
            return int(value)

        return value

    @staticmethod
    def _is_file(source):

        return (
            isinstance(source, str)
            and Path(source).is_file()
        )

    @staticmethod
    def _open_capture(source):

        # Webcam Windows
        if isinstance(source, int) and os.name == "nt":

            cap = cv2.VideoCapture(
                source,
                cv2.CAP_DSHOW
            )

            if cap.isOpened():
                return cap

            cap.release()

        return cv2.VideoCapture(source)

    def _capture_loop(
        self,
        camera_id,
        source,
        loop_video,
        stop_event,
    ):

        frame_id = -1

        is_file = self._is_file(source)

        while not stop_event.is_set():

            self._set_state(
                camera_id,
                status="connecting",
                error=None
            )

            cap = self._open_capture(source)

            with self._lock:
                self._captures[camera_id] = cap

            if not cap.isOpened():

                self._set_state(
                    camera_id,
                    status="offline",
                    error=f"Cannot open source: {source}"
                )

                cap.release()

                stop_event.wait(
                    self.reconnect_delay
                )

                continue

            # Quan trọng với video file:
            # OpenCV nếu không throttle sẽ đọc nhanh hết file.
            source_fps = cap.get(
                cv2.CAP_PROP_FPS
            )

            if source_fps <= 0:
                source_fps = 30.0

            frame_interval = (
                1.0 / source_fps
                if is_file
                else 0
            )

            next_frame_at = time.monotonic()

            try:

                while not stop_event.is_set():

                    ok, frame = cap.read()

                    if not ok:

                        if is_file:

                            if loop_video:

                                cap.set(
                                    cv2.CAP_PROP_POS_FRAMES,
                                    0
                                )

                                next_frame_at = (
                                    time.monotonic()
                                )

                                continue

                            self._set_state(
                                camera_id,
                                status="ended"
                            )

                            return

                        self._set_state(
                            camera_id,
                            status="offline",
                            error="Frame read failed"
                        )

                        break

                    if is_file:

                        now = time.monotonic()

                        wait_time = (
                            next_frame_at - now
                        )

                        if wait_time > 0:
                            stop_event.wait(
                                wait_time
                            )

                        next_frame_at += (
                            frame_interval
                        )

                    frame_id += 1

                    captured_at = time.time()

                    packet = FramePacket(
                        camera_id=camera_id,
                        frame_id=frame_id,
                        captured_at=captured_at,
                        frame=frame,
                    )

                    self.frame_hub.publish(packet)

                    self._set_state(
                        camera_id,
                        status="online",
                        frame_id=frame_id,
                        last_frame_at=captured_at,
                        error=None,
                    )

            except Exception as exc:

                logger.exception(
                    "Camera %s failed",
                    camera_id
                )

                self._set_state(
                    camera_id,
                    status="error",
                    error=str(exc)
                )

            finally:
                cap.release()
                with self._lock:
                    if self._captures.get(camera_id) is cap:
                        self._captures.pop(camera_id, None)

            if not is_file:

                stop_event.wait(
                    self.reconnect_delay
                )

        self._set_state(
            camera_id,
            status="offline"
        )

    def _set_state(
        self,
        camera_id,
        **changes
    ):

        with self._lock:

            state = self._states.get(
                camera_id
            )

            if state is None:
                return

            for key, value in changes.items():
                setattr(
                    state,
                    key,
                    value
                )
