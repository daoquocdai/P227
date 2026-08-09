from abc import ABC, abstractmethod

from src.models.frame import FramePacket
from src.models.vision import VisionResult
from src.vision.session import VisionSession


class VisionEngine(ABC):

    def start(self):
        pass

    @abstractmethod
    def process(
        self,
        packet: FramePacket,
        session: VisionSession,
    ) -> VisionResult:
        pass

    def stop(self):
        pass