import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
import threading
import time

import cv2

from src.services.frame_hub import FrameHub

VISION_OVERLAY_MAX_AGE_SECONDS = 0.75


class StreamService:

    def __init__(
        self,
        frame_hub: FrameHub,
        jpeg_quality: int = 80,
        vision=None,
        processed_frame_hub: FrameHub | None = None,
    ):

        self.frame_hub = frame_hub

        self.jpeg_quality = max(
            1,
            min(100, jpeg_quality)
        )
        self.vision = vision
        self.processed_frame_hub = processed_frame_hub
        self._jpeg_lock = threading.Lock()
        self._jpeg_samples = deque(maxlen=2048)

    def latest_jpeg(self, camera_id: str) -> tuple[bytes, int] | None:
        packet = self.frame_hub.get_latest(camera_id)
        if packet is None:
            return None
        encoded = self._encode_jpeg(packet.frame)
        if encoded is None:
            return None
        return encoded, packet.frame_id

    def mjpeg(
        self,
        camera_id: str
    ):

        last_frame_id = -1

        while True:

            packet = (
                self.frame_hub.wait_for_next(
                    camera_id=camera_id,
                    after_frame_id=last_frame_id,
                    timeout=2.0,
                )
            )

            if packet is None:
                continue

            last_frame_id = packet.frame_id

            jpg = self._encode_jpeg(packet.frame)
            if jpg is None:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n"
                b"\r\n"
                + jpg
                + b"\r\n"
            )

    async def mjpeg_async(
        self,
        camera_id: str,
        is_disconnected: Callable[[], Awaitable[bool]],
        *,
        show_boxes: bool = True,
        show_identity: bool = True,
        show_fall: bool = True,
    ):
        """Stream MJPEG without keeping shutdown alive after client disconnect."""
        last_frame_id = -1
        while not await is_disconnected():
            packet = await asyncio.to_thread(
                self.frame_hub.wait_for_next,
                camera_id,
                last_frame_id,
                0.5,
            )
            if packet is None:
                continue

            last_frame_id = packet.frame_id
            frame = packet.frame
            if self.vision is not None:
                from src.presentation.vision_overlay import render_vision

                result = self._fresh_vision_result(packet)
                identity_enabled = getattr(self.vision, "is_identity_enabled", None)
                show_current_identity = show_identity and (
                    identity_enabled(packet.camera_id) if identity_enabled is not None else True
                )
                frame = render_vision(
                    frame,
                    result,
                    show_boxes=show_boxes,
                    show_identity=show_current_identity,
                    show_fall=show_fall,
                )
            encoded = await asyncio.to_thread(self._encode_jpeg, frame)
            if encoded is None:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n"
                b"\r\n"
                + encoded
                + b"\r\n"
            )

    def _fresh_vision_result(self, packet):
        latest_result = getattr(self.vision, "latest_result", None)
        if latest_result is None:
            return None
        result = latest_result(packet.camera_id)
        if result is None:
            return None
        metadata = result.metadata
        if metadata.get("source_epoch") != packet.source_epoch:
            return None
        result_time = metadata.get("observation_time")
        if packet.source_timestamp is None or result_time is None:
            return None
        age = packet.source_timestamp - float(result_time)
        if age < 0 or age > VISION_OVERLAY_MAX_AGE_SECONDS:
            return None
        return result

    def _encode_jpeg(self, frame) -> bytes | None:
        started = time.perf_counter()
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with self._jpeg_lock:
            self._jpeg_samples.append((time.monotonic(), elapsed_ms))
        return encoded.tobytes() if ok else None

    def jpeg_profile_samples(self) -> list[tuple[float, float]]:
        """Return bounded encode timing samples for operational profiling."""
        with self._jpeg_lock:
            return list(self._jpeg_samples)
