"""Temporary factory retained only for rollback-oriented legacy tests."""


def build_legacy_vision_engine(settings, mock_event_frame_ids=None):
    if settings.vision_engine == "mock":
        from src.vision.adapters.mock import MockVisionEngine

        return MockVisionEngine(emit_event_on_frame_ids=mock_event_frame_ids)

    from src.services.face_identity_service import face_gallery
    from src.vision.pipeline import CanonicalVisionPipeline

    return CanonicalVisionPipeline(
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


def build_legacy_runtime(frame_hub, *, settings, engine=None, event_dispatcher=None,
                         mock_event_frame_ids=None):
    """Construct the quarantined capture/worker stack only on explicit rollback."""
    from src.services.camera_runtime import CameraRuntime
    from src.services.vision_manager import VisionManager

    selected = engine or build_legacy_vision_engine(settings, mock_event_frame_ids)
    return (
        CameraRuntime(frame_hub),
        VisionManager(frame_hub=frame_hub, engine=selected,
                      event_dispatcher=event_dispatcher),
    )


def resolve_legacy_identity_execution(provider):
    """Temporary Phase 3 seam for the enrollment encoder; replace in Phase 4."""
    from src.vision.runtime import VisionRuntimeResolver

    return VisionRuntimeResolver.resolve_identity_execution(
        VisionRuntimeResolver.available_ort_providers(), provider)
