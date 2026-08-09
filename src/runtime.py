from src.config import get_settings
from src.services.camera_runtime import CameraRuntime
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.vision_manager import VisionManager
from src.services.vision_sample_buffer import VisionSampleBuffer
from src.vision.adapters.mock import MockVisionEngine


class LocalRuntime:

    def __init__(
        self,
        vision_engine=None,
        event_dispatcher=None,
        mock_event_frame_ids: set[int] | None = None,
    ):

        engine = vision_engine
        sample_buffer = None
        if engine is None:
            settings = get_settings()
            if settings.vision_engine == "legacy":
                # Keep heavy optional Vision imports out of Mock startup/tests.
                from src.vision.adapters.legacy import LegacyVisionEngine

                engine = LegacyVisionEngine(
                    yolo_path=settings.vision_legacy_yolo_path,
                    config_path=settings.vision_legacy_config_path,
                    checkpoint_path=settings.vision_legacy_checkpoint_path,
                    known_faces_dir=settings.vision_legacy_known_faces_dir,
                    identity_enabled=settings.vision_legacy_identity_enabled,
                    insightface_root=settings.vision_legacy_insightface_root,
                    device=settings.vision_device,
                )
                sample_buffer = VisionSampleBuffer(
                    target_sample_rate=settings.vision_temporal_target_sample_rate,
                    legacy_skip_factor=2,
                    capacity=settings.vision_temporal_buffer_capacity,
                )
            else:
                engine = MockVisionEngine(emit_event_on_frame_ids=mock_event_frame_ids)

        self.frame_hub = FrameHub()
        self.vision_sample_buffer = sample_buffer

        self.camera = CameraRuntime(
            self.frame_hub,
            vision_sample_buffer=sample_buffer,
        )

        self.stream = StreamService(
            self.frame_hub
        )

        self.vision = VisionManager(
            frame_hub=self.frame_hub,
            engine=engine,
            event_dispatcher=event_dispatcher,
            sample_buffer=sample_buffer,
        )

    def start(self):
        self.vision.start()

    def stop(self):
        self.vision.stop()
        self.camera.stop_all()
