import pytest
from pydantic import ValidationError
from sda_vision import VisionSession, VisionSessionConfig
from sda_vision.runtime.hardware import (
    FaceAccelerationError,
    HardwareCapabilities,
    resolve_action_backend,
    resolve_face_providers,
)

from src.config import Settings
from src.integrations.sda_identity import SdaFaceEmbeddingEncoder


def test_intel_resolves_openvino_action_and_directml_face_independently():
    caps = HardwareCapabilities(
        openvino_gpu=True,
        openvino_gpu_name="Intel Iris Xe",
        adapter_names=("Intel Iris Xe",),
    )
    assert resolve_action_backend("auto", caps).backend == "openvino"
    face = resolve_face_providers("auto", caps, ["DmlExecutionProvider", "CPUExecutionProvider"], "Windows")
    assert face.backend == "ONNX Runtime DirectML"
    assert face.providers[0] == "DmlExecutionProvider"


def test_intel_missing_directml_is_an_error_not_cpu_identity():
    caps = HardwareCapabilities(openvino_gpu=True, adapter_names=("Intel Iris Xe",))
    assert resolve_action_backend("auto", caps).backend == "openvino"
    with pytest.raises(FaceAccelerationError, match="DmlExecutionProvider"):
        resolve_face_providers("auto", caps, ["CPUExecutionProvider"], "Windows")


def test_nvidia_resolves_cuda_for_both_heavy_stages():
    caps = HardwareCapabilities(torch_cuda=True, torch_device_name="RTX")
    assert resolve_action_backend("auto", caps).backend == "torch_cuda"
    face = resolve_face_providers("auto", caps, ["CUDAExecutionProvider", "CPUExecutionProvider"], "Windows")
    assert face.providers == ("CUDAExecutionProvider", "CPUExecutionProvider")


def test_amd_windows_resolves_directml_for_both_heavy_stages():
    caps = HardwareCapabilities(
        directml_usable=True,
        directml_device_name="AMD Radeon",
        adapter_names=("AMD Radeon",),
    )
    assert resolve_action_backend("auto", caps).backend == "torch_directml"
    assert resolve_face_providers("auto", caps, ["DmlExecutionProvider"], "Windows").device == "DirectML"


def test_amd_linux_keeps_rocm_action_and_rejects_unsupported_face_gpu():
    caps = HardwareCapabilities(torch_cuda=True, torch_hip=True, torch_device_name="Radeon")
    assert resolve_action_backend("auto", caps).backend == "torch_rocm"
    with pytest.raises(FaceAccelerationError, match="AMD Linux"):
        resolve_face_providers("auto", caps, ["CPUExecutionProvider"], "Linux")


def test_cpu_only_and_explicit_cpu_resolve_both_heavy_stages_to_cpu():
    caps = HardwareCapabilities()
    assert resolve_action_backend("auto", caps).backend == "cpu"
    assert resolve_face_providers("auto", caps, ["CPUExecutionProvider"], "Linux").device == "CPU"
    assert resolve_action_backend("cpu", caps).backend == "cpu"
    assert resolve_face_providers("cpu", caps, ["CPUExecutionProvider"], "Windows").device == "CPU"


def test_face_only_selects_supported_present_provider():
    caps = HardwareCapabilities(torch_cuda=True, torch_device_name="RTX")
    with pytest.raises(FaceAccelerationError):
        resolve_face_providers("auto", caps, ["DmlExecutionProvider", "CPUExecutionProvider"], "Windows")


def test_face_acceleration_failure_does_not_raise_on_fall_session(monkeypatch):
    caps = HardwareCapabilities(openvino_gpu=True, adapter_names=("Intel Iris Xe",))
    monkeypatch.setattr("sda_vision.session.probe_capabilities", lambda: caps)
    monkeypatch.setattr("sda_vision.session.ort.get_available_providers", lambda: ["CPUExecutionProvider"])
    session = VisionSession(VisionSessionConfig(device="auto", identity_enabled=True, preview="none"))
    session._start_identity_stage()
    assert session.identity_stage is None
    assert "DmlExecutionProvider" in session.face_startup_error
    assert session.backend.backend == "openvino"


def test_enrollment_directml_setting_uses_dedicated_face_contract():
    encoder = SdaFaceEmbeddingEncoder.__new__(SdaFaceEmbeddingEncoder)
    SdaFaceEmbeddingEncoder.__init__(encoder, insightface_root=".", provider="directml")
    assert encoder._encoder.config.device == "directml"


def test_application_device_contract_rejects_unimplemented_multi_gpu_index():
    with pytest.raises(ValidationError, match="VISION_DEVICE"):
        Settings(vision_device="cuda:1")
