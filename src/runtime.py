from src.config import get_settings
from src.services.camera_runtime import CameraRuntime
from src.services.camera_service import CameraNotFoundError, camera_service
from src.services.face_identity_service import face_gallery
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.vision_manager import VisionManager
from src.services.vision_sample_buffer import VisionSampleBuffer
from src.vision.adapters.mock import MockVisionEngine


def build_vision_engine(settings, mock_event_frame_ids: set[int] | None = None):
    if settings.vision_engine == "mock":
        return MockVisionEngine(emit_event_on_frame_ids=mock_event_frame_ids)

    if settings.vision_engine == "legacy_v2":
        from src.vision.adapters.v2 import V2VisionEngine

        engine_class = V2VisionEngine
        config_path = settings.vision_v2_config_path
        checkpoint_path = settings.vision_v2_checkpoint_path
    else:
        from src.vision.adapters.legacy import LegacyVisionEngine

        engine_class = LegacyVisionEngine
        config_path = settings.vision_legacy_config_path
        checkpoint_path = settings.vision_legacy_checkpoint_path

    return engine_class(
        yolo_path=settings.vision_legacy_yolo_path,
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        known_faces_dir=settings.vision_legacy_known_faces_dir,
        identity_enabled=settings.vision_legacy_identity_enabled,
        identity_provider=settings.vision_legacy_identity_provider,
        insightface_root=settings.vision_legacy_insightface_root,
        device=settings.vision_device,
        face_gallery=face_gallery,
    )


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
            engine = build_vision_engine(settings, mock_event_frame_ids)
            if settings.vision_engine != "mock":
                sample_buffer = VisionSampleBuffer(
                    target_sample_rate=settings.vision_temporal_target_sample_rate,
                    legacy_skip_factor=2,
                    capacity=settings.vision_temporal_buffer_capacity,
                )

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

    def restore_persisted_state(self) -> list[dict]:
        results = []
        for desired in camera_service.desired_states():
            camera_id = desired["id"]
            if desired["vision_enabled"]:
                self.vision.enable(camera_id)
            else:
                self.vision.disable(camera_id)
            if desired["camera_enabled"]:
                results.append(self.start_persisted_camera(camera_id, desired["loop_video"]))
            else:
                results.append({"camera_id": camera_id, "status": "offline"})
        return results

    def start_persisted_camera(self, camera_id: str, loop_video: bool | None = None) -> dict:
        public_id = camera_service.public_id(camera_id)
        if self.camera.is_running(public_id):
            return self.camera.get_status(public_id) or {"camera_id": public_id, "status": "connecting"}
        try:
            public_id, source = camera_service.resolve_source(camera_id)
            if loop_video is None:
                desired = next(item for item in camera_service.desired_states() if item["id"] == public_id)
                loop_video = desired["loop_video"]
            return self.camera.start(public_id, source, loop_video=loop_video)
        except (CameraNotFoundError, ValueError, OSError) as exc:
            return self.camera.set_unavailable(public_id, str(exc))

    def set_camera_enabled(self, camera_id: str, enabled: bool) -> dict:
        camera_service.set_camera_enabled(camera_id, enabled)
        public_id = camera_service.public_id(camera_id)
        if enabled:
            return self.start_persisted_camera(public_id)
        return self.camera.stop(public_id) or {"camera_id": public_id, "status": "offline"}

    def set_vision_enabled(self, camera_id: str, enabled: bool) -> dict:
        camera_service.set_vision_enabled(camera_id, enabled)
        public_id = camera_service.public_id(camera_id)
        return self.vision.enable(public_id) if enabled else self.vision.disable(public_id)

    def restart_camera_if_enabled(self, camera_id: str) -> None:
        desired = next(item for item in camera_service.desired_states() if item["id"] == camera_service.public_id(camera_id))
        if not desired["camera_enabled"]:
            return
        public_id = desired["id"]
        if self.camera.is_running(public_id):
            self.camera.stop(public_id)
        self.start_persisted_camera(public_id, desired["loop_video"])

    def stop(self):
        self.vision.stop()
        self.camera.stop_all()
