from pathlib import Path
import time

import cv2
import pytest

from sda_vision import FaceEncoder, FaceEncoderConfig, IdentityGalleryEntry, IdentityGallerySnapshot
from sda_vision.runtime.identity import IdentityStage, IdentityState


ROOT = Path(__file__).resolve().parents[1]
FACE = ROOT / "register face" / "Dai" / "frame_0000.jpg"
MODEL = Path.home() / ".insightface" / "models" / "buffalo_l" / "w600k_r50.onnx"


def _wait_result(stage, previous_count, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = stage.poll()
        if stage.frames_processed > previous_count:
            return result
        time.sleep(0.02)
    pytest.fail("Identity child did not return a result")


def _wait_gallery(stage, version, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = stage.poll_status() or {}
        if status.get("gallery_version") == version:
            return status
        time.sleep(0.02)
    pytest.fail(f"Identity child did not apply gallery {version}")


@pytest.mark.skipif(not FACE.exists() or not MODEL.exists(),
                    reason="local buffalo_l model and valid face fixture required")
def test_real_spawned_identity_child_accepts_live_supplied_gallery():
    image = cv2.imread(str(FACE))
    assert image is not None
    encoded = FaceEncoder(FaceEncoderConfig(device="cpu")).encode(FACE.read_bytes())
    stage = IdentityStage(
        ["CPUExecutionProvider"], ROOT / "register face", ROOT / "unused-live-cache.npz",
        gallery_mode="supplied", gallery_snapshot=IdentityGallerySnapshot(1))
    try:
        started = time.perf_counter()
        stage.start()
        assert stage._ready.wait(60), "real Identity child did not become ready"
        ready_ms = (time.perf_counter() - started) * 1000.0
        pid = stage._process.pid
        ready = stage.poll_status()
        assert ready and ready.get("model_ms", 0) > 0
        model_ms = ready["model_ms"]
        bbox = (0, 0, image.shape[1], image.shape[0])

        before = stage.frames_processed
        assert stage.submit(image, bbox, now=1.0)
        assert _wait_result(stage, before).state == IdentityState.UNKNOWN

        stage.update_gallery(IdentityGallerySnapshot(
            2, (IdentityGalleryEntry("test-person", "Test Name", encoded.embedding),)))
        applied_v2 = _wait_gallery(stage, 2)
        assert applied_v2["gallery_entries"] == 1
        assert applied_v2["gallery_apply_ms"] >= 0
        before = stage.frames_processed
        assert stage.submit(image, bbox, now=2.0)
        known = _wait_result(stage, before)
        assert known.state == IdentityState.LOCKED_KNOWN
        assert (known.person_id, known.name) == ("test-person", "Test Name")

        stage.update_gallery(IdentityGallerySnapshot(3))
        assert stage.result.state == IdentityState.UNVERIFIED
        applied_v3 = _wait_gallery(stage, 3)
        assert applied_v3["gallery_entries"] == 0
        before = stage.frames_processed
        assert stage.submit(image, bbox, now=3.0)
        removed = _wait_result(stage, before)
        assert removed.state != IdentityState.LOCKED_KNOWN
        assert removed.person_id is None

        assert stage._process.pid == pid
        assert stage._process.is_alive()
        assert stage.gallery_status["model_ms"] == model_ms
        print({"child_pid": pid, "ready_ms": ready_ms, "model_ms": model_ms,
               "v2_apply_ms": applied_v2["gallery_apply_ms"],
               "v3_apply_ms": applied_v3["gallery_apply_ms"],
               "v2_state": known.state.value, "v3_state": removed.state.value})
    finally:
        stage.stop(timeout=5)
    assert not stage._process.is_alive()


@pytest.mark.skipif(not FACE.exists() or not MODEL.exists(),
                    reason="local buffalo_l model and valid face fixture required")
def test_real_spawned_identity_child_uses_directml_when_available():
    import onnxruntime as ort

    if "DmlExecutionProvider" not in ort.get_available_providers():
        pytest.skip("DmlExecutionProvider is unavailable")
    image = cv2.imread(str(FACE))
    encoded = FaceEncoder(FaceEncoderConfig(device="directml", detector_size=640)).encode(
        FACE.read_bytes())
    snapshot = IdentityGallerySnapshot(
        1, (IdentityGalleryEntry("test-person", "Test Name", encoded.embedding),))
    stage = IdentityStage(
        ["DmlExecutionProvider", "CPUExecutionProvider"],
        ROOT / "register face", ROOT / "unused-live-cache.npz",
        det_size=640, gallery_mode="supplied", gallery_snapshot=snapshot)
    try:
        stage.start()
        assert stage._ready.wait(60), "DirectML Identity child did not become ready"
        status = stage.poll_status()
        assert status and status.get("startup_error") is None
        assert status["requested_providers"][0] == "DmlExecutionProvider"
        assert status["effective_providers"][0] == "DmlExecutionProvider"
        bbox = (0, 0, image.shape[1], image.shape[0])
        before = stage.frames_processed
        assert stage.submit(image, bbox, now=1.0)
        known = _wait_result(stage, before)
        assert known.state == IdentityState.LOCKED_KNOWN
        assert known.face_found is True
    finally:
        stage.stop(timeout=5)
    assert not stage._process.is_alive()
