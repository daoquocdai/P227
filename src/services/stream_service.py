import asyncio
from collections.abc import Awaitable, Callable

import cv2

from src.services.frame_hub import FrameHub


class StreamService:

    def __init__(
        self,
        frame_hub: FrameHub,
        jpeg_quality: int = 80,
    ):

        self.frame_hub = frame_hub

        self.jpeg_quality = max(
            1,
            min(100, jpeg_quality)
        )

    def latest_jpeg(self, camera_id: str) -> tuple[bytes, int] | None:
        packet = self.frame_hub.get_latest(camera_id)
        if packet is None:
            return None
        ok, encoded = cv2.imencode(
            ".jpg",
            packet.frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        if not ok:
            return None
        return encoded.tobytes(), packet.frame_id

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

            ok, encoded = cv2.imencode(
                ".jpg",
                packet.frame,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    self.jpeg_quality
                ]
            )

            if not ok:
                continue

            jpg = encoded.tobytes()

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
            encoded = await asyncio.to_thread(self._encode_jpeg, packet.frame)
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

    def _encode_jpeg(self, frame) -> bytes | None:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        return encoded.tobytes() if ok else None
