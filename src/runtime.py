from src.config import get_settings
from src.services.camera_runtime import CameraRuntime
from src.services.camera_service import CameraNotFoundError, camera_service
from src.services.face_identity_service import face_gallery
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.synchronous_vision_manager import SynchronousVisionManager
from src.services.vision_manager import VisionManager
from src.vision.adapters.mock import MockVisionEngine
from src.vision.pipeline import RuntimeV2VisionPipeline


def build_vision_engine(settings, mock_event_frame_ids: set[int] | None = None):
    if settings.vision_engine == "mock":
        return MockVisionEngine(emit_event_on_frame_ids=mock_event_frame_ids)

    return RuntimeV2VisionPipeline(
        yolo_path=settings.vision_yolo_path,
        config_path=settings.vision_config_path,
        checkpoint_path=settings.vision_checkpoint_path,
        model_cache_dir=settings.vision_model_cache_dir,
        known_faces_dir=settings.vision_known_faces_dir,
        identity_enabled=settings.vision_identity_enabled,
        identity_provider=settings.vision_identity_provider,
        insightface_root=settings.vision_insightface_root,
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

        self.frame_hub = FrameHub()
        self.processed_frame_hub = FrameHub()
        self.vision_sample_buffer = sample_buffer

        if get_settings().vision_engine == "mock" or vision_engine is not None:
            self.camera = CameraRuntime(self.frame_hub)
            self.vision = VisionManager(
                frame_hub=self.frame_hub,
                engine=engine,
                event_dispatcher=event_dispatcher,
            )
        else:
            self.vision = SynchronousVisionManager(
                engine,
                event_dispatcher,
                processed_frame_hub=self.processed_frame_hub,
            )
            self.camera = CameraRuntime(
                self.frame_hub,
                vision_processor=self.vision.process,
            )
        self.stream = StreamService(
            self.frame_hub,
            vision=self.vision,
            processed_frame_hub=self.processed_frame_hub,
        )

    def start(self):
        self.vision.start()

    def restore_persisted_state(self) -> list[dict]:
        results = []
        for desired in camera_service.desired_states():
            camera_id = desired["id"]
            if desired["vision_enabled"]:
                self.vision.enable(camera_id)
                self.vision.set_identity_enabled(camera_id, desired.get("identity_enabled", False))
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
        if not enabled:
            return self.vision.disable(public_id)
        self.vision.enable(public_id)
        desired = next(item for item in camera_service.desired_states() if item["id"] == public_id)
        self.vision.set_identity_enabled(public_id, desired.get("identity_enabled", False))
        return self.vision.get_status(public_id)

    def restart_camera_if_enabled(self, camera_id: str) -> None:
        desired = next(item for item in camera_service.desired_states() if item["id"] == camera_service.public_id(camera_id))
        if not desired["camera_enabled"]:
            return
        public_id = desired["id"]
        if self.camera.is_running(public_id):
            self.camera.stop(public_id)
        self.start_persisted_camera(public_id, desired["loop_video"])

    def stop(self):
        self.camera.stop_all()
        self.vision.stop()
