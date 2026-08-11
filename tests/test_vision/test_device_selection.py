import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from src.config import Settings
from src.vision.pipeline import CanonicalVisionPipeline, VisionInitializationError
from src.vision.runtime import OpenVINOActionModel, VisionRuntimeResolver


class FakeCuda:
    def __init__(self, *, available: bool, count: int = 0) -> None:
        self._available = available
        self._count = count

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._count

    def get_device_name(self, device) -> str:
        return f"Fake NVIDIA {device.index}"


class FakeTorch:
    __version__ = "2.5.1+cu121"
    version = SimpleNamespace(cuda="12.1")
    device = staticmethod(torch.device)

    def __init__(self, *, available: bool, count: int = 0) -> None:
        self.cuda = FakeCuda(available=available, count=count)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (" AUTO ", "auto"),
        ("CPU", "cpu"),
        ("CUDA", "cuda"),
        ("CUDA:2", "cuda:2"),
    ],
)
def test_settings_normalizes_supported_vision_devices(configured, expected):
    assert Settings(vision_device=configured).vision_device == expected


@pytest.mark.parametrize("configured", ["gpu", "cuda:-1", "cuda:any", "cuda:0:1", ""])
def test_settings_rejects_invalid_vision_devices(configured):
    with pytest.raises(ValidationError, match="VISION_DEVICE"):
        Settings(vision_device=configured)


def test_auto_prefers_cuda_zero_and_exposes_stage_diagnostics():
    engine = CanonicalVisionPipeline(device="auto")

    selected = engine._select_torch_device(FakeTorch(available=True, count=2))

    assert str(selected) == "cuda:0"
    diagnostics = engine.device_diagnostics()
    assert diagnostics["requested_device"] == "auto"
    assert diagnostics["actual_device"] == "cuda:0"
    assert diagnostics["device_name"] == "Fake NVIDIA 0"
    assert diagnostics["runtime"] == "pytorch"
    assert diagnostics["accelerated"] is True
    assert diagnostics["fallback_reason"] is None
    assert diagnostics["stages"]["sda_gcn"] == "cuda:0"


def test_cpu_forces_cpu_even_when_cuda_is_available():
    engine = CanonicalVisionPipeline(device="cpu")

    selected = engine._select_torch_device(FakeTorch(available=True, count=2))

    assert str(selected) == "cpu"
    assert engine.device_diagnostics()["actual_device"] == "cpu"


def test_auto_falls_back_to_cpu_when_cuda_is_unavailable():
    engine = CanonicalVisionPipeline(device="auto")

    selected = engine._select_torch_device(FakeTorch(available=False))

    assert str(selected) == "cpu"
    assert engine.device_diagnostics()["cuda_available"] is False


def test_explicit_cuda_does_not_fall_back_when_unavailable():
    engine = CanonicalVisionPipeline(device="cuda")

    with pytest.raises(VisionInitializationError, match="CUDA is unavailable"):
        engine._select_torch_device(FakeTorch(available=False))

    diagnostics = engine.device_diagnostics()
    assert diagnostics["requested_device"] == "cuda"
    assert diagnostics["actual_device"] is None
    assert diagnostics["cuda_available"] is False


def test_explicit_cuda_index_is_validated():
    engine = CanonicalVisionPipeline(device="cuda:2")

    with pytest.raises(VisionInitializationError, match=r"only 2 CUDA device\(s\)"):
        engine._select_torch_device(FakeTorch(available=True, count=2))


def test_direct_engine_rejects_invalid_device_without_loading_models():
    with pytest.raises(ValueError, match="device must be"):
        CanonicalVisionPipeline(device="intel")


def test_openvino_action_model_serializes_shared_infer_request():
    class CompiledModel:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def __call__(self, values):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return {"output": np.zeros((values.shape[0], 5), dtype=np.float32)}

    compiled = CompiledModel()
    model = OpenVINOActionModel(compiled, torch)
    inputs = torch.zeros((1, 3, 64, 25, 1), dtype=torch.float32)
    threads = [threading.Thread(target=model, args=(inputs,)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert compiled.max_active == 1


def test_auto_detector_keeps_native_cuda_instead_of_selecting_intel_openvino(tmp_path):
    path, device, diagnostics = VisionRuntimeResolver.resolve_detector(
        object,
        tmp_path / "unused.pt",
        tmp_path,
        "auto",
        torch.device("cuda:0"),
    )

    assert path == tmp_path / "unused.pt"
    assert device == "cuda:0"
    assert diagnostics == {"runtime": "pytorch", "device": "cuda:0", "fallback_reason": None}


def test_auto_action_model_keeps_native_cuda():
    class CudaModel:
        def parameters(self):
            yield SimpleNamespace(device=torch.device("cuda:0"))

    model = CudaModel()
    resolved, diagnostics = VisionRuntimeResolver.resolve_action_model(
        model,
        None,
        None,
        None,
        "auto",
        torch,
    )

    assert resolved is model
    assert diagnostics == {"runtime": "pytorch", "device": "cuda:0", "fallback_reason": None}


def test_auto_identity_prefers_cuda_provider_over_directml(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            get_available_providers=lambda: [
                "DmlExecutionProvider",
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        ),
    )
    engine = CanonicalVisionPipeline(identity_provider="auto")

    providers, context_id = engine._identity_execution(torch.device("cuda:0"))

    assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert context_id == 0
