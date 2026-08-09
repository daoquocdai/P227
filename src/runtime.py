from src.services.camera_runtime import CameraRuntime
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.vision_manager import VisionManager
from src.vision.adapters.mock import MockVisionEngine


class LocalRuntime:

    def __init__(
        self,
        vision_engine=None,
    ):

        self.frame_hub = FrameHub()

        self.camera = CameraRuntime(
            self.frame_hub
        )

        self.stream = StreamService(
            self.frame_hub
        )

        self.vision = VisionManager(
            frame_hub=self.frame_hub,
            engine=(
                vision_engine
                or MockVisionEngine()
            ),
        )

    def start(self):
        self.vision.start()

    def stop(self):
        self.vision.stop()
        self.camera.stop_all()
