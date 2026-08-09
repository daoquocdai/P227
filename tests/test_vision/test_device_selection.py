from types import SimpleNamespace

import pytest
import torch
from pydantic import ValidationError

from src.config import Settings
from src.vision.adapters.legacy import (
    LegacyVisionEngine,
    LegacyVisionInitializationError,
)


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
    [(" AUTO ", "auto"), ("CPU", "cpu"), ("CUDA", "cuda"), ("CUDA:2", "cuda:2")],
)
def test_settings_normalizes_supported_vision_devices(configured, expected):
    assert Settings(vision_device=configured).vision_device == expected


@pytest.mark.parametrize("configured", ["gpu", "cuda:-1", "cuda:any", "cuda:0:1", ""])
def test_settings_rejects_invalid_vision_devices(configured):
    with pytest.raises(ValidationError, match="VISION_DEVICE"):
        Settings(vision_device=configured)


def test_auto_prefers_cuda_zero_and_exposes_stage_diagnostics():
    engine = LegacyVisionEngine(device="auto")

    selected = engine._select_torch_device(FakeTorch(available=True, count=2))

    assert str(selected) == "cuda:0"
    assert engine.device_diagnostics() == {
        "requested_device": "auto",
        "actual_device": "cuda:0",
        "cuda_available": True,
        "cuda_device_count": 2,
        "device_name": "Fake NVIDIA 0",
        "torch_version": "2.5.1+cu121",
        "torch_cuda_build": "12.1",
        "stages": {
            "yolo": "cuda:0",
            "pose": "cpu",
            "preprocessing": "cpu",
            "sda_gcn": "cuda:0",
        },
    }


def test_cpu_forces_cpu_even_when_cuda_is_available():
    engine = LegacyVisionEngine(device="cpu")

    selected = engine._select_torch_device(FakeTorch(available=True, count=2))

    assert str(selected) == "cpu"
    assert engine.device_diagnostics()["actual_device"] == "cpu"


def test_auto_falls_back_to_cpu_when_cuda_is_unavailable():
    engine = LegacyVisionEngine(device="auto")

    selected = engine._select_torch_device(FakeTorch(available=False))

    assert str(selected) == "cpu"
    assert engine.device_diagnostics()["cuda_available"] is False


def test_explicit_cuda_does_not_fall_back_when_unavailable():
    engine = LegacyVisionEngine(device="cuda")

    with pytest.raises(LegacyVisionInitializationError, match="CUDA is unavailable"):
        engine._select_torch_device(FakeTorch(available=False))

    diagnostics = engine.device_diagnostics()
    assert diagnostics["requested_device"] == "cuda"
    assert diagnostics["actual_device"] is None
    assert diagnostics["cuda_available"] is False


def test_explicit_cuda_index_is_validated():
    engine = LegacyVisionEngine(device="cuda:2")

    with pytest.raises(LegacyVisionInitializationError, match=r"only 2 CUDA device\(s\)"):
        engine._select_torch_device(FakeTorch(available=True, count=2))


def test_direct_engine_rejects_invalid_device_without_loading_models():
    with pytest.raises(ValueError, match="device must be"):
        LegacyVisionEngine(device="intel")
