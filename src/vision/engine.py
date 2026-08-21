from abc import ABC, abstractmethod

from src.models.frame import FramePacket
from src.models.vision import VisionResult
from src.vision.session import VisionSession


class VisionEngine(ABC):
    def start(self):
        pass

    def prepare_camera(self, camera_id: str, session: VisionSession) -> None:
        """Optionally initialize per-camera state before capture starts."""
        del camera_id, session

    def release_camera(self, camera_id: str) -> None:
        """Optionally release mutable resources owned by one camera."""
        del camera_id

    @abstractmethod
    def process(
        self,
        packet: FramePacket,
        session: VisionSession,
    ) -> VisionResult:
        pass

    def stop(self):
        pass
