import time

from src.models.frame import FramePacket
from src.models.vision import VisionResult
from src.vision.engine import VisionEngine
from src.vision.session import VisionSession


class MockVisionEngine(VisionEngine):
    """Model-free engine used only to verify local Vision wiring."""

    def __init__(self, raise_on_camera_ids: set[str] | None = None) -> None:
        self.raise_on_camera_ids = set(raise_on_camera_ids or ())

    def process(self, packet: FramePacket, session: VisionSession) -> VisionResult:
        started = time.perf_counter()
        if packet.camera_id in self.raise_on_camera_ids:
            raise RuntimeError(f"Mock Vision failure for {packet.camera_id}")
        return VisionResult(
            camera_id=packet.camera_id,
            frame_id=packet.frame_id,
            captured_at=packet.captured_at,
            processed_at=time.time(),
            processing_ms=(time.perf_counter() - started) * 1000,
            metadata={"engine": "mock", "dropped_frames": session.dropped_frames},
        )
