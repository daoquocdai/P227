from unittest.mock import Mock

from src.runtime import LocalRuntime
from src.services.camera_service import camera_service
from src.vision.adapters.mock import MockVisionEngine


def test_restore_persisted_state_isolates_invalid_camera(monkeypatch):
    runtime = LocalRuntime(vision_engine=MockVisionEngine())
    desired = [
        {"id": "active", "camera_enabled": True, "vision_enabled": True, "loop_video": True},
        {"id": "invalid", "camera_enabled": True, "vision_enabled": False, "loop_video": False},
        {"id": "inactive", "camera_enabled": False, "vision_enabled": False, "loop_video": False},
    ]
    monkeypatch.setattr(camera_service, "desired_states", lambda: desired)
    monkeypatch.setattr(camera_service, "public_id", lambda camera_id: camera_id)
    monkeypatch.setattr(
        camera_service,
        "get_camera",
        lambda camera_id: {"source_kind": "video_file", "location": camera_id},
    )

    def resolve(camera_id):
        if camera_id == "invalid":
            raise ValueError("missing source")
        return camera_id, "source.mp4"

    monkeypatch.setattr(camera_service, "resolve_source", resolve)
    monkeypatch.setattr(runtime.camera, "start", Mock(return_value={"camera_id": "active", "status": "connecting"}))
    unavailable = Mock(side_effect=lambda camera_id, error: {"camera_id": camera_id, "status": "error", "error": error})
    monkeypatch.setattr(runtime.camera, "set_unavailable", unavailable)

    restored = runtime.restore_persisted_state()

    assert [item["status"] for item in restored] == ["connecting", "error", "offline"]
    runtime.camera.start.assert_called_once_with("active", "source.mp4", loop_video=True)
    unavailable.assert_called_once_with("invalid", "missing source")
    assert runtime.vision.get_status("active")["enabled"] is True
    assert runtime.vision.get_status("invalid")["enabled"] is False


def test_restore_persisted_state_ignores_legacy_identity_values(monkeypatch):
    runtime = LocalRuntime(vision_engine=MockVisionEngine())
    desired = [
        {
            "id": "explicit-on",
            "camera_enabled": False,
            "vision_enabled": True,
            "loop_video": False,
            "identity_enabled": True,
        },
        {
            "id": "explicit-off",
            "camera_enabled": False,
            "vision_enabled": True,
            "loop_video": False,
            "identity_enabled": False,
        },
        {
            "id": "missing-fallback",
            "camera_enabled": False,
            "vision_enabled": True,
            "loop_video": False,
        },
    ]
    monkeypatch.setattr(camera_service, "desired_states", lambda: desired)

    runtime.restore_persisted_state()

    assert runtime.vision.get_status("explicit-on")["enabled"] is True
    assert runtime.vision.get_status("explicit-off")["enabled"] is True
    assert runtime.vision.get_status("missing-fallback")["enabled"] is True
