import time

from src.models.frame import FramePacket
from src.models.vision import VisionEvent, VisionResult
from src.vision.engine import VisionEngine
from src.vision.session import VisionSession


class MockVisionEngine(VisionEngine):
    """Model-free engine used only to verify local Vision wiring."""

    def __init__(
        self,
        raise_on_camera_ids: set[str] | None = None,
        emit_event_on_frame_ids: set[int] | None = None,
    ) -> None:
        self.raise_on_camera_ids = set(raise_on_camera_ids or ())
        self.emit_event_on_frame_ids = set(emit_event_on_frame_ids or ())

    def process(self, packet: FramePacket, session: VisionSession) -> VisionResult:
        started = time.perf_counter()
        if packet.camera_id in self.raise_on_camera_ids:
            raise RuntimeError(f"Mock Vision failure for {packet.camera_id}")
        events = []
        if packet.frame_id in self.emit_event_on_frame_ids:
            events.append(VisionEvent(type="fall", confidence=0.95, metadata={"camera_location": packet.camera_id}))
        return VisionResult(
            camera_id=packet.camera_id,
            frame_id=packet.frame_id,
            captured_at=packet.captured_at,
            processed_at=time.time(),
            processing_ms=(time.perf_counter() - started) * 1000,
            events=events,
            metadata={"engine": "mock", "dropped_frames": session.dropped_frames},
        )
