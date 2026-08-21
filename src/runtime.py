from src.config import get_settings
from src.services.camera_service import CameraNotFoundError, camera_service
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService


def build_vision_engine(settings, mock_event_frame_ids: set[int] | None = None):
    # Explicit development rollback/test factory; never a production fallback.
    from src.integrations.legacy_vision import build_legacy_vision_engine

    return build_legacy_vision_engine(settings, mock_event_frame_ids)


class LocalRuntime:

    def __init__(
        self,
        vision_engine=None,
        event_dispatcher=None,
        mock_event_frame_ids: set[int] | None = None,
    ):

        settings = get_settings()
        engine = vision_engine

        self.frame_hub = FrameHub()
        self.processed_frame_hub = FrameHub()
        self.vision_sample_buffer = None

        if settings.vision_engine == "sda" and vision_engine is None:
            from src.integrations.sda_vision import SdaCameraFacade, SdaSessionRegistry, SdaVisionFacade

            self.sda = SdaSessionRegistry(
                self.frame_hub,
                settings=settings,
                event_dispatcher=event_dispatcher,
            )
            from src.services.face_gallery_provider import face_gallery_coordinator
            from src.integrations.sda_identity import SdaGalleryPublisher
            self._face_gallery_coordinator = face_gallery_coordinator
            self._sda_gallery_publisher = SdaGalleryPublisher(self.sda)
            self._face_gallery_coordinator.set_publisher(self._sda_gallery_publisher)
            self._face_gallery_coordinator.refresh_after_commit()
            self.camera = SdaCameraFacade(self.sda)
            self.vision = SdaVisionFacade(self.sda)
        else:
            from src.integrations.legacy_vision import build_legacy_runtime

            self.camera, self.vision = build_legacy_runtime(
                self.frame_hub,
                settings=settings,
                engine=engine,
                event_dispatcher=event_dispatcher,
                mock_event_frame_ids=mock_event_frame_ids,
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
            options = {}
            if hasattr(self, "sda"):
                options["location"] = camera_service.get_camera(camera_id)["location"]
            return self.camera.start(public_id, source, loop_video=loop_video, **options)
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
        if hasattr(self, "_face_gallery_coordinator"):
            self._face_gallery_coordinator.clear_publisher(self._sda_gallery_publisher)
